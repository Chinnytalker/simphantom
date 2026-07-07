import json
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db import transaction as db_transaction
from django.db.models import F
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal
from services.fivesim import buy_number, check_order, cancel_order, get_products
from services import tigersms, grizzly as grizzlysms
from services.config import get_usd_to_ngn, FLAT_MARKUP_NGN, OTP_MARKUP_NGN
from .models import Order, Transaction, ProviderStats
from .serializers import OrderSerializer, TransactionSerializer

logger = logging.getLogger(__name__)

EXPIRY_MINUTES = 5
# With no SMS after this long, silently swap the number for a fresh one (once)
RETRY_AFTER_MINUTES = 2.5
MAX_RETRIES = 1


def compute_server_price(country, operator, product, service_type):
    """
    Authoritative price in NGN: live provider cost + our markup.
    Returns a Decimal, or None if no provider has stock/pricing for this combo.
    """
    markup = OTP_MARKUP_NGN if service_type == 'OTP_VERIFICATION' else FLAT_MARKUP_NGN

    cost_usd = None

    grizzly_country_id = grizzlysms.map_country(country)
    grizzly_service_code = grizzlysms.map_service(product)
    if grizzly_country_id and grizzly_service_code:
        info = grizzlysms.get_prices(grizzly_country_id).get(grizzly_service_code)
        if info and info.get('cost', 0) > 0:
            cost_usd = float(info['cost'])

    if cost_usd is None:
        products = get_products(country, operator)
        if isinstance(products, dict) and 'error' not in products:
            info = products.get(product)
            if isinstance(info, dict):
                try:
                    price = float(info.get('Price', 0))
                except (TypeError, ValueError):
                    price = 0.0
                if price > 0:
                    cost_usd = price

    if cost_usd is None:
        return None
    return Decimal(str(round(cost_usd * get_usd_to_ngn() + markup, 2)))


# ── Provider stats & routing ──────────────────────────────────────────────────

def record_attempt(provider, product, country):
    """A number was issued by this provider — count the attempt."""
    try:
        stats, _ = ProviderStats.objects.get_or_create(
            provider=provider, product=product, country=country or ''
        )
        ProviderStats.objects.filter(pk=stats.pk).update(total_orders=F('total_orders') + 1)
    except Exception:
        logger.exception('[Stats] failed to record attempt')


def record_success(provider, product, country):
    """An SMS code actually arrived — count the success."""
    try:
        stats, _ = ProviderStats.objects.get_or_create(
            provider=provider, product=product, country=country or ''
        )
        ProviderStats.objects.filter(pk=stats.pk).update(successful=F('successful') + 1)
    except Exception:
        logger.exception('[Stats] failed to record success')


def rank_providers(product, country):
    """
    Candidate providers ordered by real OTP delivery rate for this combo.
    Laplace-smoothed so a provider isn't written off (or crowned) on 1-2 orders;
    with no data both score 0.5 and Grizzly wins the tie (it performs better).
    """
    candidates = []
    if grizzlysms.map_country(country) and grizzlysms.map_service(product):
        candidates.append('grizzly')
    candidates.append('5sim')
    if len(candidates) == 1:
        return candidates

    stats = {
        s.provider: s
        for s in ProviderStats.objects.filter(product=product, country=country or '')
    }

    def score(provider):
        s = stats.get(provider)
        if not s:
            return 0.5
        return (s.successful + 1) / (s.total_orders + 2)

    # stable sort keeps grizzly first on equal scores
    return sorted(candidates, key=score, reverse=True)


def provider_price_ngn(provider, country, operator, product, service_type):
    """What buying from this provider would cost the user (cost + markup), or None."""
    markup = OTP_MARKUP_NGN if service_type == 'OTP_VERIFICATION' else FLAT_MARKUP_NGN
    cost_usd = None
    if provider == 'grizzly':
        gid = grizzlysms.map_country(country)
        scode = grizzlysms.map_service(product)
        if gid and scode:
            info = grizzlysms.get_prices(gid).get(scode)
            if info and info.get('cost', 0) > 0:
                cost_usd = float(info['cost'])
    else:
        products = get_products(country, operator)
        if isinstance(products, dict) and 'error' not in products:
            info = products.get(product)
            if isinstance(info, dict):
                try:
                    p = float(info.get('Price', 0))
                except (TypeError, ValueError):
                    p = 0.0
                if p > 0:
                    cost_usd = p
    if cost_usd is None:
        return None
    return Decimal(str(round(cost_usd * get_usd_to_ngn() + markup, 2)))


# A fallback/replacement provider is only used if its price stays in the same
# range as what the user was charged — we never quietly eat a dearer number.
PRICE_RANGE_TOLERANCE = Decimal('1.10')


def within_price_range(provider, order_budget, country, operator, product, service_type):
    candidate_price = provider_price_ngn(provider, country, operator, product, service_type)
    if candidate_price is None:
        return False
    return candidate_price <= order_budget * PRICE_RANGE_TOLERANCE


def purchase_from(provider, country, operator, product):
    """Buy a number from one specific provider. Returns provider order_data dict."""
    if provider == 'grizzly':
        gid = grizzlysms.map_country(country)
        scode = grizzlysms.map_service(product)
        if not (gid and scode):
            return {'error': 'grizzly mapping missing'}
        return grizzlysms.get_number(scode, gid)
    return buy_number(country, operator, product)


def cancel_at_provider(provider, provider_order_id):
    try:
        if provider == 'grizzly':
            grizzlysms.cancel_number(provider_order_id)
        elif provider == 'tigersms':
            tigersms.cancel_number(provider_order_id)
        else:
            cancel_order(provider_order_id)
    except Exception:
        pass


# ── Refund / SMS helpers ─────────────────────────────────────────────────────

def refund_order(user, order, new_status, description):
    """
    Refund an order's charge to the wallet exactly once, atomically.
    All refund paths (cancel, expiry, provider-side cancel) share one canonical
    reference so concurrent requests can never credit the wallet twice.
    Returns True if this call performed the refund, False if already refunded.
    """
    # Older code wrote refunds under three different reference formats —
    # treat any of them as "already refunded".
    legacy_refs = [
        f"REFUND-{order.id}",
        f"REFUND-EXPIRE-{order.id}",
        f"REFUND-CANCEL-{order.id}",
    ]
    with db_transaction.atomic():
        if Transaction.objects.filter(reference__in=legacy_refs).exists():
            Order.objects.filter(pk=order.pk).update(status=new_status)
            order.status = new_status
            return False

        _, created = Transaction.objects.get_or_create(
            reference=f"REFUND-{order.id}",
            defaults={
                'user': user,
                'amount': order.amount_charged,
                'type': 'CREDIT',
                'description': description,
            },
        )
        if created:
            get_user_model().objects.filter(pk=user.pk).update(
                wallet_balance=F('wallet_balance') + order.amount_charged
            )
        Order.objects.filter(pk=order.pk).update(status=new_status)
        order.status = new_status
    return created


def provider_sms(provider, provider_order_id):
    """Return the SMS code if one is already waiting at the provider, else None."""
    try:
        if provider in ('grizzly', 'tigersms'):
            mod = grizzlysms if provider == 'grizzly' else tigersms
            chk = mod.get_status(provider_order_id)
            if chk.get('status') == 'RECEIVED' and chk.get('code'):
                return chk['code']
        else:
            chk = check_order(provider_order_id)
            if not chk.get('error') and chk.get('sms'):
                return chk['sms'][0]['code']
    except Exception:
        pass
    return None


def deliver_sms(order, code):
    """
    Store a received code on the order and update delivery stats.
    Conditional update so a concurrent poll/worker can't double-count the
    success or trigger duplicate notifications. Returns True on transition.
    """
    updated = Order.objects.filter(pk=order.pk).exclude(status='RECEIVED').update(
        sms_code=code, status='RECEIVED'
    )
    order.sms_code = code
    order.status = 'RECEIVED'
    if updated:
        record_success(order.provider, order.product, order.country)
    return bool(updated)


def poll_provider(provider, provider_order_id):
    """Normalized provider status: {'status': PENDING|RECEIVED|CANCELED|ERROR, 'code': ...}."""
    try:
        if provider in ('grizzly', 'tigersms'):
            mod = grizzlysms if provider == 'grizzly' else tigersms
            data = mod.get_status(provider_order_id)
            if 'error' in data:
                return {'status': 'ERROR', 'code': None}
            return {'status': data['status'], 'code': data.get('code')}
        data = check_order(provider_order_id)
        if 'error' in data:
            return {'status': 'ERROR', 'code': None}
        if data.get('sms'):
            return {'status': 'RECEIVED', 'code': data['sms'][0]['code']}
        st = data.get('status', '')
        if st in ('CANCELED', 'EXPIRED', 'TIMEOUT', 'BANNED'):
            return {'status': 'CANCELED', 'code': None}
        return {'status': 'PENDING', 'code': None}
    except Exception:
        return {'status': 'ERROR', 'code': None}


def retry_with_fresh_number(order, old_provider):
    """
    Cancel a silent number and buy a replacement (best other provider first,
    same provider as fallback — a fresh number helps either way). Only buys
    if the replacement lands in the same price range the user already paid.
    Returns True if the order now carries a new number.
    """
    # Claim the retry atomically so a concurrent poll/worker can't double-buy
    claimed = Order.objects.filter(
        pk=order.pk, status='PENDING', retry_count=order.retry_count
    ).update(retry_count=order.retry_count + 1)
    if not claimed:
        return False
    order.retry_count += 1

    cancel_at_provider(old_provider, order.fivesim_order_id)

    candidates = rank_providers(order.product, order.country)
    # Prefer switching providers; keep the old one as a last resort
    candidates.sort(key=lambda p: p == old_provider)

    for candidate in candidates:
        if not within_price_range(
            candidate, order.amount_charged,
            order.country, order.operator or 'any', order.product, order.service_type,
        ):
            logger.info(
                '[Retry] %s skipped for order %s — price outside what the user paid',
                candidate, order.id,
            )
            continue
        order_data = purchase_from(
            candidate, order.country, order.operator or 'any', order.product
        )
        if 'error' in order_data:
            logger.warning(
                '[Retry] %s failed (%s) for order %s — trying next',
                candidate, order_data['error'], order.id,
            )
            continue

        creds = json.loads(order.credentials or '{}')
        creds['provider'] = candidate
        creds.setdefault('previous_numbers', []).append(order.phone)
        order.fivesim_order_id = str(order_data['id'])
        order.phone = order_data['phone']
        order.credentials = json.dumps(creds)
        order.expires_at = timezone.now() + timedelta(minutes=EXPIRY_MINUTES)
        order.save(update_fields=['fivesim_order_id', 'phone', 'credentials', 'expires_at'])
        record_attempt(candidate, order.product, order.country)
        logger.info(
            '[Retry] order %s swapped %s -> %s (%s)',
            order.id, old_provider, candidate, order.phone,
        )
        return True

    # Nobody could sell us a replacement — undo the claim so the normal
    # expiry path refunds the user at the 5-minute mark as usual.
    Order.objects.filter(pk=order.pk).update(retry_count=order.retry_count - 1)
    order.retry_count -= 1
    return False


class BuyNumberView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        country = (request.data.get('country') or '').strip().lower()
        operator = request.data.get('operator') or 'any'
        product = (request.data.get('product') or '').strip().lower()
        service_type = request.data.get('service_type', 'VIRTUAL_NUMBER')

        valid_service_types = {c[0] for c in Order.SERVICE_TYPES}
        if service_type not in valid_service_types:
            service_type = 'VIRTUAL_NUMBER'

        if not country or not product:
            return Response(
                {'error': 'country and product are required'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            client_price = Decimal(str(request.data.get('price')))
        except Exception:
            return Response({'error': 'Invalid price'}, status=status.HTTP_400_BAD_REQUEST)

        # Never trust the client-sent price — recompute from live provider cost.
        # The client price is only used to detect a stale page.
        price = compute_server_price(country, operator, product, service_type)
        if price is None or price <= 0:
            return Response(
                {'error': 'This service is currently unavailable for the selected country. Please try another.'},
                status=status.HTTP_400_BAD_REQUEST
            )
        if client_price < price * Decimal('0.90'):
            return Response(
                {'error': 'Price has changed — please refresh the page and try again.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        User = get_user_model()

        # 1. Reserve the funds in a short, self-contained transaction — no slow
        #    provider HTTP is held inside it, so DB connections aren't tied up.
        deducted = User.objects.filter(
            pk=request.user.pk, wallet_balance__gte=price
        ).update(wallet_balance=F('wallet_balance') - price)
        if not deducted:
            return Response(
                {'error': 'Insufficient wallet balance'},
                status=status.HTTP_400_BAD_REQUEST
            )

        def _refund_reserved():
            User.objects.filter(pk=request.user.pk).update(
                wallet_balance=F('wallet_balance') + price
            )

        # 2. Acquire a number from a provider — OUTSIDE any DB transaction.
        try:
            provider = None
            order_data = {'error': 'No provider available'}
            for candidate in rank_providers(product, country):
                if not within_price_range(candidate, price, country, operator, product, service_type):
                    logger.warning(
                        "[SimPhantom] %s skipped for %s/%s — price outside the charged range",
                        candidate, country, product,
                    )
                    continue
                order_data = purchase_from(candidate, country, operator, product)
                if 'error' not in order_data:
                    provider = candidate
                    break
                logger.warning(
                    "[SimPhantom] %s failed (%s) for %s/%s — trying next provider",
                    candidate, order_data['error'], country, product,
                )
        except Exception as e:
            _refund_reserved()
            logger.exception('[BuyNumber] provider error')
            return Response({'error': str(e)}, status=status.HTTP_502_BAD_GATEWAY)

        if provider is None:
            _refund_reserved()
            return Response({'error': order_data['error']}, status=status.HTTP_400_BAD_REQUEST)

        # Best-effort low-balance alert (never blocks the sale)
        try:
            if provider == 'grizzly':
                bal = grizzlysms.get_balance()
                if 'balance' in bal and bal['balance'] < 5:
                    logger.warning("[SimPhantom] Grizzly balance LOW: $%.2f — top up now!", bal['balance'])
            else:
                from services.fivesim import get_balance
                balance_usd = float(get_balance().get('balance', 999))
                if balance_usd < 5:
                    logger.warning("[SimPhantom] 5sim balance LOW: $%.2f — top up now!", balance_usd)
        except Exception:
            pass

        # 3. Persist the order + debit in a short transaction. If this fails we
        #    already hold a provider number, so release it and refund.
        try:
            with db_transaction.atomic():
                order = Order.objects.create(
                    user=request.user,
                    service_type=service_type,
                    fivesim_order_id=str(order_data['id']),
                    phone=order_data['phone'],
                    product=product,
                    country=country,
                    operator=operator,
                    status=order_data.get('status', 'PENDING'),
                    amount_charged=price,
                    credentials=json.dumps({'provider': provider}),
                    expires_at=timezone.now() + timedelta(minutes=EXPIRY_MINUTES),
                )
                Transaction.objects.create(
                    user=request.user,
                    amount=price,
                    type='DEBIT',
                    reference=f"ORDER-{order.id}",
                    description=f"Purchased {product} number",
                )
        except Exception as e:
            cancel_at_provider(provider, str(order_data['id']))
            _refund_reserved()
            logger.exception('[BuyNumber] failed to persist order')
            return Response({'error': 'Could not complete purchase'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        try:
            from main.notifications import send_purchase_email
            send_purchase_email(
                request.user,
                'Virtual Number',
                [('Phone number', order.phone), ('Product', product), ('Country', country)],
                order.id,
                price,
            )
        except Exception:
            logger.exception('[BuyNumber] purchase email failed')

        record_attempt(provider, product, country)
        return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)


class CheckOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, user=request.user)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

        if order.status in ('RECEIVED', 'FINISHED', 'CANCELED', 'EXPIRED'):
            return Response({
                'status': order.status,
                'sms_code': order.sms_code,
                'phone': order.phone,
            })

        creds = json.loads(order.credentials or '{}')
        provider = creds.get('provider', '5sim')

        # Auto-expire after EXPIRY_MINUTES with no SMS — works for all providers
        if order.expires_at and timezone.now() >= order.expires_at:
            # One last provider check: if the SMS arrived late, deliver it
            # instead of cancelling a number the provider already charged us for.
            late_code = provider_sms(provider, order.fivesim_order_id)
            if late_code:
                deliver_sms(order, late_code)
                return Response({
                    'status': 'RECEIVED',
                    'sms_code': late_code,
                    'phone': order.phone,
                })

            cancel_at_provider(provider, order.fivesim_order_id)

            refunded = refund_order(
                request.user, order, 'EXPIRED',
                f"Auto-refund: {order.product} number expired with no SMS",
            )
            request.user.refresh_from_db()
            return Response({
                'status': 'EXPIRED',
                'sms_code': None,
                'phone': order.phone,
                'refunded': refunded,
                'amount_refunded': str(order.amount_charged),
                'new_balance': str(request.user.wallet_balance),
                'product': order.product,
                'country': order.country,
                'operator': order.operator or 'any',
            })

        # Query the provider for the SMS
        if provider in ('grizzly', 'tigersms'):
            mod = grizzlysms if provider == 'grizzly' else tigersms
            data = mod.get_status(order.fivesim_order_id)
            if 'error' in data:
                return Response({'error': data['error']}, status=status.HTTP_502_BAD_GATEWAY)
            if data['status'] == 'RECEIVED' and data.get('code'):
                deliver_sms(order, data['code'])
            elif data['status'] == 'CANCELED':
                refunded = refund_order(
                    request.user, order, 'CANCELED',
                    f"Refund: {order.product} number cancelled",
                )
                request.user.refresh_from_db()
                return Response({
                    'status': 'CANCELED',
                    'sms_code': order.sms_code,
                    'phone': order.phone,
                    'refunded': refunded,
                    'amount_refunded': str(order.amount_charged),
                    'new_balance': str(request.user.wallet_balance),
                })
        else:
            # 5sim path
            data = check_order(order.fivesim_order_id)
            if 'error' in data:
                return Response({'error': data['error']}, status=status.HTTP_502_BAD_GATEWAY)

            fivesim_status = data.get('status', '')
            if data.get('sms') and len(data['sms']) > 0:
                deliver_sms(order, data['sms'][0]['code'])
            elif fivesim_status in ('CANCELED', 'EXPIRED', 'TIMEOUT', 'BANNED'):
                refunded = refund_order(
                    request.user, order, 'CANCELED',
                    f"Refund: {order.product} number cancelled",
                )
                request.user.refresh_from_db()
                return Response({
                    'status': 'CANCELED',
                    'sms_code': None,
                    'phone': order.phone,
                    'refunded': refunded,
                    'amount_refunded': str(order.amount_charged),
                    'new_balance': str(request.user.wallet_balance),
                })

        if order.status == 'RECEIVED':
            return Response({
                'status': 'RECEIVED',
                'sms_code': order.sms_code,
                'phone': order.phone,
            })

        # Still pending — after RETRY_AFTER_MINUTES with no SMS, silently swap
        # the (probably burnt) number for a fresh one instead of making the
        # user cancel and rebuy themselves.
        retry_due_at = order.expires_at - timedelta(
            minutes=EXPIRY_MINUTES - RETRY_AFTER_MINUTES
        ) if order.expires_at else None
        if (
            order.retry_count < MAX_RETRIES
            and retry_due_at and timezone.now() >= retry_due_at
        ):
            swapped = retry_with_fresh_number(order, provider)
            if swapped:
                return Response({
                    'status': 'PENDING',
                    'sms_code': None,
                    'phone': order.phone,
                    'number_changed': True,
                    'expires_at': order.expires_at.isoformat(),
                    'message': 'No SMS on that number — swapped in a fresh one. Use the new number.',
                })

        return Response({
            'status': 'PENDING',
            'sms_code': order.sms_code,
            'phone': order.phone,
        })

class CancelOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, user=request.user)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

        # RECEIVED orders already delivered a code — refunding them would be free SMS
        if order.status != 'PENDING':
            return Response(
                {'error': 'Can only cancel pending orders'},
                status=status.HTTP_400_BAD_REQUEST
            )

        creds = json.loads(order.credentials or '{}')
        provider = creds.get('provider', '5sim')

        if provider == 'grizzly':
            result = grizzlysms.cancel_number(order.fivesim_order_id)
        elif provider == 'tigersms':
            result = tigersms.cancel_number(order.fivesim_order_id)
        else:
            result = cancel_order(order.fivesim_order_id)

        if isinstance(result, dict) and 'error' in result:
            # Provider rejected cancel — check if an SMS already arrived on their side
            sms_code = None
            if provider == 'grizzly':
                chk = grizzlysms.get_status(order.fivesim_order_id)
                if chk.get('status') == 'RECEIVED' and chk.get('code'):
                    sms_code = chk['code']
                elif chk.get('status') in ('CANCELED', 'NO_ACTIVATION'):
                    # Already gone on provider side — treat as cancelled locally
                    result = {'success': True}
            elif provider == 'tigersms':
                chk = tigersms.get_status(order.fivesim_order_id)
                if chk.get('status') == 'RECEIVED' and chk.get('code'):
                    sms_code = chk['code']
                elif chk.get('status') == 'CANCELED':
                    result = {'success': True}
            else:
                chk = check_order(order.fivesim_order_id)
                if not chk.get('error'):
                    if chk.get('sms') and len(chk['sms']) > 0:
                        sms_code = chk['sms'][0]['code']
                    elif chk.get('status') in ('CANCELED', 'EXPIRED', 'TIMEOUT'):
                        result = {'success': True}

            if sms_code:
                deliver_sms(order, sms_code)
                return Response({
                    'status': 'RECEIVED',
                    'sms_code': sms_code,
                    'phone': order.phone,
                    'message': 'Number already has an SMS — showing code instead of cancelling',
                })

        if isinstance(result, dict) and 'error' in result:
            # Grizzly/Tiger refuse cancels in the first 2 minutes of a purchase
            if result['error'] == 'EARLY_CANCEL_DENIED':
                bought_at = (order.expires_at - timedelta(minutes=EXPIRY_MINUTES)
                             if order.expires_at else order.created_at)
                wait_s = max(0, int((bought_at + timedelta(minutes=2) - timezone.now()).total_seconds()))
                return Response({
                    'error': (
                        f'This number can be cancelled 2 minutes after purchase — try again in ~{wait_s}s. '
                        'If no code arrives, it will be swapped and refunded automatically anyway.'
                    ),
                }, status=status.HTTP_400_BAD_REQUEST)
            logger.warning(
                '[CancelOrder] provider=%s order=%s error=%s',
                provider, order.fivesim_order_id, result['error'],
            )
            return Response({'error': result['error']}, status=status.HTTP_400_BAD_REQUEST)

        refund_order(
            request.user, order, 'CANCELED',
            f"Refund: cancelled {order.product} number",
        )
        request.user.refresh_from_db()
        return Response({
            'message': 'Order canceled and wallet refunded',
            'new_balance': str(request.user.wallet_balance),
        })


class OrderHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        orders = Order.objects.filter(user=request.user).order_by('-created_at')
        serializer = OrderSerializer(orders, many=True)
        return Response(serializer.data)

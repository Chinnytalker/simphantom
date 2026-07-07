"""
Reloadly-backed service endpoints: Airtime/Data top-ups, Gift Cards, and
Utility Bill Payments. Every purchase follows the same money-safe pattern used
across the app: reserve the wallet balance in a short transaction, call Reloadly
OUTSIDE any DB transaction, then refund on failure and persist on success.
"""
import json
import logging
import uuid
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db import transaction as db_transaction
from django.db.models import F
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated

from orders.models import Order, Transaction
from . import reloadly
from .config import (
    airtime_naira_price, giftcard_naira_price, utility_naira_price, get_usd_to_ngn,
    AIRTIME_MARKUP_PCT,
)

logger = logging.getLogger('services')
User = get_user_model()


def reserve_wallet(user, price_ngn):
    """Deduct price atomically. Returns True if funds were reserved."""
    return bool(
        User.objects.filter(pk=user.pk, wallet_balance__gte=price_ngn)
        .update(wallet_balance=F('wallet_balance') - price_ngn)
    )


def refund_wallet(user, price_ngn):
    User.objects.filter(pk=user.pk).update(wallet_balance=F('wallet_balance') + price_ngn)


def insufficient(user, price_ngn):
    user.refresh_from_db(fields=['wallet_balance'])
    return Response(
        {'error': f'Insufficient balance. Need ₦{price_ngn:,.0f}, have ₦{user.wallet_balance:,.0f}.'},
        status=400,
    )


# ══════════════════════════════════════════════════════════════════════════════
#  AIRTIME / DATA
# ══════════════════════════════════════════════════════════════════════════════

def _airtime_local_price(op, local_amount):
    """
    Naira the customer pays.
    Home country (Nigeria): the EXACT local face value — ₦100 airtime = ₦100,
    with the business absorbing any provider FX difference.
    Abroad (UK, USA, …): our real USD cost (via Reloadly FX) plus the markup.
    """
    from .config import AIRTIME_HOME_COUNTRIES
    country = str(op.get('country') or '').upper()
    currency = str(op.get('currency') or '').upper()

    if country in AIRTIME_HOME_COUNTRIES and currency == 'NGN':
        return float(round(float(local_amount)))

    fx = op.get('fx_rate')
    try:
        if fx and float(fx) > 0:
            return airtime_naira_price(float(local_amount) / float(fx))
    except (TypeError, ValueError, ZeroDivisionError):
        pass
    return float(round(float(local_amount) * (1 + AIRTIME_MARKUP_PCT)))


def _describe(op, amount):
    """Bundle description for a local amount, if the operator provides one."""
    descs = op.get('local_fixed_descriptions') or {}
    for k, v in descs.items():
        try:
            if abs(float(k) - float(amount)) < 0.01:
                return v
        except (TypeError, ValueError):
            continue
    return None


def _airtime_denominations(op):
    """Priced denominations in the recipient's LOCAL currency (naira for NG)."""
    cur = op.get('currency') or ''
    out = []
    if op['denomination_type'] == 'FIXED' and op.get('local_fixed_amounts'):
        for amt in op['local_fixed_amounts']:
            out.append({
                'local_amount': amt,
                'currency': cur,
                'description': _describe(op, amt),
                'naira_price': _airtime_local_price(op, amt),
            })
    else:
        lo = float(op.get('local_min_amount') or 0)
        hi = float(op.get('local_max_amount') or 0)
        for amt in (100, 200, 500, 1000, 2000, 5000):
            if lo <= amt <= hi:
                out.append({'local_amount': amt, 'currency': cur, 'description': None,
                            'naira_price': _airtime_local_price(op, amt)})
        if not out and hi:
            amt = round(lo) if lo else round(hi)
            out.append({'local_amount': amt, 'currency': cur, 'description': None,
                        'naira_price': _airtime_local_price(op, amt)})
    return out


def _operator_payload(op):
    return {
        'operator_id': op['operator_id'],
        'operator': op['name'],
        'country': op['country'],
        'is_data': op['is_data'],
        'denomination_type': op['denomination_type'],
        'is_range': op['denomination_type'] == 'RANGE',
        'currency': op.get('currency') or '',
        'min_local': op.get('local_min_amount'),
        'max_local': op.get('local_max_amount'),
        'logo': op['logo'],
        'denominations': _airtime_denominations(op),
    }


class AirtimeDetectView(APIView):
    """
    Auto-detect the operator for a phone + country. If detection fails, fall
    back to the full operator list so the user can pick their network manually.
    Public (read-only) — like the gift-card and utility listings; only the
    actual purchase requires login.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        phone = (request.query_params.get('phone') or '').strip()
        country = (request.query_params.get('country') or '').strip()
        if not phone or not country:
            return Response({'error': 'phone and country are required'}, status=400)

        op = reloadly.detect_operator(phone, country)
        all_ops = reloadly.operators_for_country(country)
        if isinstance(all_ops, dict) and 'error' in all_ops and 'error' in op:
            return Response({'error': 'Could not load networks for that country. Please try again.'},
                            status=502)
        all_ops = all_ops if isinstance(all_ops, list) else []

        if 'error' not in op and op.get('operator_id'):
            # Offer this network's data/bundle operators alongside airtime.
            base = (op['name'].split() or [''])[0].lower()
            related = [
                _operator_payload(o) for o in all_ops
                if o.get('operator_id') and o['operator_id'] != op['operator_id']
                and o['name'].lower().startswith(base)
            ]
            return Response({'detected': True, 'airtime': _operator_payload(op), 'related': related})

        # Auto-detect failed — offer manual network selection instead of a dead end.
        payload = [_operator_payload(o) for o in all_ops if o.get('operator_id')]
        if not payload:
            return Response({'error': 'No networks available for that country.'}, status=404)
        return Response({'detected': False, 'operators': payload})


class ReloadlyCountriesView(APIView):
    """All countries a Reloadly product supports (for the country dropdowns)."""
    permission_classes = [AllowAny]
    product = 'airtime'

    def get(self, request):
        data = reloadly.countries(self.product)
        if isinstance(data, dict) and 'error' in data:
            return Response({'error': 'Could not load countries.'}, status=502)
        return Response(data)


class AirtimeCountriesView(ReloadlyCountriesView):
    product = 'airtime'


class GiftCardCountriesView(ReloadlyCountriesView):
    product = 'giftcards'


class UtilityCountriesView(ReloadlyCountriesView):
    product = 'utilities'


class AirtimeOperatorsView(APIView):
    """List all operators for a country (for the manual network picker)."""
    permission_classes = [AllowAny]

    def get(self, request):
        country = (request.query_params.get('country') or '').strip()
        if not country:
            return Response({'error': 'country is required'}, status=400)
        operators = reloadly.operators_for_country(country)
        if isinstance(operators, dict) and 'error' in operators:
            return Response({'error': 'Could not load networks.'}, status=502)
        return Response([_operator_payload(o) for o in operators if o.get('operator_id')])


class AirtimePurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        phone = (request.data.get('phone') or '').strip()
        country = (request.data.get('country') or '').strip()
        operator_id = request.data.get('operator_id')
        try:
            local_amount = float(request.data.get('local_amount'))
        except (TypeError, ValueError):
            return Response({'error': 'Invalid amount'}, status=400)

        if not (phone and country and operator_id) or local_amount <= 0:
            return Response({'error': 'phone, country, operator_id and amount are required'}, status=400)

        # Fetch the operator server-side to price authoritatively and validate range.
        op = reloadly.get_operator(operator_id)
        if isinstance(op, dict) and 'error' in op:
            return Response({'error': 'Could not verify that network. Please try again.'}, status=502)

        lo = float(op.get('local_min_amount') or 0)
        hi = float(op.get('local_max_amount') or 0)
        if op['denomination_type'] == 'RANGE' and hi and not (lo <= local_amount <= hi):
            return Response({'error': f'Amount must be between {lo:g} and {hi:g} {op.get("currency", "")}.'},
                            status=400)
        if op['denomination_type'] == 'FIXED':
            valid = any(abs(float(a) - local_amount) < 0.01 for a in (op.get('local_fixed_amounts') or []))
            if not valid:
                return Response({'error': 'Please choose one of the listed bundles.'}, status=400)

        price = Decimal(str(_airtime_local_price(op, local_amount)))
        currency = op.get('currency') or ''
        user = request.user
        if not reserve_wallet(user, price):
            return insufficient(user, price)

        result = reloadly.topup(operator_id, local_amount, country, phone, use_local_amount=True)
        if 'error' in result:
            refund_wallet(user, price)
            return Response({'error': 'Top-up failed. Your wallet was not charged.'}, status=502)

        desc = _describe(op, local_amount) or f'{local_amount:g} {currency}'
        ref = 'AIRTIME-' + uuid.uuid4().hex[:12].upper()
        with db_transaction.atomic():
            Transaction.objects.create(
                user=user, amount=price, type='DEBIT', reference=ref,
                description=f'{"Data" if op["is_data"] else "Airtime"} {desc} to {phone}',
            )
            order = Order.objects.create(
                user=user, service_type='AIRTIME',
                product=f'{op["name"]} — {desc}',
                phone=phone, country=country, status='FINISHED', amount_charged=price,
                credentials=json.dumps({
                    'transaction_id': result.get('transactionId'),
                    'operator': result.get('operatorName', op['name']),
                    'local_amount': local_amount, 'currency': currency,
                    'description': desc, 'is_data': op['is_data'],
                }),
            )

        _purchase_email(user, 'Airtime / Data', [
            ('Number', phone), ('Bought', desc), ('Network', result.get('operatorName', op['name'])),
        ], order.id, price)

        return Response({'id': order.id, 'status': 'FINISHED', 'phone': phone,
                         'bought': desc}, status=201)


class AirtimeOrdersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = []
        for o in Order.objects.filter(user=request.user, service_type='AIRTIME').order_by('-created_at')[:30]:
            c = json.loads(o.credentials or '{}')
            rows.append({'id': o.id, 'phone': o.phone,
                         'bought': c.get('description', ''), 'is_data': c.get('is_data', False),
                         'operator': c.get('operator', ''), 'status': o.status,
                         'amount_charged': str(o.amount_charged), 'created_at': o.created_at.isoformat()})
        return Response(rows)


# ══════════════════════════════════════════════════════════════════════════════
#  GIFT CARDS
# ══════════════════════════════════════════════════════════════════════════════

def _giftcard_usd_cost(product, recipient_denom):
    """
    USD (sender-currency) cost to us for a given recipient denomination.
    FIXED cards: read the exact sender cost from Reloadly's map.
    RANGE cards: scale by the sender/recipient ratio and apply any discount.
    """
    # FIXED — exact mapping recipient value -> sender USD cost
    m = product.get('fixedRecipientToSenderDenominationsMap') or {}
    for k, v in m.items():
        try:
            if abs(float(k) - float(recipient_denom)) < 0.001:
                return float(v)
        except (TypeError, ValueError):
            continue

    # RANGE — derive the sender-per-recipient ratio from the max denominations
    try:
        max_recip = float(product.get('maxRecipientDenomination') or 0)
        max_send = float(product.get('maxSenderDenomination') or 0)
        ratio = (max_send / max_recip) if (max_recip and max_send) else 1.0
    except (TypeError, ValueError, ZeroDivisionError):
        ratio = 1.0
    try:
        discount = float(product.get('discountPercentage') or 0) / 100.0
    except (TypeError, ValueError):
        discount = 0.0
    return float(recipient_denom) * ratio * (1 - discount)


def _giftcard_denominations(product):
    """Priced denominations a user can pick, for both FIXED and RANGE cards."""
    dtype = product.get('denominationType')
    currency = product.get('recipientCurrencyCode', '')
    if dtype == 'FIXED':
        values = [float(d) for d in (product.get('fixedRecipientDenominations') or [])]
    else:
        lo = float(product.get('minRecipientDenomination') or 1)
        hi = float(product.get('maxRecipientDenomination') or lo)
        values = [v for v in (5, 10, 25, 50, 100) if lo <= v <= hi]
        if not values:
            values = sorted({round(lo, 2), round(hi, 2)})
    return [{
        'recipient_denom': v,
        'recipient_currency': currency,
        'naira_price': giftcard_naira_price(_giftcard_usd_cost(product, v)),
    } for v in values]


class GiftCardProductsView(APIView):
    """List gift card products for a country, each with priced denominations (NGN)."""
    permission_classes = [AllowAny]

    def get(self, request):
        country = (request.query_params.get('country') or 'US').strip().upper()
        products = reloadly.gift_card_products(country)
        if isinstance(products, dict) and 'error' in products:
            return Response({'error': 'Could not load gift cards right now.'}, status=502)

        out = []
        for p in products:
            out.append({
                'product_id': p.get('productId'),
                'name': p.get('productName', ''),
                'brand': (p.get('brand') or {}).get('brandName', ''),
                'country': (p.get('country') or {}).get('isoName', country),
                'logo': (p.get('logoUrls') or [None])[0],
                'denomination_type': p.get('denominationType'),
                'recipient_currency': p.get('recipientCurrencyCode', ''),
                'min_recipient': p.get('minRecipientDenomination'),
                'max_recipient': p.get('maxRecipientDenomination'),
                'denominations': _giftcard_denominations(p),
            })
        out.sort(key=lambda x: x['name'])
        return Response(out)


class GiftCardPurchaseView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        product_id = request.data.get('product_id')
        try:
            recipient_denom = float(request.data.get('recipient_denom'))
        except (TypeError, ValueError):
            return Response({'error': 'Invalid denomination'}, status=400)
        recipient_email = (request.data.get('recipient_email') or request.user.email or '').strip()

        if not product_id or recipient_denom <= 0:
            return Response({'error': 'product_id and recipient_denom are required'}, status=400)

        # Re-fetch product server-side to price authoritatively (never trust client)
        product = reloadly.gift_card_product(product_id)
        if isinstance(product, dict) and 'error' in product:
            return Response({'error': 'Could not verify that gift card. Try again.'}, status=502)

        usd_cost = _giftcard_usd_cost(product, recipient_denom)
        price = Decimal(str(giftcard_naira_price(usd_cost)))
        user = request.user
        if not reserve_wallet(user, price):
            return insufficient(user, price)

        order_resp = reloadly.gift_card_order(
            product_id, recipient_denom, quantity=1,
            recipient_email=recipient_email, country_iso2=(product.get('country') or {}).get('isoName'),
            custom_identifier='GC-' + uuid.uuid4().hex[:10],
        )
        if isinstance(order_resp, dict) and 'error' in order_resp:
            refund_wallet(user, price)
            return Response({'error': 'Gift card purchase failed. Your wallet was not charged.'}, status=502)

        transaction_id = order_resp.get('transactionId')

        # Retrieve the redeem code(s). May be delayed — store PENDING if not ready.
        cards = reloadly.gift_card_redeem_code(transaction_id) if transaction_id else {'error': 'no txn'}
        code_ready = isinstance(cards, list) and len(cards) > 0
        status_val = 'FINISHED' if code_ready else 'PENDING'

        ref = 'GIFTCARD-' + uuid.uuid4().hex[:12].upper()
        with db_transaction.atomic():
            Transaction.objects.create(
                user=user, amount=price, type='DEBIT', reference=ref,
                description=f"Gift card — {product.get('productName', '')} {recipient_denom}",
            )
            order = Order.objects.create(
                user=user, service_type='GIFT_CARD',
                product=product.get('productName', 'Gift Card'),
                status=status_val, amount_charged=price,
                credentials=json.dumps({
                    'transaction_id': transaction_id,
                    'recipient_denom': recipient_denom,
                    'recipient_currency': product.get('recipientCurrencyCode', ''),
                    'cards': cards if code_ready else [],
                }),
            )

        _purchase_email(user, 'Gift Card', [
            ('Card', product.get('productName', '')),
            ('Value', f"{recipient_denom} {product.get('recipientCurrencyCode', '')}"),
            ('Status', 'Delivered' if code_ready else 'Processing'),
        ], order.id, price)

        return Response({'id': order.id, 'status': status_val,
                         'cards': cards if code_ready else [],
                         'name': product.get('productName', '')}, status=201)


class GiftCardOrdersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = []
        for o in Order.objects.filter(user=request.user, service_type='GIFT_CARD').order_by('-created_at')[:30]:
            c = json.loads(o.credentials or '{}')
            rows.append({'id': o.id, 'name': o.product, 'status': o.status,
                         'value': f"{c.get('recipient_denom', '')} {c.get('recipient_currency', '')}",
                         'cards': c.get('cards', []),
                         'amount_charged': str(o.amount_charged), 'created_at': o.created_at.isoformat()})
        return Response(rows)


class GiftCardRefreshView(APIView):
    """Re-pull the redeem code for a gift card that was still processing."""
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, user=request.user, service_type='GIFT_CARD')
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=404)

        creds = json.loads(order.credentials or '{}')
        if creds.get('cards'):
            return Response({'ready': True, 'cards': creds['cards']})

        cards = reloadly.gift_card_redeem_code(creds.get('transaction_id'))
        if isinstance(cards, list) and cards:
            creds['cards'] = cards
            order.credentials = json.dumps(creds)
            order.status = 'FINISHED'
            order.save(update_fields=['credentials', 'status'])
            return Response({'ready': True, 'cards': cards})
        return Response({'ready': False, 'message': 'Still processing — check back shortly.'})


# ══════════════════════════════════════════════════════════════════════════════
#  UTILITY BILLS
# ══════════════════════════════════════════════════════════════════════════════

class UtilityBillersView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        country = (request.query_params.get('country') or 'NG').strip().upper()
        biller_type = request.query_params.get('type')
        data = reloadly.billers(country, biller_type)
        if isinstance(data, dict) and 'error' in data:
            return Response({'error': 'Could not load billers right now.'}, status=502)

        out = [{
            'id': b.get('id'),
            'name': b.get('name', ''),
            'type': b.get('type', ''),
            'service_type': b.get('serviceType', ''),
            'country': b.get('countryCode', country),
            'currency': b.get('localTransactionCurrencyCode', ''),
            'min_local': b.get('minLocalTransactionAmount'),
            'max_local': b.get('maxLocalTransactionAmount'),
        } for b in data]
        out.sort(key=lambda x: (x['type'], x['name']))
        return Response(out)


class UtilityPayView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        biller_id = request.data.get('biller_id')
        subscriber = (request.data.get('subscriber_account') or '').strip()
        try:
            amount_local = float(request.data.get('amount_local'))
        except (TypeError, ValueError):
            return Response({'error': 'Invalid amount'}, status=400)

        if not (biller_id and subscriber) or amount_local <= 0:
            return Response({'error': 'biller_id, subscriber_account and amount_local are required'}, status=400)

        # Reloadly bills in local currency; we approximate the USD cost for pricing.
        # For NGN billers the local amount IS naira, so charge that + markup directly.
        currency = (request.data.get('currency') or 'NGN').upper()
        if currency == 'NGN':
            price = Decimal(str(round(amount_local * 1.07, 0)))  # 7% service fee
        else:
            usd = amount_local / get_usd_to_ngn() if currency == 'NGN' else amount_local
            price = Decimal(str(utility_naira_price(usd)))

        user = request.user
        if not reserve_wallet(user, price):
            return insufficient(user, price)

        result = reloadly.pay_bill(biller_id, amount_local, subscriber, use_local_amount=True,
                                   reference='UTIL-' + uuid.uuid4().hex[:10])
        if isinstance(result, dict) and 'error' in result:
            refund_wallet(user, price)
            return Response({'error': 'Bill payment failed. Your wallet was not charged.'}, status=502)

        ref = 'UTILITY-' + uuid.uuid4().hex[:12].upper()
        with db_transaction.atomic():
            Transaction.objects.create(
                user=user, amount=price, type='DEBIT', reference=ref,
                description=f'Utility bill {subscriber} ({amount_local} {currency})',
            )
            order = Order.objects.create(
                user=user, service_type='UTILITY',
                product=f'Bill {subscriber}', status='FINISHED', amount_charged=price,
                credentials=json.dumps({
                    'transaction_id': result.get('id') or result.get('transactionId'),
                    'subscriber': subscriber, 'amount_local': amount_local, 'currency': currency,
                }),
            )

        _purchase_email(user, 'Utility Bill', [
            ('Account', subscriber), ('Amount', f'{amount_local} {currency}'),
        ], order.id, price)

        return Response({'id': order.id, 'status': 'FINISHED'}, status=201)


class UtilityOrdersView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        rows = []
        for o in Order.objects.filter(user=request.user, service_type='UTILITY').order_by('-created_at')[:30]:
            c = json.loads(o.credentials or '{}')
            rows.append({'id': o.id, 'subscriber': c.get('subscriber', ''),
                         'amount_local': c.get('amount_local'), 'currency': c.get('currency', ''),
                         'status': o.status, 'amount_charged': str(o.amount_charged),
                         'created_at': o.created_at.isoformat()})
        return Response(rows)


# ── shared ────────────────────────────────────────────────────────────────────

def _purchase_email(user, service_name, rows, order_id, price):
    try:
        from main.notifications import send_purchase_email
        send_purchase_email(user, service_name, rows, order_id, price)
    except Exception:
        logger.exception('purchase email failed')

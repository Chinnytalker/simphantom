import hmac
import hashlib
import json
import uuid
import logging
from django.conf import settings

logger = logging.getLogger('payments')
from django.db import transaction as db_transaction
from django.db.models import F
from django.contrib.auth import get_user_model
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_ratelimit.decorators import ratelimit
from decimal import Decimal
from orders.models import Transaction
from .serializers import InitializePaymentSerializer

# Smallest wallet top-up we accept, in NGN (after any USD conversion).
MIN_TOPUP_NGN = Decimal('100')


def credit_wallet_once(reference, user_id, amount):
    """
    Credit a pending top-up to the wallet exactly once.

    Uses a conditional UPDATE on status so that the webhook, the JS verify
    call and the redirect callback can all fire for the same payment without
    ever double-crediting — only the first to flip PENDING->COMPLETED wins.
    Returns True if this call performed the credit.
    """
    with db_transaction.atomic():
        flipped = Transaction.objects.filter(
            reference=reference, type='CREDIT', status='PENDING'
        ).update(status='COMPLETED', description='Wallet top-up (confirmed)')
        if flipped:
            get_user_model().objects.filter(pk=user_id).update(
                wallet_balance=F('wallet_balance') + amount
            )
    if flipped:
        # Reward the referrer (if any) for this user's first funded deposit.
        try:
            from accounts.referrals import award_referral
            award_referral(user_id, amount)
        except Exception:
            logger.exception('Referral award failed for user=%s', user_id)
    return bool(flipped)


@method_decorator(ratelimit(key='user', rate='20/h', method='POST', block=False), name='post')
class InitializePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if getattr(request, 'limited', False):
            return Response(
                {'error': 'Too many top-up attempts. Please wait a while and try again.'},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        serializer = InitializePaymentSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        amount   = serializer.validated_data['amount']
        currency = serializer.validated_data.get('currency', 'NGN')

        # Convert USD → NGN for Paystack (Paystack charges in NGN)
        if currency == 'USD':
            from services.config import get_usd_to_ngn
            rate = get_usd_to_ngn()
            ngn_amount = (amount * Decimal(str(rate))).quantize(Decimal('0.01'))
            desc = f'Wallet top-up (pending) [${amount} USD @ ₦{rate}]'
        else:
            ngn_amount = amount
            desc = 'Wallet top-up (pending)'

        if ngn_amount < MIN_TOPUP_NGN:
            return Response(
                {'error': f'Minimum top-up is ₦{MIN_TOPUP_NGN:,.0f}.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        reference = str(uuid.uuid4())

        Transaction.objects.create(
            user=request.user,
            amount=ngn_amount,
            type='CREDIT',
            status='PENDING',
            reference=reference,
            description=desc,
        )

        return Response({
            'reference':          reference,
            'amount':             int(ngn_amount * 100),   # kobo
            'email':              request.user.email,
            'paystack_public_key': settings.PAYSTACK_PUBLIC_KEY,
            'original_amount':    str(amount),
            'original_currency':  currency,
        }, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name='dispatch')
class PaystackWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        paystack_secret = settings.PAYSTACK_SECRET
        signature = request.headers.get('X-Paystack-Signature', '')

        # Verify signature
        computed = hmac.new(
            paystack_secret.encode('utf-8'),
            request.body,
            hashlib.sha512
        ).hexdigest()

        if not hmac.compare_digest(computed, signature):
            return Response({'error': 'Invalid signature'}, status=400)

        try:
            event = json.loads(request.body)
        except (ValueError, TypeError):
            return Response({'error': 'Invalid JSON'}, status=400)

        if event.get('event') == 'charge.success':
            try:
                ref = event['data']['reference']
                amount = Decimal(event['data']['amount']) / 100  # kobo → naira
            except (KeyError, TypeError, ValueError):
                return Response({'error': 'Malformed payload'}, status=400)

            try:
                txn = Transaction.objects.get(reference=ref, type='CREDIT')
            except Transaction.DoesNotExist:
                return Response({'status': 'ok'})

            if credit_wallet_once(ref, txn.user_id, amount):
                user = get_user_model().objects.get(pk=txn.user_id)
                from main.notifications import send_deposit_confirmed_email
                send_deposit_confirmed_email(user, amount, user.wallet_balance)
                logger.info('Wallet credited via webhook user=%s amount=%s ref=%s',
                            txn.user_id, amount, ref)

        return Response({'status': 'ok'})


class VerifyPaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        reference = request.data.get('reference', '').strip()
        if not reference:
            return Response({'error': 'Reference required'}, status=400)

        import requests as http_requests
        try:
            resp = http_requests.get(
                f'https://api.paystack.co/transaction/verify/{reference}',
                headers={'Authorization': f'Bearer {settings.PAYSTACK_SECRET}'},
                timeout=10,
            )
            result = resp.json()
            logger.info('Paystack verify ref=%s http=%s', reference, resp.status_code)
        except Exception as e:
            logger.error('Paystack verify network error ref=%s err=%s', reference, e)
            return Response({'error': 'Could not reach Paystack'}, status=502)

        pay_status = result.get('data', {}).get('status')
        if not result.get('status') or pay_status != 'success':
            logger.warning('Paystack verify not success ref=%s pay_status=%s', reference, pay_status)
            return Response({'error': f'Payment status: {pay_status}'}, status=400)

        amount = Decimal(result['data']['amount']) / 100  # kobo → naira

        try:
            txn = Transaction.objects.get(
                reference=reference, user=request.user, type='CREDIT',
            )
        except Transaction.DoesNotExist:
            logger.error('Transaction not found ref=%s user=%s', reference, request.user.id)
            return Response({'error': 'Transaction not found'}, status=404)

        if not credit_wallet_once(reference, txn.user_id, amount):
            logger.info('Already confirmed ref=%s', reference)
            return Response({'status': 'already_confirmed'})

        logger.info('Wallet credited via verify user=%s amount=%s ref=%s',
                    request.user.id, amount, reference)
        user = get_user_model().objects.get(pk=txn.user_id)
        try:
            from main.notifications import send_deposit_confirmed_email
            send_deposit_confirmed_email(user, amount, user.wallet_balance)
        except Exception as e:
            logger.error('Deposit email failed user=%s err=%s', user.id, e)
        return Response({'status': 'ok', 'amount': str(amount)})


# ══════════════════════════════════════════════════════════════════════════════
#  Crypto deposits (NOWPayments)
# ══════════════════════════════════════════════════════════════════════════════

@method_decorator(ratelimit(key='user', rate='20/h', method='POST', block=False), name='post')
class CryptoDepositView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if getattr(request, 'limited', False):
            return Response({'error': 'Too many attempts. Please wait a while.'},
                            status=status.HTTP_429_TOO_MANY_REQUESTS)

        try:
            usd = Decimal(str(request.data.get('amount_usd')))
        except Exception:
            return Response({'error': 'Invalid amount'}, status=400)

        min_usd = Decimal(str(settings.MIN_CRYPTO_USD))
        if usd < min_usd:
            return Response({'error': f'Minimum crypto deposit is ${min_usd:g}.'}, status=400)
        if usd > Decimal('100000'):
            return Response({'error': 'Amount too large.'}, status=400)

        from services.config import get_usd_to_ngn
        rate = get_usd_to_ngn()
        ngn_amount = (usd * Decimal(str(rate))).quantize(Decimal('0.01'))

        reference = 'CRYPTO-' + uuid.uuid4().hex[:16].upper()
        Transaction.objects.create(
            user=request.user, amount=ngn_amount, type='CREDIT', status='PENDING',
            reference=reference,
            description=f'Wallet top-up (pending) [crypto ${usd} @ ₦{rate}]',
        )

        from . import nowpayments
        callback = request.build_absolute_uri('/api/payments/webhook/nowpayments/')
        result = nowpayments.create_invoice(
            usd, reference, f'SimPhantom wallet top-up (${usd})',
            price_currency='usd', ipn_callback_url=callback,
            success_url=request.build_absolute_uri('/dashboard/?crypto=success'),
            cancel_url=request.build_absolute_uri('/dashboard/?crypto=cancel'),
        )
        if 'error' in result or not result.get('invoice_url'):
            # Nothing was charged; drop the orphan pending row.
            Transaction.objects.filter(reference=reference, status='PENDING').delete()
            return Response({'error': result.get('error', 'Could not start crypto payment.')}, status=502)

        return Response({
            'invoice_url': result['invoice_url'],
            'reference': reference,
            'amount_usd': str(usd),
            'amount_ngn': str(ngn_amount),
        }, status=200)


@method_decorator(csrf_exempt, name='dispatch')
class NowPaymentsWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        from . import nowpayments
        signature = request.headers.get('x-nowpayments-sig', '')
        if not nowpayments.verify_ipn(request.body, signature):
            logger.warning('[NOWPayments] bad IPN signature')
            return Response({'error': 'Invalid signature'}, status=400)

        try:
            event = json.loads(request.body)
        except (ValueError, TypeError):
            return Response({'error': 'Invalid JSON'}, status=400)

        pay_status = (event.get('payment_status') or '').lower()
        reference = event.get('order_id') or ''

        # Credit only once the payment has fully landed.
        if pay_status in ('finished', 'confirmed') and reference:
            try:
                txn = Transaction.objects.get(reference=reference, type='CREDIT')
            except Transaction.DoesNotExist:
                return Response({'status': 'ok'})

            if credit_wallet_once(reference, txn.user_id, txn.amount):
                user = get_user_model().objects.get(pk=txn.user_id)
                logger.info('Wallet credited via crypto user=%s amount=%s ref=%s',
                            txn.user_id, txn.amount, reference)
                try:
                    from main.notifications import send_deposit_confirmed_email
                    send_deposit_confirmed_email(user, txn.amount, user.wallet_balance)
                except Exception:
                    logger.exception('crypto deposit email failed')

        return Response({'status': 'ok'})

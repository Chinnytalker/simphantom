import hmac
import hashlib
import json
import uuid
from django.conf import settings
from django.db import transaction as db_transaction
from django.db.models import F
from django.contrib.auth import get_user_model
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from decimal import Decimal
from orders.models import Transaction
from .serializers import InitializePaymentSerializer


class InitializePaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = InitializePaymentSerializer(data=request.data)
        if serializer.is_valid():
            amount   = serializer.validated_data['amount']
            currency = serializer.validated_data.get('currency', 'NGN')

            # Convert USD → NGN for Paystack (Paystack charges in NGN)
            if currency == 'USD':
                from services.config import USD_TO_NGN
                ngn_amount = amount * Decimal(str(USD_TO_NGN))
                desc = f'Wallet top-up (pending) [${amount} USD @ ₦{USD_TO_NGN}]'
            else:
                ngn_amount = amount
                desc = 'Wallet top-up (pending)'

            reference = str(uuid.uuid4())

            Transaction.objects.create(
                user=request.user,
                amount=ngn_amount,
                type='CREDIT',
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
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


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

        if computed != signature:
            return Response({'error': 'Invalid signature'}, status=400)

        try:
            event = json.loads(request.body)
        except:
            return Response({'error': 'Invalid JSON'}, status=400)

        if event.get('event') == 'charge.success':
            ref = event['data']['reference']
            amount = Decimal(event['data']['amount']) / 100  # convert from kobo

            try:
                with db_transaction.atomic():
                    txn = Transaction.objects.get(reference=ref, type='CREDIT')
                    if 'pending' in txn.description:
                        get_user_model().objects.filter(pk=txn.user_id).update(
                            wallet_balance=F('wallet_balance') + amount
                        )
                        txn.description = 'Wallet top-up (confirmed)'
                        txn.save()
                # Email after DB commit (outside atomic block)
                user = get_user_model().objects.get(pk=txn.user_id)
                from main.notifications import send_deposit_confirmed_email
                send_deposit_confirmed_email(user, amount, user.wallet_balance)
            except Transaction.DoesNotExist:
                pass

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
        except Exception:
            return Response({'error': 'Could not reach Paystack'}, status=502)

        if not result.get('status') or result['data']['status'] != 'success':
            return Response({'error': 'Payment not confirmed by Paystack'}, status=400)

        amount = Decimal(result['data']['amount']) / 100  # kobo → naira

        try:
            with db_transaction.atomic():
                txn = Transaction.objects.get(
                    reference=reference,
                    user=request.user,
                    type='CREDIT',
                )
                if 'pending' in txn.description:
                    get_user_model().objects.filter(pk=txn.user_id).update(
                        wallet_balance=F('wallet_balance') + amount
                    )
                    txn.description = 'Wallet top-up (confirmed)'
                    txn.save()
                else:
                    return Response({'status': 'already_confirmed'})

            user = get_user_model().objects.get(pk=txn.user_id)
            from main.notifications import send_deposit_confirmed_email
            send_deposit_confirmed_email(user, amount, user.wallet_balance)
            return Response({'status': 'ok', 'amount': str(amount)})

        except Transaction.DoesNotExist:
            return Response({'error': 'Transaction not found'}, status=404)
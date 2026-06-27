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
from services.fivesim import buy_number, check_order, cancel_order
from services import tigersms, grizzly as grizzlysms
from .models import Order, Transaction
from .serializers import OrderSerializer, TransactionSerializer

logger = logging.getLogger(__name__)

MARKUP = Decimal('1.30')
EXPIRY_MINUTES = 5


class BuyNumberView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        country = request.data.get('country')
        operator = request.data.get('operator', 'any')
        product = request.data.get('product')
        service_type = request.data.get('service_type', 'VIRTUAL_NUMBER')

        valid_service_types = {c[0] for c in Order.SERVICE_TYPES}
        if service_type not in valid_service_types:
            service_type = 'VIRTUAL_NUMBER'

        try:
            price = Decimal(str(request.data.get('price')))
        except Exception:
            return Response({'error': 'Invalid price'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            with db_transaction.atomic():
                deducted = get_user_model().objects.filter(
                    pk=request.user.pk, wallet_balance__gte=price
                ).update(wallet_balance=F('wallet_balance') - price)

                if not deducted:
                    return Response(
                        {'error': 'Insufficient wallet balance'},
                        status=status.HTTP_400_BAD_REQUEST
                    )

                # Try Grizzly first; fall back to 5sim if mapping missing or API fails
                grizzly_country_id = grizzlysms.map_country(country)
                grizzly_service_code = grizzlysms.map_service(product)
                provider = '5sim'

                if grizzly_country_id and grizzly_service_code:
                    order_data = grizzlysms.get_number(grizzly_service_code, grizzly_country_id)
                    if 'error' not in order_data:
                        provider = 'grizzly'
                    else:
                        logger.warning(
                            "[SimPhantom] Grizzly failed (%s) for %s/%s — falling back to 5sim",
                            order_data['error'], country, product,
                        )
                        order_data = buy_number(country, operator, product)
                else:
                    order_data = buy_number(country, operator, product)

                if 'error' in order_data:
                    raise ValueError(order_data['error'])

                try:
                    if provider == 'grizzly':
                        bal = grizzlysms.get_balance()
                        if 'balance' in bal and bal['balance'] < 5:
                            logger.warning(
                                "[SimPhantom] Grizzly balance LOW: $%.2f — top up now!", bal['balance']
                            )
                    else:
                        from services.fivesim import get_balance
                        profile = get_balance()
                        balance_usd = float(profile.get('balance', 999))
                        if balance_usd < 5:
                            logger.warning(
                                "[SimPhantom] 5sim balance LOW: $%.2f — top up now!", balance_usd
                            )
                except Exception:
                    pass

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

                from main.notifications import send_purchase_email
                send_purchase_email(
                    request.user,
                    'Virtual Number',
                    [('Phone number', order.phone), ('Product', product), ('Country', country)],
                    order.id,
                    price,
                )

                return Response(OrderSerializer(order).data, status=status.HTTP_201_CREATED)

        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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

        # Auto-expire after EXPIRY_MINUTES with no SMS — works for both 5sim and TigerSMS orders
        if order.expires_at and timezone.now() >= order.expires_at:
            creds = json.loads(order.credentials or '{}')
            provider = creds.get('provider', '5sim')
            try:
                if provider == 'grizzly':
                    grizzlysms.cancel_number(order.fivesim_order_id)
                elif provider == 'tigersms':
                    tigersms.cancel_number(order.fivesim_order_id)
                else:
                    cancel_order(order.fivesim_order_id)
            except Exception:
                pass

            with db_transaction.atomic():
                get_user_model().objects.filter(pk=request.user.pk).update(
                    wallet_balance=F('wallet_balance') + order.amount_charged
                )
                Transaction.objects.get_or_create(
                    reference=f"REFUND-EXPIRE-{order.id}",
                    defaults={
                        'user': request.user,
                        'amount': order.amount_charged,
                        'type': 'CREDIT',
                        'description': f"Auto-refund: {order.product} number expired after {EXPIRY_MINUTES}min",
                    }
                )
                order.status = 'EXPIRED'
                order.save(update_fields=['status'])

            request.user.refresh_from_db()
            return Response({
                'status': 'EXPIRED',
                'sms_code': None,
                'phone': order.phone,
                'refunded': True,
                'amount_refunded': str(order.amount_charged),
                'new_balance': str(request.user.wallet_balance),
                'product': order.product,
                'country': order.country,
                'operator': order.operator or 'any',
            })

        creds = json.loads(order.credentials or '{}')
        provider = creds.get('provider', '5sim')

        # Handle GrizzlySMS orders
        if provider == 'grizzly':
            data = grizzlysms.get_status(order.fivesim_order_id)
            if 'error' in data:
                return Response({'error': data['error']}, status=status.HTTP_502_BAD_GATEWAY)
            if data['status'] == 'RECEIVED' and data.get('code'):
                order.sms_code = data['code']
                order.status = 'RECEIVED'
                order.save(update_fields=['sms_code', 'status'])
            elif data['status'] == 'CANCELED' and order.status != 'CANCELED':
                with db_transaction.atomic():
                    get_user_model().objects.filter(pk=request.user.pk).update(
                        wallet_balance=F('wallet_balance') + order.amount_charged
                    )
                    Transaction.objects.get_or_create(
                        reference=f"REFUND-{order.id}",
                        defaults={
                            'user': request.user,
                            'amount': order.amount_charged,
                            'type': 'CREDIT',
                            'description': f"Refund: {order.product} number cancelled",
                        }
                    )
                    order.status = 'CANCELED'
                    order.save(update_fields=['status'])
                request.user.refresh_from_db()
                return Response({
                    'status': 'CANCELED',
                    'sms_code': order.sms_code,
                    'phone': order.phone,
                    'refunded': True,
                    'amount_refunded': str(order.amount_charged),
                    'new_balance': str(request.user.wallet_balance),
                })
            return Response({
                'status': data['status'],
                'sms_code': order.sms_code,
                'phone': order.phone,
            })

        # Handle legacy TigerSMS orders
        if provider == 'tigersms':
            data = tigersms.get_status(order.fivesim_order_id)
            if 'error' in data:
                return Response({'error': data['error']}, status=status.HTTP_502_BAD_GATEWAY)
            if data['status'] == 'RECEIVED' and data.get('code'):
                order.sms_code = data['code']
                order.status = 'RECEIVED'
                order.save(update_fields=['sms_code', 'status'])
            elif data['status'] == 'CANCELED' and order.status != 'CANCELED':
                with db_transaction.atomic():
                    get_user_model().objects.filter(pk=request.user.pk).update(
                        wallet_balance=F('wallet_balance') + order.amount_charged
                    )
                    Transaction.objects.get_or_create(
                        reference=f"REFUND-{order.id}",
                        defaults={
                            'user': request.user,
                            'amount': order.amount_charged,
                            'type': 'CREDIT',
                            'description': f"Refund: {order.product} number cancelled",
                        }
                    )
                    order.status = 'CANCELED'
                    order.save(update_fields=['status'])
                request.user.refresh_from_db()
                return Response({
                    'status': 'CANCELED',
                    'sms_code': order.sms_code,
                    'phone': order.phone,
                    'refunded': True,
                    'amount_refunded': str(order.amount_charged),
                    'new_balance': str(request.user.wallet_balance),
                })
            return Response({
                'status': data['status'],
                'sms_code': order.sms_code,
                'phone': order.phone,
            })

        # 5sim path
        data = check_order(order.fivesim_order_id)
        if 'error' in data:
            return Response({'error': data['error']}, status=status.HTTP_502_BAD_GATEWAY)

        fivesim_status = data.get('status', '')
        if data.get('sms') and len(data['sms']) > 0:
            order.sms_code = data['sms'][0]['code']
            order.status = 'RECEIVED'
            order.save(update_fields=['sms_code', 'status'])
        elif fivesim_status in ('CANCELED', 'EXPIRED') and order.status not in ('CANCELED', 'EXPIRED'):
            with db_transaction.atomic():
                get_user_model().objects.filter(pk=request.user.pk).update(
                    wallet_balance=F('wallet_balance') + order.amount_charged
                )
                Transaction.objects.get_or_create(
                    reference=f"REFUND-{order.id}",
                    defaults={
                        'user': request.user,
                        'amount': order.amount_charged,
                        'type': 'CREDIT',
                        'description': f"Refund: {order.product} number cancelled",
                    }
                )
                order.status = 'CANCELED'
                order.save(update_fields=['status'])
            request.user.refresh_from_db()
            return Response({
                'status': 'CANCELED',
                'sms_code': None,
                'phone': order.phone,
                'refunded': True,
                'amount_refunded': str(order.amount_charged),
                'new_balance': str(request.user.wallet_balance),
            })

        return Response({
            'status': fivesim_status or order.status,
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

        if order.status not in ['PENDING']:
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
            return Response({'error': result['error']}, status=status.HTTP_400_BAD_REQUEST)

        with db_transaction.atomic():
            get_user_model().objects.filter(pk=request.user.pk).update(
                wallet_balance=F('wallet_balance') + order.amount_charged
            )
            Transaction.objects.get_or_create(
                reference=f"REFUND-CANCEL-{order.id}",
                defaults={
                    'user': request.user,
                    'amount': order.amount_charged,
                    'type': 'CREDIT',
                    'description': f"Refund: cancelled {order.product} number",
                }
            )
            order.status = 'CANCELED'
            order.save(update_fields=['status'])

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

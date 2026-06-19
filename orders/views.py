from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db import transaction as db_transaction
from django.db.models import F
from django.contrib.auth import get_user_model
from decimal import Decimal
from services.fivesim import buy_number, check_order, cancel_order
from .models import Order, Transaction
from .serializers import OrderSerializer, TransactionSerializer

MARKUP = Decimal('1.30')

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

                order_data = buy_number(country, operator, product)

                # Raise so atomic rolls back the wallet deduction
                if 'error' in order_data:
                    raise ValueError(order_data['error'])

                # Warn you (via server log) when 5sim balance is getting low
                try:
                    from services.fivesim import get_balance
                    profile = get_balance()
                    balance_usd = float(profile.get('balance', 999))
                    if balance_usd < 5:
                        import logging
                        logging.getLogger(__name__).warning(
                            f"[SimPhantom] 5sim balance LOW: ${balance_usd:.2f} — top up now!"
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
                    status=order_data['status'],
                    amount_charged=price,
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
            data = check_order(order.fivesim_order_id)

            # Update SMS code if received
            if data.get('sms') and len(data['sms']) > 0:
                order.sms_code = data['sms'][0]['code']
                order.status = 'RECEIVED'
                order.save()

            return Response({
                'status': data.get('status'),
                'sms_code': order.sms_code,
                'phone': order.phone,
            })
        except Order.DoesNotExist:
            return Response(
                {'error': 'Order not found'},
                status=status.HTTP_404_NOT_FOUND
            )


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

        # External call before any DB changes so we don't hold a transaction open
        result = cancel_order(order.fivesim_order_id)
        if isinstance(result, dict) and 'error' in result:
            return Response({'error': result['error']}, status=status.HTTP_400_BAD_REQUEST)

        with db_transaction.atomic():
            get_user_model().objects.filter(pk=request.user.pk).update(
                wallet_balance=F('wallet_balance') + order.amount_charged
            )
            order.status = 'CANCELED'
            order.save()

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
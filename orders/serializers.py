from rest_framework import serializers
from .models import Order, Transaction

class OrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ['id', 'fivesim_order_id', 'phone', 'product', 'country', 'status', 'sms_code', 'amount_charged', 'created_at']


class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = ['id', 'amount', 'type', 'reference', 'description', 'created_at']
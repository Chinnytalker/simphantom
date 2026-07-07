from decimal import Decimal
from rest_framework import serializers


class InitializePaymentSerializer(serializers.Serializer):
    # min_value blocks zero/negative amounts; max_value blocks absurd values.
    # A tighter NGN floor is enforced in the view (after USD→NGN conversion).
    amount   = serializers.DecimalField(
        max_digits=10, decimal_places=2,
        min_value=Decimal('0.01'), max_value=Decimal('10000000'),
    )
    currency = serializers.ChoiceField(choices=['NGN', 'USD'], default='NGN')

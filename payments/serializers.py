from rest_framework import serializers

class InitializePaymentSerializer(serializers.Serializer):
    amount   = serializers.DecimalField(max_digits=10, decimal_places=2)
    currency = serializers.ChoiceField(choices=['NGN', 'USD'], default='NGN')
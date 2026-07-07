import json
from django.db import models
from django.conf import settings


class Order(models.Model):
    SERVICE_TYPES = [
        ('VIRTUAL_NUMBER', 'Virtual Number'),
        ('OTP_VERIFICATION', 'OTP Verification'),
        ('TEMPORARY_EMAIL', 'Temporary Email'),
        ('VPN', 'VPN Subscription'),
        ('ESIM', 'eSIM Package'),
        ('RESIDENTIAL_PROXY', 'Residential Proxy'),
        ('BULK_SMS', 'Bulk SMS'),
        ('PHONE_LOOKUP', 'Phone Number Lookup'),
        ('AIRTIME', 'Airtime / Data Top-up'),
        ('GIFT_CARD', 'Gift Card'),
        ('UTILITY', 'Utility Bill Payment'),
    ]

    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('RECEIVED', 'Received'),
        ('CANCELED', 'Canceled'),
        ('FINISHED', 'Finished'),
        ('EXPIRED', 'Expired'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    service_type = models.CharField(max_length=20, choices=SERVICE_TYPES)
    fivesim_order_id = models.CharField(max_length=100, blank=True, null=True)

    # Generic fields that work for all services
    phone = models.CharField(max_length=20, blank=True, null=True)  # For numbers, OTP
    email = models.CharField(max_length=255, blank=True, null=True)  # For emails, VPN
    product = models.CharField(max_length=100)
    country = models.CharField(max_length=100, blank=True, null=True)
    operator = models.CharField(max_length=50, default='any')

    # For SMS/OTP/etc
    sms_code = models.CharField(max_length=50, blank=True, null=True)
    verification_code = models.CharField(max_length=50, blank=True, null=True)

    # For proxies, VPN, etc
    proxy_ip = models.CharField(max_length=100, blank=True, null=True)
    credentials = models.TextField(blank=True, null=True)  # JSON for complex data

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    amount_charged = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    # Number of automatic number swaps performed after no SMS arrived
    retry_count = models.PositiveSmallIntegerField(default=0)

    @property
    def provider(self):
        """Which API provider fulfilled this order: 'grizzly', 'tigersms', or '5sim'."""
        creds = json.loads(self.credentials or '{}')
        return creds.get('provider', '5sim')

    def __str__(self):
        return f"{self.user.email} - {self.get_service_type_display()} - {self.product}"


class Transaction(models.Model):
    TYPE_CHOICES = [('CREDIT', 'Credit'), ('DEBIT', 'Debit')]
    STATUS_CHOICES = [('PENDING', 'Pending'), ('COMPLETED', 'Completed')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    # PENDING is only used for wallet top-ups awaiting Paystack confirmation.
    # Everything else (debits, refunds) is COMPLETED the moment it's written.
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='COMPLETED')
    reference = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class ProviderStats(models.Model):
    """
    OTP delivery success rate per provider + service + country.
    An attempt is counted when a number is issued; a success when an SMS
    code actually arrives. Used to route each purchase to whichever
    provider is really delivering codes for that combo.
    """
    provider = models.CharField(max_length=20)   # 'grizzly', '5sim', 'tigersms'
    product = models.CharField(max_length=100)   # e.g. 'whatsapp'
    country = models.CharField(max_length=100)   # e.g. 'nigeria'
    total_orders = models.PositiveIntegerField(default=0)
    successful = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('provider', 'product', 'country')

    @property
    def success_rate(self):
        return self.successful / self.total_orders if self.total_orders else 0.0

    def __str__(self):
        return f"{self.provider} {self.product}/{self.country}: {self.successful}/{self.total_orders}"
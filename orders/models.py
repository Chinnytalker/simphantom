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

    def __str__(self):
        return f"{self.user.email} - {self.get_service_type_display()} - {self.product}"


class Transaction(models.Model):
    TYPE_CHOICES = [('CREDIT', 'Credit'), ('DEBIT', 'Debit')]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    reference = models.CharField(max_length=200, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
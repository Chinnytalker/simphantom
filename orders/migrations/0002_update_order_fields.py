from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0001_initial'),
    ]

    operations = [
        # service_type
        migrations.AddField(
            model_name='order',
            name='service_type',
            field=models.CharField(
                choices=[
                    ('VIRTUAL_NUMBER', 'Virtual Number'),
                    ('OTP_VERIFICATION', 'OTP Verification'),
                    ('TEMPORARY_EMAIL', 'Temporary Email'),
                    ('VPN', 'VPN Subscription'),
                    ('ESIM', 'eSIM Package'),
                    ('RESIDENTIAL_PROXY', 'Residential Proxy'),
                    ('BULK_SMS', 'Bulk SMS'),
                    ('PHONE_LOOKUP', 'Phone Number Lookup'),
                ],
                default='VIRTUAL_NUMBER',
                max_length=20,
            ),
            preserve_default=False,
        ),
        # make fivesim_order_id nullable
        migrations.AlterField(
            model_name='order',
            name='fivesim_order_id',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        # make phone nullable
        migrations.AlterField(
            model_name='order',
            name='phone',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        # make country nullable
        migrations.AlterField(
            model_name='order',
            name='country',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        # make sms_code already nullable in initial — no change needed
        # add new fields
        migrations.AddField(
            model_name='order',
            name='email',
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='verification_code',
            field=models.CharField(blank=True, max_length=50, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='proxy_ip',
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='credentials',
            field=models.TextField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]

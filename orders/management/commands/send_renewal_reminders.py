"""
Management command: send_renewal_reminders
Run every 6 hours via cron. Warns users 3 days before VPN/eSIM expiry.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone

from orders.models import Order


class Command(BaseCommand):
    help = 'Email users whose VPN or eSIM expires within 3 days.'

    def handle(self, *args, **options):
        now = timezone.now()
        soon = now + timezone.timedelta(days=3)

        expiring = Order.objects.filter(
            status='FINISHED',
            expires_at__gt=now,
            expires_at__lte=soon,
            service_type__in=['VPN', 'ESIM'],
        ).select_related('user')

        self.stdout.write(f'[renewal_reminders] {expiring.count()} orders expiring within 3 days')

        for order in expiring:
            days_left = max(1, (order.expires_at - now).days)
            if order.service_type == 'VPN':
                from main.notifications import send_vpn_expiring_email
                send_vpn_expiring_email(order.user, order, days_left)
                self.stdout.write(f'  [VPN] reminded user {order.user.email} — {days_left}d left')
            elif order.service_type == 'ESIM':
                from main.notifications import send_esim_expiring_email
                send_esim_expiring_email(order.user, order, days_left)
                self.stdout.write(f'  [eSIM] reminded user {order.user.email} — {days_left}d left')

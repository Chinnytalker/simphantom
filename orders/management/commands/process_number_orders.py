"""
Management command: process_number_orders
Background worker for virtual number / OTP orders. Does everything the
dashboard poll does, server-side — so users who closed the tab still get:
  - their OTP delivered (stored + emailed) the moment it arrives
  - a silent number auto-swapped for a fresh one after 2.5 min
  - a full refund when the window expires with no SMS

Run once per pass (cron style) or keep it alive with --loop N seconds:
  python manage.py process_number_orders --loop 20
"""
import json
import logging
import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from orders.models import Order
from orders.views import (
    EXPIRY_MINUTES,
    RETRY_AFTER_MINUTES,
    MAX_RETRIES,
    cancel_at_provider,
    deliver_sms,
    poll_provider,
    refund_order,
    retry_with_fresh_number,
)
from main.notifications import (
    send_sms_code_email,
    send_number_swapped_email,
    send_order_refunded_email,
)

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Deliver OTPs, auto-swap silent numbers and refund expired virtual number orders.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--loop', type=int, default=0,
            help='Run forever, sleeping this many seconds between passes (0 = single pass)',
        )

    def handle(self, *args, **options):
        interval = options['loop']
        if interval:
            self.stdout.write(f'[number-worker] running every {interval}s — Ctrl+C to stop')
        while True:
            close_old_connections()
            try:
                processed = self.process_all()
                if processed:
                    self.stdout.write(f'[number-worker] processed {processed} pending order(s)')
            except Exception:
                logger.exception('[number-worker] pass failed')
            if not interval:
                break
            time.sleep(interval)

    def process_all(self):
        pending = Order.objects.filter(
            status='PENDING',
            service_type__in=['VIRTUAL_NUMBER', 'OTP_VERIFICATION'],
            fivesim_order_id__isnull=False,
        ).select_related('user')

        count = 0
        for order in pending:
            try:
                self.process_order(order)
                count += 1
            except Exception:
                logger.exception('[number-worker] failed processing order %s', order.id)
        return count

    def process_order(self, order):
        creds = json.loads(order.credentials or '{}')
        provider = creds.get('provider', '5sim')
        now = timezone.now()

        state = poll_provider(provider, order.fivesim_order_id)

        # 1. Code arrived — deliver it and email the user
        if state['status'] == 'RECEIVED' and state.get('code'):
            if deliver_sms(order, state['code']):
                send_sms_code_email(order.user, order, state['code'])
                self.stdout.write(f'  [SMS] order #{order.id} code delivered')
            return

        # 2. Provider cancelled it on their side — refund
        if state['status'] == 'CANCELED':
            if refund_order(order.user, order, 'CANCELED',
                            f"Refund: {order.product} number cancelled"):
                send_order_refunded_email(order.user, order)
                self.stdout.write(f'  [Refund] order #{order.id} cancelled by provider — refunded')
            return

        # 3. Window fully expired with no SMS — cancel + refund
        if order.expires_at and now >= order.expires_at:
            cancel_at_provider(provider, order.fivesim_order_id)
            if refund_order(order.user, order, 'EXPIRED',
                            f"Auto-refund: {order.product} number expired with no SMS"):
                send_order_refunded_email(order.user, order)
                self.stdout.write(f'  [Refund] order #{order.id} expired — refunded')
            return

        # 4. Halfway through with nothing — swap in a fresh number
        retry_due_at = order.expires_at - timedelta(
            minutes=EXPIRY_MINUTES - RETRY_AFTER_MINUTES
        ) if order.expires_at else None
        if (
            order.retry_count < MAX_RETRIES
            and retry_due_at and now >= retry_due_at
        ):
            if retry_with_fresh_number(order, provider):
                send_number_swapped_email(order.user, order)
                self.stdout.write(f'  [Swap] order #{order.id} got fresh number {order.phone}')

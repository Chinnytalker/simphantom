"""
Management command: expire_orders
Run every hour via cron. Handles:
  - Marking expired VPN/eSIM orders as EXPIRED
  - Auto-renewing VPN if user has enough wallet balance
  - Sending expiry / renewal emails
"""
import json
import logging
import uuid

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.db import transaction as db_transaction
from django.db.models import F
from django.utils import timezone

from orders.models import Order, Transaction

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Expire VPN/eSIM orders that have passed their expires_at, auto-renew VPN when possible.'

    def handle(self, *args, **options):
        now = timezone.now()
        expired = Order.objects.filter(
            status='FINISHED',
            expires_at__lt=now,
            service_type__in=['VPN', 'ESIM'],
        ).select_related('user')

        self.stdout.write(f'[expire_orders] checking {expired.count()} expired orders at {now}')

        for order in expired:
            if order.service_type == 'VPN':
                self._handle_vpn(order)
            elif order.service_type == 'ESIM':
                self._handle_esim(order)

    # ── VPN ──────────────────────────────────────────────────────────────────

    def _handle_vpn(self, order):
        from services.config import VPN_PLANS
        from main.notifications import send_vpn_renewed_email, send_vpn_expired_email

        creds = json.loads(order.credentials or '{}')
        plan_id = order.product
        plan = next((p for p in VPN_PLANS if p['id'] == plan_id), None)

        if plan is None:
            self._expire(order)
            return

        price = Decimal(str(plan['price_ngn']))
        user = order.user

        # Auto-renew if wallet has enough balance
        with db_transaction.atomic():
            deducted = type(user).objects.filter(
                pk=user.pk, wallet_balance__gte=price
            ).update(wallet_balance=F('wallet_balance') - price)

            if not deducted:
                # Can't renew — expire and notify
                order.status = 'EXPIRED'
                order.save(update_fields=['status'])
                send_vpn_expired_email(user, order, plan)
                self.stdout.write(f'  [VPN] order #{order.id} expired — insufficient balance')
                return

            # Re-register the same WireGuard peer (same keys, same IP if possible)
            try:
                from services import vpn_server, wireguard
                client_public_key = creds.get('client_public_key', '')
                result = vpn_server.add_peer(plan['location'], client_public_key)
                if 'error' in result:
                    raise RuntimeError(result['error'])
                assigned_ip = result.get('assigned_ip', creds.get('assigned_ip', ''))
                server_public_key = result.get('server_public_key', creds.get('server_public_key', ''))
                server_endpoint = creds.get('server_endpoint', '')
                client_private_key = creds.get('client_private_key', '')
            except Exception as exc:
                # Refund and expire on provisioning failure
                type(user).objects.filter(pk=user.pk).update(wallet_balance=F('wallet_balance') + price)
                order.status = 'EXPIRED'
                order.save(update_fields=['status'])
                send_vpn_expired_email(user, order, plan)
                logger.error('[expire_orders] VPN renewal provisioning failed order #%s: %s', order.id, exc)
                return

            config_str = wireguard.build_client_config(
                client_private_key, assigned_ip, server_public_key, server_endpoint
            )

            ref = 'VPN-RENEW-' + uuid.uuid4().hex[:10].upper()
            Transaction.objects.create(
                user=user, amount=price, type='DEBIT', reference=ref,
                description=f'VPN auto-renewal — {plan["name"]}',
            )

            expires_at = timezone.now() + timezone.timedelta(days=plan['duration_days'])
            new_order = Order.objects.create(
                user=user,
                service_type='VPN',
                product=plan_id,
                status='FINISHED',
                amount_charged=price,
                expires_at=expires_at,
                credentials=json.dumps({
                    **creds,
                    'assigned_ip': assigned_ip,
                    'server_public_key': server_public_key,
                    'config': config_str,
                }),
            )

            order.status = 'EXPIRED'
            order.save(update_fields=['status'])

        send_vpn_renewed_email(user, order, new_order, plan, expires_at)
        self.stdout.write(f'  [VPN] order #{order.id} auto-renewed → new order #{new_order.id}')

    # ── eSIM ─────────────────────────────────────────────────────────────────

    def _handle_esim(self, order):
        from main.notifications import send_esim_expired_email
        self._expire(order)
        send_esim_expired_email(order.user, order)
        self.stdout.write(f'  [eSIM] order #{order.id} expired')

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _expire(self, order):
        order.status = 'EXPIRED'
        order.save(update_fields=['status'])

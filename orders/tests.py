"""
Tests for the virtual number order flow: buying, SMS delivery, cancelling,
expiry refunds, and the wallet-safety rules around them.
All provider calls (Grizzly / TigerSMS / 5sim) are mocked — no network.
"""
import json
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from django.core.cache import cache
from services.config import FLAT_MARKUP_NGN, _FX_CACHE_KEY, get_usd_to_ngn
from .models import Order, Transaction, ProviderStats

User = get_user_model()

# Pin the FX rate so tests never hit the network and prices are deterministic.
FX_RATE = 1650.0
cache.set(_FX_CACHE_KEY, FX_RATE, 3600)

# One grizzly-priced product used across tests: cost $0.50
GRIZZLY_COST_USD = 0.50
SERVER_PRICE = Decimal(str(round(GRIZZLY_COST_USD * get_usd_to_ngn() + FLAT_MARKUP_NGN, 2)))

# 5sim offering the same product at the same cost — inside the price range
FIVESIM_PRODUCTS_OK = {'whatsapp': {'Price': GRIZZLY_COST_USD, 'Qty': 20}}
# ...and a version priced far outside the range
FIVESIM_PRODUCTS_EXPENSIVE = {'whatsapp': {'Price': GRIZZLY_COST_USD * 30, 'Qty': 20}}


def grizzly_prices(_country_id):
    return {'wa': {'count': 10, 'cost': GRIZZLY_COST_USD}}


class BuyNumberTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='buyer', email='buyer@test.com', password='pass12345'
        )
        User.objects.filter(pk=self.user.pk).update(wallet_balance=Decimal('10000.00'))
        self.client.force_login(self.user)

    def buy(self, **overrides):
        payload = {
            'country': 'nigeria',
            'product': 'whatsapp',
            'operator': 'any',
            'price': str(SERVER_PRICE),
        }
        payload.update(overrides)
        return self.client.post('/api/orders/buy/', payload, content_type='application/json')

    @patch('orders.views.grizzlysms.get_balance', return_value={'balance': 100})
    @patch('orders.views.grizzlysms.get_number', return_value={'id': '111', 'phone': '+2348012345678'})
    @patch('orders.views.grizzlysms.get_prices', side_effect=grizzly_prices)
    def test_successful_buy_charges_server_price(self, *_mocks):
        res = self.buy()
        self.assertEqual(res.status_code, 201, res.content)

        order = Order.objects.get(user=self.user)
        self.assertEqual(order.status, 'PENDING')
        self.assertEqual(order.amount_charged, SERVER_PRICE)
        self.assertEqual(order.provider, 'grizzly')

        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('10000.00') - SERVER_PRICE)
        self.assertTrue(Transaction.objects.filter(reference=f'ORDER-{order.id}', type='DEBIT').exists())

    @patch('orders.views.grizzlysms.get_prices', side_effect=grizzly_prices)
    def test_negative_price_rejected(self, *_mocks):
        res = self.buy(price='-50000')
        self.assertEqual(res.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('10000.00'))
        self.assertEqual(Order.objects.count(), 0)

    @patch('orders.views.grizzlysms.get_prices', side_effect=grizzly_prices)
    def test_understated_price_rejected(self, *_mocks):
        res = self.buy(price='1')
        self.assertEqual(res.status_code, 400)
        self.assertIn('Price has changed', res.json()['error'])
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('10000.00'))

    @patch('orders.views.grizzlysms.get_prices', side_effect=grizzly_prices)
    def test_insufficient_balance_rejected(self, *_mocks):
        User.objects.filter(pk=self.user.pk).update(wallet_balance=Decimal('10.00'))
        res = self.buy()
        self.assertEqual(res.status_code, 400)
        self.assertIn('Insufficient', res.json()['error'])
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('10.00'))

    @patch('orders.views.get_products', return_value=FIVESIM_PRODUCTS_OK)
    @patch('orders.views.buy_number', return_value={'error': 'no free phones'})
    @patch('orders.views.grizzlysms.get_number', return_value={'error': 'NO_NUMBERS'})
    @patch('orders.views.grizzlysms.get_prices', side_effect=grizzly_prices)
    def test_provider_failure_refunds_wallet(self, *_mocks):
        res = self.buy()
        self.assertEqual(res.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('10000.00'))
        self.assertEqual(Order.objects.count(), 0)

    @patch('orders.views.get_balance', create=True)
    @patch('orders.views.buy_number', return_value={'id': '222', 'phone': '+15550001111', 'status': 'PENDING'})
    @patch('orders.views.get_products', return_value=FIVESIM_PRODUCTS_EXPENSIVE)
    @patch('orders.views.grizzlysms.get_number', return_value={'error': 'NO_NUMBERS'})
    @patch('orders.views.grizzlysms.get_prices', side_effect=grizzly_prices)
    def test_fallback_provider_outside_price_range_is_skipped(self, *_mocks):
        """5sim costs 30x the charged price — must not be bought as fallback."""
        res = self.buy()
        self.assertEqual(res.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('10000.00'))
        self.assertEqual(Order.objects.count(), 0)

    @patch('orders.views.grizzlysms.get_balance', return_value={'balance': 100})
    @patch('orders.views.grizzlysms.get_number', return_value={'id': '111', 'phone': '+2348012345678'})
    @patch('orders.views.grizzlysms.get_prices', side_effect=grizzly_prices)
    def test_buy_records_provider_attempt(self, *_mocks):
        self.buy()
        stats = ProviderStats.objects.get(provider='grizzly', product='whatsapp', country='nigeria')
        self.assertEqual(stats.total_orders, 1)
        self.assertEqual(stats.successful, 0)

    @patch('orders.views.grizzlysms.get_balance', return_value={'balance': 100})
    @patch('orders.views.grizzlysms.get_number', return_value={'id': '222', 'phone': '+2348012345678'})
    @patch('orders.views.grizzlysms.get_prices', side_effect=grizzly_prices)
    def test_otp_purchase_uses_otp_markup(self, *_mocks):
        """OTP verification uses the same buy flow with the higher OTP markup."""
        from services.config import OTP_MARKUP_NGN
        otp_price = Decimal(str(round(GRIZZLY_COST_USD * 1650 + OTP_MARKUP_NGN, 2)))
        res = self.buy(service_type='OTP_VERIFICATION', price=str(otp_price))
        self.assertEqual(res.status_code, 201, res.content)
        order = Order.objects.get(user=self.user)
        self.assertEqual(order.service_type, 'OTP_VERIFICATION')
        self.assertEqual(order.amount_charged, otp_price)      # OTP markup applied
        self.assertGreater(otp_price, SERVER_PRICE)            # costs more than a plain number
        self.assertEqual(order.provider, 'grizzly')

    @patch('orders.views.get_products', return_value={'error': 'down'})
    @patch('orders.views.grizzlysms.get_prices', return_value={})
    def test_no_price_available_rejected(self, *_mocks):
        res = self.buy()
        self.assertEqual(res.status_code, 400)
        self.assertIn('unavailable', res.json()['error'])


class OrderLifecycleTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='holder', email='holder@test.com', password='pass12345'
        )
        User.objects.filter(pk=self.user.pk).update(wallet_balance=Decimal('5000.00'))
        self.client.force_login(self.user)
        self.order = Order.objects.create(
            user=self.user,
            service_type='VIRTUAL_NUMBER',
            fivesim_order_id='555',
            phone='+2348011112222',
            product='whatsapp',
            country='nigeria',
            status='PENDING',
            amount_charged=Decimal('2325.00'),
            credentials=json.dumps({'provider': 'grizzly'}),
            expires_at=timezone.now() + timedelta(minutes=5),
        )

    # ── SMS / OTP delivery ────────────────────────────────────────────────

    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'RECEIVED', 'code': '493827'})
    def test_check_delivers_sms_code(self, _m):
        res = self.client.get(f'/api/orders/check/{self.order.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['sms_code'], '493827')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'RECEIVED')

    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'PENDING', 'code': None})
    def test_check_pending_no_code(self, _m):
        res = self.client.get(f'/api/orders/check/{self.order.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['status'], 'PENDING')
        self.assertIsNone(res.json()['sms_code'])

    # ── Expiry ────────────────────────────────────────────────────────────

    @patch('orders.views.grizzlysms.cancel_number', return_value={'success': True})
    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'PENDING', 'code': None})
    def test_expired_order_refunds_once(self, *_m):
        Order.objects.filter(pk=self.order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        res = self.client.get(f'/api/orders/check/{self.order.id}/')
        self.assertEqual(res.json()['status'], 'EXPIRED')
        self.assertTrue(res.json()['refunded'])

        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('5000.00') + self.order.amount_charged)

        # Second check must not refund again
        res2 = self.client.get(f'/api/orders/check/{self.order.id}/')
        self.assertEqual(res2.json()['status'], 'EXPIRED')
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('5000.00') + self.order.amount_charged)
        self.assertEqual(Transaction.objects.filter(type='CREDIT').count(), 1)

    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'RECEIVED', 'code': '777888'})
    def test_late_sms_delivered_instead_of_expiring(self, _m):
        Order.objects.filter(pk=self.order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        res = self.client.get(f'/api/orders/check/{self.order.id}/')
        self.assertEqual(res.json()['status'], 'RECEIVED')
        self.assertEqual(res.json()['sms_code'], '777888')
        # No refund — the code was delivered
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('5000.00'))

    # ── Cancelling ────────────────────────────────────────────────────────

    @patch('orders.views.grizzlysms.cancel_number', return_value={'success': True})
    def test_cancel_refunds_wallet(self, _m):
        res = self.client.post(f'/api/orders/cancel/{self.order.id}/')
        self.assertEqual(res.status_code, 200)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'CANCELED')
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('5000.00') + self.order.amount_charged)

        # Cancelling again must fail and not refund again
        res2 = self.client.post(f'/api/orders/cancel/{self.order.id}/')
        self.assertEqual(res2.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('5000.00') + self.order.amount_charged)

    def test_cannot_cancel_received_order(self):
        Order.objects.filter(pk=self.order.pk).update(status='RECEIVED', sms_code='123456')
        res = self.client.post(f'/api/orders/cancel/{self.order.id}/')
        self.assertEqual(res.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('5000.00'))

    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'PENDING', 'code': None})
    @patch('orders.views.grizzlysms.cancel_number', return_value={'error': 'EARLY_CANCEL_DENIED'})
    def test_early_cancel_gets_friendly_message(self, *_m):
        """Grizzly refuses cancels in the first 2 min (verified live) — no raw error to user."""
        res = self.client.post(f'/api/orders/cancel/{self.order.id}/')
        self.assertEqual(res.status_code, 400)
        self.assertIn('2 minutes after purchase', res.json()['error'])
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'PENDING')
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('5000.00'))

    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'RECEIVED', 'code': '654321'})
    @patch('orders.views.grizzlysms.cancel_number', return_value={'error': 'EARLY_CANCEL_DENIED'})
    def test_cancel_rejected_shows_waiting_sms(self, *_m):
        res = self.client.post(f'/api/orders/cancel/{self.order.id}/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['sms_code'], '654321')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'RECEIVED')
        # No refund — user got the code
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('5000.00'))

    # ── Cross-path double-refund guard ────────────────────────────────────

    @patch('orders.views.grizzlysms.cancel_number', return_value={'success': True})
    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'CANCELED', 'code': None})
    def test_check_after_cancel_does_not_double_refund(self, *_m):
        # Cancel first (refund #1)
        self.client.post(f'/api/orders/cancel/{self.order.id}/')
        # Simulate a stale poll that still sees the order as PENDING
        Order.objects.filter(pk=self.order.pk).update(status='PENDING')
        self.client.get(f'/api/orders/check/{self.order.id}/')

        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('5000.00') + self.order.amount_charged)
        self.assertEqual(Transaction.objects.filter(type='CREDIT').count(), 1)

    # ── Silent auto-retry (number swap) ───────────────────────────────────

    def make_retry_due(self):
        # < 2.5 min left on the 5-min window → retry is due but not yet expired
        Order.objects.filter(pk=self.order.pk).update(
            expires_at=timezone.now() + timedelta(minutes=2)
        )

    @patch('orders.views.buy_number', return_value={'id': '999', 'phone': '+15550002222', 'status': 'PENDING'})
    @patch('orders.views.get_products', return_value=FIVESIM_PRODUCTS_OK)
    @patch('orders.views.grizzlysms.cancel_number', return_value={'success': True})
    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'PENDING', 'code': None})
    def test_silent_retry_swaps_number(self, *_m):
        self.order.amount_charged = SERVER_PRICE
        self.order.save(update_fields=['amount_charged'])
        self.make_retry_due()

        res = self.client.get(f'/api/orders/check/{self.order.id}/')
        data = res.json()
        self.assertTrue(data.get('number_changed'), data)
        self.assertEqual(data['phone'], '+15550002222')
        self.assertEqual(data['status'], 'PENDING')

        self.order.refresh_from_db()
        self.assertEqual(self.order.retry_count, 1)
        self.assertEqual(self.order.phone, '+15550002222')
        self.assertEqual(self.order.fivesim_order_id, '999')
        self.assertEqual(self.order.provider, '5sim')  # switched away from grizzly
        # Fresh 5-minute window
        self.assertGreater(self.order.expires_at, timezone.now() + timedelta(minutes=4))
        # No refund happened — user keeps waiting on the new number
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('5000.00'))

    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'PENDING', 'code': None})
    def test_no_second_retry(self, _m):
        Order.objects.filter(pk=self.order.pk).update(retry_count=1)
        self.make_retry_due()
        res = self.client.get(f'/api/orders/check/{self.order.id}/')
        self.assertFalse(res.json().get('number_changed'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.retry_count, 1)

    @patch('orders.views.grizzlysms.get_number', return_value={'id': '444', 'phone': '+2348099998888'})
    @patch('orders.views.grizzlysms.get_prices', side_effect=grizzly_prices)
    @patch('orders.views.get_products', return_value=FIVESIM_PRODUCTS_EXPENSIVE)
    @patch('orders.views.grizzlysms.cancel_number', return_value={'success': True})
    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'PENDING', 'code': None})
    def test_retry_skips_overpriced_provider(self, *_m):
        """5sim way over the paid price → retry stays on grizzly with a fresh number."""
        self.order.amount_charged = SERVER_PRICE
        self.order.save(update_fields=['amount_charged'])
        self.make_retry_due()

        res = self.client.get(f'/api/orders/check/{self.order.id}/')
        self.assertTrue(res.json().get('number_changed'))
        self.order.refresh_from_db()
        self.assertEqual(self.order.provider, 'grizzly')
        self.assertEqual(self.order.phone, '+2348099998888')

    @patch('orders.views.grizzlysms.get_number', return_value={'error': 'NO_NUMBERS'})
    @patch('orders.views.grizzlysms.get_prices', side_effect=grizzly_prices)
    @patch('orders.views.get_products', return_value={'error': 'down'})
    @patch('orders.views.grizzlysms.cancel_number', return_value={'success': True})
    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'PENDING', 'code': None})
    def test_retry_failure_leaves_order_for_expiry_refund(self, *_m):
        self.order.amount_charged = SERVER_PRICE
        self.order.save(update_fields=['amount_charged'])
        self.make_retry_due()

        res = self.client.get(f'/api/orders/check/{self.order.id}/')
        self.assertFalse(res.json().get('number_changed'))
        self.order.refresh_from_db()
        # Claim was rolled back so the expiry path can still refund normally
        self.assertEqual(self.order.retry_count, 0)
        self.assertEqual(self.order.status, 'PENDING')

    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'RECEIVED', 'code': '111222'})
    def test_sms_delivery_records_success_stat(self, _m):
        self.client.get(f'/api/orders/check/{self.order.id}/')
        stats = ProviderStats.objects.get(provider='grizzly', product='whatsapp', country='nigeria')
        self.assertEqual(stats.successful, 1)

    # ── Access control & history ──────────────────────────────────────────

    def test_other_users_order_is_404(self):
        stranger = User.objects.create_user(
            username='stranger', email='s@test.com', password='pass12345'
        )
        self.client.force_login(stranger)
        self.assertEqual(self.client.get(f'/api/orders/check/{self.order.id}/').status_code, 404)
        self.assertEqual(self.client.post(f'/api/orders/cancel/{self.order.id}/').status_code, 404)

    def test_history_lists_orders(self):
        res = self.client.get('/api/orders/history/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['id'], self.order.id)
        self.assertEqual(data[0]['provider'], 'grizzly')


@patch('orders.management.commands.process_number_orders.send_order_refunded_email')
@patch('orders.management.commands.process_number_orders.send_number_swapped_email')
@patch('orders.management.commands.process_number_orders.send_sms_code_email')
class BackgroundWorkerTests(TestCase):
    """The process_number_orders worker — delivery, swap and refund with no user polling."""

    def setUp(self):
        self.user = User.objects.create_user(
            username='sleeper', email='sleeper@test.com', password='pass12345'
        )
        User.objects.filter(pk=self.user.pk).update(wallet_balance=Decimal('5000.00'))
        self.order = Order.objects.create(
            user=self.user,
            service_type='VIRTUAL_NUMBER',
            fivesim_order_id='777',
            phone='+2348033334444',
            product='whatsapp',
            country='nigeria',
            status='PENDING',
            amount_charged=SERVER_PRICE,
            credentials=json.dumps({'provider': 'grizzly'}),
            expires_at=timezone.now() + timedelta(minutes=5),
        )

    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'RECEIVED', 'code': '424242'})
    def test_worker_delivers_code_and_emails(self, _status, mock_code_email, *_mails):
        call_command('process_number_orders')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'RECEIVED')
        self.assertEqual(self.order.sms_code, '424242')
        mock_code_email.assert_called_once()
        stats = ProviderStats.objects.get(provider='grizzly', product='whatsapp', country='nigeria')
        self.assertEqual(stats.successful, 1)

    @patch('orders.views.grizzlysms.cancel_number', return_value={'success': True})
    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'PENDING', 'code': None})
    def test_worker_refunds_expired_order(self, _s, _c, _code_mail, _swap_mail, mock_refund_email):
        Order.objects.filter(pk=self.order.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        call_command('process_number_orders')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'EXPIRED')
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('5000.00') + SERVER_PRICE)
        mock_refund_email.assert_called_once()

        # A second pass must not refund again
        call_command('process_number_orders')
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('5000.00') + SERVER_PRICE)

    @patch('orders.views.buy_number', return_value={'id': '888', 'phone': '+15550003333', 'status': 'PENDING'})
    @patch('orders.views.get_products', return_value=FIVESIM_PRODUCTS_OK)
    @patch('orders.views.grizzlysms.cancel_number', return_value={'success': True})
    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'PENDING', 'code': None})
    def test_worker_swaps_silent_number(self, _s, _c, _p, _b, _code_mail, mock_swap_email, _refund_mail):
        Order.objects.filter(pk=self.order.pk).update(expires_at=timezone.now() + timedelta(minutes=2))
        call_command('process_number_orders')
        self.order.refresh_from_db()
        self.assertEqual(self.order.retry_count, 1)
        self.assertEqual(self.order.phone, '+15550003333')
        self.assertEqual(self.order.provider, '5sim')
        mock_swap_email.assert_called_once()

    @patch('orders.views.grizzlysms.get_status', return_value={'status': 'CANCELED', 'code': None})
    def test_worker_refunds_provider_cancelled_order(self, _s, _code_mail, _swap_mail, mock_refund_email):
        call_command('process_number_orders')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'CANCELED')
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('5000.00') + SERVER_PRICE)
        mock_refund_email.assert_called_once()

    @patch('orders.views.grizzlysms.get_status', return_value={'error': 'timeout'})
    def test_worker_leaves_order_alone_on_provider_error(self, _s, *_mails):
        call_command('process_number_orders')
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'PENDING')
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('5000.00'))

"""
Tests for the payments money path: amount validation, webhook signature
verification, and idempotent (never double-credit) wallet top-ups.
Paystack HTTP is mocked — no network.
"""
import hashlib
import hmac
import json
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from orders.models import Transaction

User = get_user_model()

PAYSTACK_SECRET = 'sk_test_dummy_secret'


def sign(body: bytes) -> str:
    return hmac.new(PAYSTACK_SECRET.encode(), body, hashlib.sha512).hexdigest()


def paystack_ok(amount_kobo=100000):
    resp = type('R', (), {})()
    resp.status_code = 200
    resp.json = lambda: {'status': True, 'data': {'status': 'success', 'amount': amount_kobo}}
    return resp


@override_settings(PAYSTACK_SECRET=PAYSTACK_SECRET, RATELIMIT_ENABLE=False)
class InitializePaymentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('payer', 'payer@test.com', 'pass12345')
        self.client.force_login(self.user)

    def init(self, **body):
        return self.client.post('/api/payments/initialize/', body, content_type='application/json')

    def test_valid_amount_creates_pending_transaction(self):
        res = self.init(amount='5000', currency='NGN')
        self.assertEqual(res.status_code, 200, res.content)
        ref = res.json()['reference']
        txn = Transaction.objects.get(reference=ref)
        self.assertEqual(txn.status, 'PENDING')
        self.assertEqual(txn.type, 'CREDIT')
        self.assertEqual(txn.amount, Decimal('5000'))
        self.assertEqual(res.json()['amount'], 500000)  # kobo

    def test_zero_and_negative_rejected(self):
        for bad in ('0', '-100', '0.00'):
            res = self.init(amount=bad)
            self.assertEqual(res.status_code, 400, f'{bad} should be rejected')
        self.assertEqual(Transaction.objects.count(), 0)

    def test_below_ngn_floor_rejected(self):
        res = self.init(amount='50', currency='NGN')
        self.assertEqual(res.status_code, 400)
        self.assertIn('Minimum', res.json()['error'])

    def test_absurd_amount_rejected(self):
        res = self.init(amount='99999999999')
        self.assertEqual(res.status_code, 400)

    def test_login_required(self):
        self.client.logout()
        res = self.init(amount='5000')
        self.assertIn(res.status_code, (401, 403))


@override_settings(PAYSTACK_SECRET=PAYSTACK_SECRET, RATELIMIT_ENABLE=False)
class WebhookTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('wh', 'wh@test.com', 'pass12345')
        User.objects.filter(pk=self.user.pk).update(wallet_balance=Decimal('0'))
        self.ref = 'ref-abc-123'
        self.txn = Transaction.objects.create(
            user=self.user, amount=Decimal('3000'), type='CREDIT',
            status='PENDING', reference=self.ref, description='Wallet top-up (pending)',
        )

    def post_event(self, body: bytes, signature=None):
        return self.client.post(
            '/api/payments/webhook/paystack/',
            data=body, content_type='application/json',
            HTTP_X_PAYSTACK_SIGNATURE=signature if signature is not None else sign(body),
        )

    def charge_body(self, ref=None, amount_kobo=300000):
        return json.dumps({
            'event': 'charge.success',
            'data': {'reference': ref or self.ref, 'amount': amount_kobo, 'status': 'success'},
        }).encode()

    @patch('main.notifications.send_deposit_confirmed_email')
    def test_valid_webhook_credits_once(self, _email):
        body = self.charge_body()
        res = self.post_event(body)
        self.assertEqual(res.status_code, 200)

        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('3000'))
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, 'COMPLETED')

        # Replaying the same event must NOT credit again
        self.post_event(body)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('3000'))

    def test_bad_signature_rejected(self):
        res = self.post_event(self.charge_body(), signature='deadbeef')
        self.assertEqual(res.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('0'))
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, 'PENDING')

    def test_invalid_json_rejected(self):
        res = self.post_event(b'not json{')
        self.assertEqual(res.status_code, 400)

    def test_unknown_reference_ignored_gracefully(self):
        res = self.post_event(self.charge_body(ref='does-not-exist'))
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('0'))

    @patch('main.notifications.send_deposit_confirmed_email')
    def test_credits_paystack_amount_not_stored(self, _email):
        # Even though the stored txn said 3000, we credit what Paystack reports
        self.post_event(self.charge_body(amount_kobo=250000))  # ₦2500 actually paid
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('2500'))


@override_settings(PAYSTACK_SECRET=PAYSTACK_SECRET, RATELIMIT_ENABLE=False)
class VerifyPaymentTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('vf', 'vf@test.com', 'pass12345')
        User.objects.filter(pk=self.user.pk).update(wallet_balance=Decimal('0'))
        self.client.force_login(self.user)
        self.ref = 'ref-verify-1'
        self.txn = Transaction.objects.create(
            user=self.user, amount=Decimal('1000'), type='CREDIT',
            status='PENDING', reference=self.ref, description='Wallet top-up (pending)',
        )

    def verify(self):
        return self.client.post('/api/payments/verify/', {'reference': self.ref},
                                content_type='application/json')

    @patch('main.notifications.send_deposit_confirmed_email')
    def test_verify_credits_once(self, _email):
        with patch('requests.get', return_value=paystack_ok()):
            res = self.verify()
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()['status'], 'ok')
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('1000'))

        with patch('requests.get', return_value=paystack_ok()):
            res2 = self.verify()
        self.assertEqual(res2.json()['status'], 'already_confirmed')
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('1000'))

    @patch('main.notifications.send_deposit_confirmed_email')
    def test_webhook_then_verify_no_double_credit(self, _email):
        body = json.dumps({
            'event': 'charge.success',
            'data': {'reference': self.ref, 'amount': 100000, 'status': 'success'},
        }).encode()
        self.client.post('/api/payments/webhook/paystack/', data=body,
                         content_type='application/json',
                         HTTP_X_PAYSTACK_SIGNATURE=sign(body))
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('1000'))

        with patch('requests.get', return_value=paystack_ok()):
            res = self.verify()
        self.assertEqual(res.json()['status'], 'already_confirmed')
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('1000'))

    def test_missing_reference_rejected(self):
        res = self.client.post('/api/payments/verify/', {}, content_type='application/json')
        self.assertEqual(res.status_code, 400)


NOWPAY_IPN = 'ipn_test_secret'


def sign_nowpay(body: bytes) -> str:
    data = json.loads(body)
    sorted_payload = json.dumps(data, sort_keys=True, separators=(',', ':'))
    return hmac.new(NOWPAY_IPN.encode(), sorted_payload.encode(), hashlib.sha512).hexdigest()


@override_settings(NOWPAYMENTS_IPN_SECRET=NOWPAY_IPN, RATELIMIT_ENABLE=False, MIN_CRYPTO_USD=3)
class CryptoDepositTests(TestCase):
    def setUp(self):
        from django.core.cache import cache
        from services.config import _FX_CACHE_KEY
        cache.set(_FX_CACHE_KEY, 1650.0, 3600)  # deterministic FX, no network
        self.user = User.objects.create_user('crypto', 'crypto@test.com', 'pass12345')
        User.objects.filter(pk=self.user.pk).update(wallet_balance=Decimal('0'))
        self.client.force_login(self.user)

    @patch('payments.nowpayments.create_invoice',
           return_value={'invoice_url': 'https://nowpayments.io/payment/?iid=123', 'id': '123'})
    def test_deposit_creates_pending_and_returns_url(self, _m):
        res = self.client.post('/api/payments/crypto/deposit/', {'amount_usd': 10},
                               content_type='application/json')
        self.assertEqual(res.status_code, 200, res.content)
        self.assertIn('invoice_url', res.json())
        txn = Transaction.objects.get(user=self.user, type='CREDIT')
        self.assertEqual(txn.status, 'PENDING')
        self.assertEqual(txn.amount, Decimal('16500.00'))  # $10 @ 1650

    def test_below_minimum_rejected(self):
        res = self.client.post('/api/payments/crypto/deposit/', {'amount_usd': 1},
                               content_type='application/json')
        self.assertEqual(res.status_code, 400)
        self.assertEqual(Transaction.objects.count(), 0)

    @patch('payments.nowpayments.create_invoice', return_value={'error': 'nowpayments down'})
    def test_invoice_failure_drops_pending_row(self, _m):
        res = self.client.post('/api/payments/crypto/deposit/', {'amount_usd': 10},
                               content_type='application/json')
        self.assertEqual(res.status_code, 502)
        self.assertEqual(Transaction.objects.count(), 0)  # orphan pending row cleaned up


@override_settings(NOWPAYMENTS_IPN_SECRET=NOWPAY_IPN)
class NowPaymentsWebhookTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('cw', 'cw@test.com', 'pass12345')
        User.objects.filter(pk=self.user.pk).update(wallet_balance=Decimal('0'))
        self.ref = 'CRYPTO-ABC123'
        self.txn = Transaction.objects.create(
            user=self.user, amount=Decimal('16500'), type='CREDIT', status='PENDING',
            reference=self.ref, description='Wallet top-up (pending) [crypto $10]',
        )

    def post_ipn(self, body: bytes, sig=None):
        return self.client.post('/api/payments/webhook/nowpayments/', data=body,
                                content_type='application/json',
                                HTTP_X_NOWPAYMENTS_SIG=sig if sig is not None else sign_nowpay(body))

    def body(self, status_='finished', ref=None):
        return json.dumps({'payment_status': status_, 'order_id': ref or self.ref,
                           'payment_id': 999, 'pay_amount': 0.0004}).encode()

    @patch('main.notifications.send_deposit_confirmed_email')
    def test_finished_credits_once(self, _m):
        res = self.post_ipn(self.body('finished'))
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('16500'))
        # replay must not double-credit
        self.post_ipn(self.body('finished'))
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('16500'))

    def test_bad_signature_rejected(self):
        res = self.post_ipn(self.body('finished'), sig='deadbeef')
        self.assertEqual(res.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('0'))

    def test_pending_status_does_not_credit(self):
        res = self.post_ipn(self.body('waiting'))
        self.assertEqual(res.status_code, 200)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('0'))
        self.txn.refresh_from_db()
        self.assertEqual(self.txn.status, 'PENDING')

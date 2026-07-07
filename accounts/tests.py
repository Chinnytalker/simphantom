"""
Tests for the referral system: code generation, capture at signup (email +
session), and awarding the referrer on the referee's first funded deposit.
"""
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from accounts.referrals import apply_referral, award_referral, SESSION_KEY
from orders.models import Transaction

User = get_user_model()


class ReferralCodeTests(TestCase):
    def test_every_user_gets_a_unique_code(self):
        a = User.objects.create_user('a', 'a@test.com', 'pass12345')
        b = User.objects.create_user('b', 'b@test.com', 'pass12345')
        self.assertTrue(a.referral_code)
        self.assertTrue(b.referral_code)
        self.assertNotEqual(a.referral_code, b.referral_code)
        self.assertEqual(len(a.referral_code), 8)

    def test_code_is_stable_across_saves(self):
        a = User.objects.create_user('a', 'a@test.com', 'pass12345')
        original = a.referral_code
        a.wallet_balance = Decimal('10')
        a.save()
        a.refresh_from_db()
        self.assertEqual(a.referral_code, original)


@override_settings(RATELIMIT_ENABLE=False)
class ReferralSignupTests(TestCase):
    def test_register_page_links_referrer(self):
        referrer = User.objects.create_user('ref', 'ref@test.com', 'pass12345')

        # Visiting with ?ref= captures the code into the session
        self.client.get(f'/register/?ref={referrer.referral_code}')
        self.assertEqual(self.client.session.get(SESSION_KEY), referrer.referral_code)

        with patch('main.notifications.send_welcome_email'), \
             patch('accounts.turnstile.verify_turnstile', return_value=True):
            self.client.post('/register/', {
                'username': 'newbie', 'email': 'newbie@test.com',
                'password': 'pass12345', 'password_confirm': 'pass12345',
                'cf-turnstile-response': 'x',
            })

        newbie = User.objects.get(username='newbie')
        self.assertEqual(newbie.referred_by_id, referrer.pk)

    def test_typed_referral_code_links_referrer(self):
        """A code typed into the signup form (no invite link) links the referrer."""
        referrer = User.objects.create_user('reflink', 'reflink@test.com', 'pass12345')
        with patch('main.notifications.send_welcome_email'), \
             patch('accounts.turnstile.verify_turnstile', return_value=True):
            self.client.post('/register/', {
                'username': 'typed', 'email': 'typed@test.com',
                'password': 'pass12345', 'password_confirm': 'pass12345',
                'referral_code': referrer.referral_code.lower(),  # case-insensitive
                'cf-turnstile-response': 'x',
            })
        self.assertEqual(User.objects.get(username='typed').referred_by_id, referrer.pk)

    def test_unknown_code_is_ignored(self):
        with patch('main.notifications.send_welcome_email'), \
             patch('accounts.turnstile.verify_turnstile', return_value=True):
            self.client.get('/register/?ref=NOTREAL9')
            self.client.post('/register/', {
                'username': 'solo', 'email': 'solo@test.com',
                'password': 'pass12345', 'password_confirm': 'pass12345',
                'cf-turnstile-response': 'x',
            })
        self.assertIsNone(User.objects.get(username='solo').referred_by_id)

    def test_cannot_refer_self(self):
        user = User.objects.create_user('self', 'self@test.com', 'pass12345')
        request = type('R', (), {'session': {SESSION_KEY: user.referral_code}})()
        apply_referral(request, user)
        user.refresh_from_db()
        self.assertIsNone(user.referred_by_id)


@override_settings(REFERRAL_BONUS_PCT='0.05', REFERRAL_BONUS_CAP='500')
class ReferralAwardTests(TestCase):
    def setUp(self):
        self.referrer = User.objects.create_user('rr', 'rr@test.com', 'pass12345')
        User.objects.filter(pk=self.referrer.pk).update(wallet_balance=Decimal('0'))
        self.referee = User.objects.create_user('re', 're@test.com', 'pass12345')
        self.referee.referred_by = self.referrer
        self.referee.save(update_fields=['referred_by'])

    def test_award_credits_percentage_capped(self):
        awarded = award_referral(self.referee.pk, Decimal('2000'))  # 5% = 100
        self.assertEqual(awarded, Decimal('100.00'))
        self.referrer.refresh_from_db()
        self.assertEqual(self.referrer.wallet_balance, Decimal('100.00'))
        self.assertTrue(Transaction.objects.filter(
            reference=f'REFERRAL-{self.referee.pk}', type='CREDIT').exists())

    def test_award_respects_cap(self):
        awarded = award_referral(self.referee.pk, Decimal('50000'))  # 5% = 2500 -> capped 500
        self.assertEqual(awarded, Decimal('500.00'))

    def test_award_is_once_only(self):
        award_referral(self.referee.pk, Decimal('2000'))
        second = award_referral(self.referee.pk, Decimal('2000'))
        self.assertIsNone(second)
        self.referrer.refresh_from_db()
        self.assertEqual(self.referrer.wallet_balance, Decimal('100.00'))

    def test_no_award_without_referrer(self):
        solo = User.objects.create_user('solo', 'solo@test.com', 'pass12345')
        self.assertIsNone(award_referral(solo.pk, Decimal('2000')))

    def test_award_fires_on_deposit_confirmation(self):
        """The real hook: crediting a pending top-up rewards the referrer."""
        from payments.views import credit_wallet_once
        Transaction.objects.create(
            user=self.referee, amount=Decimal('1000'), type='CREDIT',
            status='PENDING', reference='dep-1', description='Wallet top-up (pending)',
        )
        with patch('main.notifications.send_deposit_confirmed_email'):
            credit_wallet_once('dep-1', self.referee.pk, Decimal('1000'))
        self.referrer.refresh_from_db()
        self.assertEqual(self.referrer.wallet_balance, Decimal('50.00'))  # 5% of 1000


class DashboardRenderTests(TestCase):
    """Smoke test: the dashboard template renders with all the new context."""

    def setUp(self):
        from django.core.cache import cache
        from services.config import _FX_CACHE_KEY
        cache.set(_FX_CACHE_KEY, 1650.0, 3600)  # avoid network in the FX lookup
        self.user = User.objects.create_user('dash', 'dash@test.com', 'pass12345')
        self.client.force_login(self.user)

    def test_dashboard_renders_with_referral_card(self):
        res = self.client.get('/dashboard/')
        self.assertEqual(res.status_code, 200)
        body = res.content.decode()
        self.assertIn('Refer &amp; Earn', body)
        self.assertIn(self.user.referral_code, body)
        # Live FX rate reached the top-up modal
        self.assertIn('$1 = ₦1,650', body)

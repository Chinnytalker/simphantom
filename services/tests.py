"""
Tests for the Grizzly price-dump filtering and the dynamic service map:
junk $0.0001 placeholder services and unmappable raw codes must never reach
listings, while services from Grizzly's official getServicesList become
buyable under generated slugs.
"""
import time

from django.core.cache import cache
from django.test import TestCase

from services import grizzly
from services.config import _FX_CACHE_KEY

# Pin the FX rate so listing-price tests never hit the network.
cache.set(_FX_CACHE_KEY, 1650.0, 3600)

# 'wa' (whatsapp) and 'tg' (telegram) are in the static map; 'aob' is only in
# Grizzly's live service list; 'aba' is a raw code known to neither.
FAKE_DUMP = {
    '19': {  # nigeria
        'wa': {'cost': 0.50, 'count': 100},        # real, static map
        'tg': {'cost': 0.0001, 'count': 5000},     # junk price — filter
        'aba': {'cost': 0.25, 'count': 300},       # unmappable raw code
        'ig': {'cost': 0.30, 'count': 0},          # no stock — filter
        'aob': {'cost': 0.20, 'count': 50},        # dynamic-mapped service
    },
    '78': {  # france
        'wa': {'cost': 0.0001, 'count': 9999},     # junk price — filter
        'tg': {'cost': 0.15, 'count': 250},        # real, static map
    },
}

# What Grizzly's getServicesList "returns" in these tests
FAKE_SERVICES = {
    'wa': 'WhatsApp Messenger',   # static map must still win for this code
    'aob': 'Anthropic',           # new dynamic service
    'aff': 'C6 Bank',             # slug with spaces -> c6_bank
}


class GrizzlyFilterTests(TestCase):
    def setUp(self):
        self._saved = (
            grizzly._prices_cache, grizzly._prices_cache_time,
            grizzly._services_cache, grizzly._services_cache_time,
            grizzly._dynamic_maps_cache, grizzly._dynamic_maps_src_time,
        )
        grizzly._prices_cache = FAKE_DUMP
        grizzly._prices_cache_time = time.time()
        grizzly._services_cache = FAKE_SERVICES
        grizzly._services_cache_time = time.time()
        grizzly._dynamic_maps_cache = None
        grizzly._dynamic_maps_src_time = None

    def tearDown(self):
        (grizzly._prices_cache, grizzly._prices_cache_time,
         grizzly._services_cache, grizzly._services_cache_time,
         grizzly._dynamic_maps_cache, grizzly._dynamic_maps_src_time) = self._saved

    # ── Junk filtering ────────────────────────────────────────────────────

    def test_get_prices_drops_junk_and_empty(self):
        prices = grizzly.get_prices('19')
        self.assertIn('wa', prices)
        self.assertNotIn('tg', prices)   # $0.0001 junk
        self.assertNotIn('ig', prices)   # zero stock
        # unmapped codes survive here (raw layer) but are dropped by listings
        self.assertIn('aba', prices)

    def test_service_catalog_only_mapped_real_services(self):
        catalog = grizzly.get_service_catalog()
        names = {c['name'] for c in catalog}
        self.assertIn('whatsapp', names)   # real in nigeria
        self.assertIn('telegram', names)   # real in france
        self.assertNotIn('aba', names)     # unmappable raw code

        wa = next(c for c in catalog if c['name'] == 'whatsapp')
        self.assertEqual(wa['qty'], 100)   # france's junk-priced wa not counted

    def test_prices_by_service_drops_junk_countries(self):
        rows = grizzly.get_prices_by_service('whatsapp')
        countries = {r['country'] for r in rows}
        self.assertIn('nigeria', countries)
        self.assertNotIn('france', countries)  # junk-priced there

    def test_products_endpoint_hides_raw_codes(self):
        res = self.client.get('/api/services/grizzly/products/nigeria/')
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('whatsapp', data)
        self.assertNotIn('aba', data)      # raw code hidden
        self.assertNotIn('telegram', data)  # junk-priced in nigeria

    def test_catalog_endpoint_clean(self):
        res = self.client.get('/api/services/grizzly/catalog/')
        self.assertEqual(res.status_code, 200)
        names = {p['name'] for p in res.json()}
        self.assertNotIn('aba', names)

    # ── Dynamic service map ───────────────────────────────────────────────

    def test_dynamic_service_becomes_buyable(self):
        self.assertEqual(grizzly.code_to_product('aob'), 'anthropic')
        self.assertEqual(grizzly.map_service('anthropic'), 'aob')
        # multi-word names slugify with underscores
        self.assertEqual(grizzly.map_service('c6_bank'), 'aff')

    def test_static_map_wins_over_dynamic(self):
        # 'wa' appears in the live list as 'WhatsApp Messenger' but the static
        # name must stay 'whatsapp' so existing orders/stats keep working
        self.assertEqual(grizzly.code_to_product('wa'), 'whatsapp')
        self.assertEqual(grizzly.map_service('whatsapp'), 'wa')
        self.assertIsNone(grizzly.map_service('whatsapp_messenger'))

    def test_dynamic_service_appears_in_listings(self):
        catalog = grizzly.get_service_catalog()
        names = {c['name'] for c in catalog}
        self.assertIn('anthropic', names)

        res = self.client.get('/api/services/grizzly/products/nigeria/')
        self.assertIn('anthropic', res.json())


# ══════════════════════════════════════════════════════════════════════════════
#  Reloadly (airtime, gift cards, utilities) — all external calls mocked
# ══════════════════════════════════════════════════════════════════════════════
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model

from orders.models import Order
from services.config import airtime_naira_price, giftcard_naira_price
from services.reloadly_views import _airtime_local_price as _a_price

RUser = get_user_model()


class ReloadlyTokenTests(TestCase):
    def test_token_is_cached_per_audience(self):
        from services import reloadly
        cache.delete('reloadly_token_airtime_sb')
        cache.delete('reloadly_token_airtime_live')
        fake = type('R', (), {})()
        fake.status_code = 200
        fake.raise_for_status = lambda: None
        fake.json = lambda: {'access_token': 'tok-123', 'expires_in': 3600}
        with patch('services.reloadly.requests.post', return_value=fake) as m, \
             patch('services.reloadly._creds', return_value=('id', 'secret')):
            t1 = reloadly._get_token('airtime')
            t2 = reloadly._get_token('airtime')
        self.assertEqual(t1, 'tok-123')
        self.assertEqual(t2, 'tok-123')
        self.assertEqual(m.call_count, 1)  # second call served from cache


class AirtimeTests(TestCase):
    def setUp(self):
        cache.set(_FX_CACHE_KEY, 1650.0, 3600)
        self.user = RUser.objects.create_user('air', 'air@test.com', 'pass12345')
        RUser.objects.filter(pk=self.user.pk).update(wallet_balance=Decimal('50000'))
        self.client.force_login(self.user)

    MTN = {
        'operator_id': 341, 'name': 'MTN Nigeria', 'country': 'NG', 'is_data': False,
        'denomination_type': 'RANGE', 'min_amount': 0.04, 'max_amount': 160.77,
        'local_min_amount': 50.0, 'local_max_amount': 200000.0, 'fixed_amounts': [],
        'local_fixed_amounts': [], 'local_fixed_descriptions': {}, 'currency': 'NGN',
        'fx_rate': 1650.0, 'logo': None,
    }
    MTN_DATA = {
        'operator_id': 345, 'name': 'MTN Nigeria Data', 'country': 'NG', 'is_data': True,
        'denomination_type': 'FIXED', 'min_amount': None, 'max_amount': None,
        'local_min_amount': None, 'local_max_amount': None, 'fixed_amounts': [],
        'local_fixed_amounts': [500.0, 1000.0],
        'local_fixed_descriptions': {'500': '1GB - 30days', '1000': '2.5GB - 30days'},
        'currency': 'NGN', 'fx_rate': 1650.0, 'logo': None,
    }

    def _local_price(self, local, fx=1650.0, country='NG', currency='NGN'):
        # Mirrors _airtime_local_price: NG = face value, abroad = cost + markup
        from services.reloadly_views import _airtime_local_price
        op = {'country': country, 'currency': currency, 'fx_rate': fx}
        return _airtime_local_price(op, local)

    def test_nigeria_face_value_but_abroad_marked_up(self):
        # Nigeria: customer pays the exact face value (₦500 airtime = ₦500)
        ng_op = {'country': 'NG', 'currency': 'NGN', 'fx_rate': 1244.0}
        self.assertEqual(_a_price(ng_op, 500), 500)
        self.assertEqual(_a_price(ng_op, 100), 100)
        # Abroad (Ghana): cost via FX + 15% markup, well above a naive convert
        gh_op = {'country': 'GH', 'currency': 'GHS', 'fx_rate': 12.0}
        expected = airtime_naira_price(5 / 12.0)   # 5 GHS -> USD -> NGN + markup
        self.assertEqual(_a_price(gh_op, 5), expected)

    @patch('services.reloadly.operators_for_country', return_value=[MTN, MTN_DATA])
    @patch('services.reloadly.detect_operator', return_value=MTN)
    def test_detect_returns_local_amounts_and_data(self, *_m):
        r = self.client.get('/api/services/airtime/detect/?phone=2348031234567&country=NG')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d['detected'])
        self.assertEqual(d['airtime']['operator'], 'MTN Nigeria')
        self.assertEqual(d['airtime']['denominations'][0]['local_amount'], 100)
        self.assertEqual(d['airtime']['denominations'][0]['naira_price'], self._local_price(100))
        self.assertEqual(len(d['related']), 1)
        self.assertEqual(d['related'][0]['denominations'][0]['description'], '1GB - 30days')

    @patch('services.reloadly.countries', return_value=[{'code': 'NG', 'name': 'Nigeria'},
                                                        {'code': 'GB', 'name': 'United Kingdom'}])
    def test_countries_endpoint(self, _m):
        r = self.client.get('/api/services/airtime/countries/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 2)
        self.assertEqual(r.json()[0]['code'], 'NG')

    @patch('services.reloadly.operators_for_country', return_value=[MTN])
    @patch('services.reloadly.detect_operator', return_value={'error': 'not found'})
    def test_detect_falls_back_to_manual_picker(self, *_m):
        r = self.client.get('/api/services/airtime/detect/?phone=08012345678&country=NG')
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertFalse(d['detected'])
        self.assertEqual(len(d['operators']), 1)
        self.assertTrue(d['operators'][0]['denominations'])

    @patch('services.reloadly.topup', return_value={'transactionId': 99, 'operatorName': 'MTN Nigeria'})
    @patch('services.reloadly.get_operator', return_value=MTN)
    def test_purchase_local_amount_deducts(self, *_m):
        price = Decimal(str(self._local_price(500)))
        r = self.client.post('/api/services/airtime/purchase/', {
            'phone': '2348031234567', 'country': 'NG', 'operator_id': 341, 'local_amount': 500,
        }, content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('50000') - price)
        self.assertTrue(Order.objects.filter(user=self.user, service_type='AIRTIME').exists())

    @patch('services.reloadly.get_operator', return_value=MTN)
    def test_purchase_rejects_out_of_range(self, _m):
        r = self.client.post('/api/services/airtime/purchase/', {
            'phone': '2348031234567', 'country': 'NG', 'operator_id': 341, 'local_amount': 10,
        }, content_type='application/json')  # below the ₦50 minimum
        self.assertEqual(r.status_code, 400)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('50000'))

    @patch('services.reloadly.topup', return_value={'error': 'operator down'})
    @patch('services.reloadly.get_operator', return_value=MTN)
    def test_purchase_failure_refunds(self, *_m):
        r = self.client.post('/api/services/airtime/purchase/', {
            'phone': '2348031234567', 'country': 'NG', 'operator_id': 341, 'local_amount': 500,
        }, content_type='application/json')
        self.assertEqual(r.status_code, 502)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('50000'))
        self.assertFalse(Order.objects.filter(service_type='AIRTIME').exists())


class GiftCardTests(TestCase):
    def setUp(self):
        cache.set(_FX_CACHE_KEY, 1650.0, 3600)
        self.user = RUser.objects.create_user('gc', 'gc@test.com', 'pass12345')
        RUser.objects.filter(pk=self.user.pk).update(wallet_balance=Decimal('100000'))
        self.client.force_login(self.user)

    PRODUCT = {
        'productId': 10, 'productName': 'Amazon US', 'denominationType': 'FIXED',
        'recipientCurrencyCode': 'USD', 'fixedRecipientDenominations': [10, 25],
        'fixedRecipientToSenderDenominationsMap': {'10': 10.0, '25': 25.0},
        'brand': {'brandName': 'Amazon'}, 'country': {'isoName': 'US'}, 'logoUrls': [],
    }

    @patch('services.reloadly.gift_card_products', return_value=[PRODUCT])
    def test_products_listed_with_prices(self, _m):
        r = self.client.get('/api/services/giftcards/?country=US')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data[0]['name'], 'Amazon US')
        self.assertEqual(data[0]['denominations'][0]['naira_price'], giftcard_naira_price(10.0))

    @patch('services.reloadly.gift_card_redeem_code', return_value=[{'cardNumber': 'ABC-123', 'pinCode': '9999'}])
    @patch('services.reloadly.gift_card_order', return_value={'transactionId': 555})
    @patch('services.reloadly.gift_card_product', return_value=PRODUCT)
    def test_purchase_stores_code(self, *_m):
        price = Decimal(str(giftcard_naira_price(10.0)))
        r = self.client.post('/api/services/giftcards/purchase/', {
            'product_id': 10, 'recipient_denom': 10,
        }, content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        data = r.json()
        self.assertEqual(data['status'], 'FINISHED')
        self.assertEqual(data['cards'][0]['cardNumber'], 'ABC-123')
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('100000') - price)

    @patch('services.reloadly.gift_card_order', return_value={'error': 'out of stock'})
    @patch('services.reloadly.gift_card_product', return_value=PRODUCT)
    def test_purchase_failure_refunds(self, *_m):
        r = self.client.post('/api/services/giftcards/purchase/', {
            'product_id': 10, 'recipient_denom': 10,
        }, content_type='application/json')
        self.assertEqual(r.status_code, 502)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('100000'))


class UtilityTests(TestCase):
    def setUp(self):
        cache.set(_FX_CACHE_KEY, 1650.0, 3600)
        self.user = RUser.objects.create_user('ut', 'ut@test.com', 'pass12345')
        RUser.objects.filter(pk=self.user.pk).update(wallet_balance=Decimal('50000'))
        self.client.force_login(self.user)

    BILLER = {'id': 7, 'name': 'Ikeja Electric', 'type': 'ELECTRICITY_BILL_PAYMENT',
              'serviceType': 'PREPAID', 'countryCode': 'NG',
              'localTransactionCurrencyCode': 'NGN', 'minLocalTransactionAmount': 1000,
              'maxLocalTransactionAmount': 50000}

    @patch('services.reloadly.billers', return_value=[BILLER])
    def test_billers_listed(self, _m):
        r = self.client.get('/api/services/utilities/billers/?country=NG')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()[0]['name'], 'Ikeja Electric')

    @patch('services.reloadly.pay_bill', return_value={'id': 888, 'status': 'SUCCESSFUL'})
    def test_pay_deducts_and_creates_order(self, _m):
        r = self.client.post('/api/services/utilities/pay/', {
            'biller_id': 7, 'subscriber_account': '12345', 'amount_local': 5000, 'currency': 'NGN',
        }, content_type='application/json')
        self.assertEqual(r.status_code, 201, r.content)
        self.user.refresh_from_db()
        # NGN bill: charged local amount * 1.07 service fee
        self.assertEqual(self.user.wallet_balance, Decimal('50000') - Decimal('5350'))
        self.assertTrue(Order.objects.filter(service_type='UTILITY').exists())

    @patch('services.reloadly.pay_bill', return_value={'error': 'biller unavailable'})
    def test_pay_failure_refunds(self, _m):
        r = self.client.post('/api/services/utilities/pay/', {
            'biller_id': 7, 'subscriber_account': '12345', 'amount_local': 5000, 'currency': 'NGN',
        }, content_type='application/json')
        self.assertEqual(r.status_code, 502)
        self.user.refresh_from_db()
        self.assertEqual(self.user.wallet_balance, Decimal('50000'))

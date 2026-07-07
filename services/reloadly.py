"""
Reloadly integration — one module, three products:
  • Airtime / Data top-ups   (audience: topups.reloadly.com)
  • Gift Cards               (audience: giftcards.reloadly.com)
  • Utility Bill Payments    (audience: utilities.reloadly.com)

Each product needs its own OAuth2 client-credentials token (scoped per audience).
Tokens are cached in the shared Django cache so all workers reuse them and we
don't re-auth on every request. Set RELOADLY_SANDBOX=true to hit the sandbox.
"""
import logging
import time

import requests
from decouple import config
from django.core.cache import cache

logger = logging.getLogger('services')

AUTH_URL = 'https://auth.reloadly.com/oauth/token'

SANDBOX = config('RELOADLY_SANDBOX', default=True, cast=bool)

# (production_host, sandbox_host, versioned Accept header) per product
_PRODUCTS = {
    'airtime':  ('https://topups.reloadly.com',    'https://topups-sandbox.reloadly.com',
                 'application/com.reloadly.topups-v1+json'),
    'giftcards': ('https://giftcards.reloadly.com', 'https://giftcards-sandbox.reloadly.com',
                  'application/com.reloadly.giftcards-v1+json'),
    'utilities': ('https://utilities.reloadly.com', 'https://utilities-sandbox.reloadly.com',
                  'application/com.reloadly.utilities-v1+json'),
}


def _creds():
    # Sandbox and live use separate credentials — pick the set that matches the
    # environment so flipping RELOADLY_SANDBOX switches keys, audience and URLs.
    if SANDBOX:
        return (config('RELOADLY_SANDBOX_CLIENT_ID', default=''),
                config('RELOADLY_SANDBOX_CLIENT_SECRET', default=''))
    return (config('RELOADLY_CLIENT_ID', default=''),
            config('RELOADLY_CLIENT_SECRET', default=''))


def base_url(product):
    prod_host, sandbox_host, _ = _PRODUCTS[product]
    return sandbox_host if SANDBOX else prod_host


def _accept(product):
    return _PRODUCTS[product][2]


def _audience(product):
    # The audience must match the environment host: sandbox host in sandbox
    # mode, production host in production mode (Reloadly rejects a mismatch).
    return base_url(product)


def _get_token(product):
    """Return a cached (or freshly minted) access token for a product audience."""
    cache_key = f'reloadly_token_{product}_{"sb" if SANDBOX else "live"}'
    token = cache.get(cache_key)
    if token:
        return token

    client_id, client_secret = _creds()
    if not client_id or not client_secret:
        raise RuntimeError('Reloadly credentials are not configured')

    resp = requests.post(AUTH_URL, json={
        'client_id': client_id,
        'client_secret': client_secret,
        'grant_type': 'client_credentials',
        'audience': _audience(product),
    }, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    token = data['access_token']
    # Cache well within the token's lifetime (sandbox 24h, prod 60d)
    ttl = int(data.get('expires_in', 3600))
    cache.set(cache_key, token, max(60, int(ttl * 0.8)))
    return token


def _headers(product):
    return {
        'Authorization': f'Bearer {_get_token(product)}',
        'Accept': _accept(product),
        'Content-Type': 'application/json',
    }


def _request(product, method, path, *, params=None, json_body=None, timeout=30):
    """Single choke point for all Reloadly HTTP. Returns dict or {'error': ...}."""
    url = f'{base_url(product)}{path}'
    try:
        resp = requests.request(
            method, url, headers=_headers(product),
            params=params, json=json_body, timeout=timeout,
        )
        if resp.status_code >= 400:
            try:
                body = resp.json()
                msg = body.get('message') or body.get('errorCode') or resp.text
            except ValueError:
                msg = resp.text
            logger.warning('[Reloadly] %s %s -> %s %s', method, path, resp.status_code, msg)
            return {'error': str(msg), 'status_code': resp.status_code}
        if resp.text:
            return resp.json()
        return {}
    except Exception as e:
        logger.exception('[Reloadly] request failed %s %s', method, path)
        return {'error': str(e)}


def countries(product):
    """
    All countries a product supports (airtime ~159, gift cards ~169,
    utilities ~5). Cached for a day — the list rarely changes.
    Returns [{'code','name'}] sorted by name, or {'error': ...}.
    """
    cache_key = f'reloadly_countries_{product}_{"sb" if SANDBOX else "live"}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    data = _request(product, 'GET', '/countries')
    if isinstance(data, dict) and 'error' in data:
        return data
    items = data if isinstance(data, list) else data.get('content', [])
    out = []
    for c in items:
        code = c.get('isoName') or c.get('countryCode') or c.get('code')
        if not code:
            continue
        out.append({'code': code, 'name': c.get('name') or code})
    out.sort(key=lambda x: x['name'])
    cache.set(cache_key, out, 86400)
    return out


def get_balance(product='airtime'):
    """Account balance (USD) for a product. {'balance': float, 'currencyCode': str} or {'error'}."""
    data = _request(product, 'GET', '/accounts/balance')
    if 'error' in data:
        return data
    return {'balance': float(data.get('balance', 0)), 'currencyCode': data.get('currencyCode', 'USD')}


# ── Airtime / Data ────────────────────────────────────────────────────────────

def _normalize_operator(data, country_iso2=''):
    return {
        'operator_id': data.get('operatorId'),
        'name': data.get('name', ''),
        'country': (data.get('country') or {}).get('isoName', country_iso2.upper()),
        'denomination_type': data.get('denominationType', 'RANGE'),  # FIXED | RANGE
        'sender_currency': data.get('senderCurrencyCode', 'USD'),
        'destination_currency': data.get('destinationCurrencyCode', ''),
        'min_amount': data.get('minAmount'),
        'max_amount': data.get('maxAmount'),
        'fixed_amounts': data.get('fixedAmounts', []) or [],
        'local_min_amount': data.get('localMinAmount'),
        'local_max_amount': data.get('localMaxAmount'),
        'local_fixed_amounts': data.get('localFixedAmounts', []) or [],
        'local_fixed_descriptions': data.get('localFixedAmountsDescriptions') or {},
        'currency': data.get('destinationCurrencyCode') or '',
        'fx_rate': (data.get('fx') or {}).get('rate'),
        'is_data': bool(data.get('data', False)),
        'logo': (data.get('logoUrls') or [None])[0],
    }


def detect_operator(phone, country_iso2):
    """
    Auto-detect the operator for a phone number.
    Returns a normalized dict or {'error': ...}.
    """
    path = f'/operators/auto-detect/phone/{phone}/countries/{country_iso2.upper()}'
    data = _request('airtime', 'GET', path, params={'suggestedAmountsMap': 'false'})
    if 'error' in data:
        return data
    return _normalize_operator(data, country_iso2)


def get_operator(operator_id):
    """Full detail for one operator (fx + local bundle amounts/descriptions)."""
    data = _request('airtime', 'GET', f'/operators/{operator_id}')
    if isinstance(data, dict) and 'error' in data:
        return data
    return _normalize_operator(data)


def operators_for_country(country_iso2, include_data=True):
    """
    List all airtime/data operators for a country — used as the fallback when
    auto-detect can't match a number. Returns a normalized list or {'error'}.
    """
    cache_key = f'reloadly_ops_{country_iso2.upper()}_{"sb" if SANDBOX else "live"}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    data = _request('airtime', 'GET', f'/operators/countries/{country_iso2.upper()}',
                    params={'includeBundles': 'true' if include_data else 'false'})
    if isinstance(data, dict) and 'error' in data:
        return data
    items = data if isinstance(data, list) else data.get('content', [])
    result = [_normalize_operator(o, country_iso2) for o in items]
    cache.set(cache_key, result, 3600)
    return result


def topup(operator_id, amount, country_iso2, phone, use_local_amount=False):
    """
    Send an airtime/data top-up. `amount` is in sender currency (USD) unless
    use_local_amount=True. Returns the transaction dict or {'error': ...}.
    """
    body = {
        'operatorId': operator_id,
        'amount': amount,
        'useLocalAmount': use_local_amount,
        'recipientPhone': {'countryCode': country_iso2.upper(), 'number': phone},
    }
    return _request('airtime', 'POST', '/topups', json_body=body)


# ── Gift Cards ────────────────────────────────────────────────────────────────

def gift_card_products(country_iso2=None, size=200, page=1):
    """List gift card products, optionally filtered by country. Cached 1h."""
    cache_key = f'reloadly_gc_{country_iso2 or "all"}_{"sb" if SANDBOX else "live"}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    params = {'size': size, 'page': page}
    if country_iso2:
        params['countryCode'] = country_iso2.upper()
    data = _request('giftcards', 'GET', '/products', params=params)
    if isinstance(data, dict) and 'error' in data:
        return data
    # Paginated responses wrap items in "content"; some return a bare list
    result = data.get('content', []) if isinstance(data, dict) else data
    if isinstance(result, list):
        cache.set(cache_key, result, 3600)
    return result


def gift_card_product(product_id):
    return _request('giftcards', 'GET', f'/products/{product_id}')


def gift_card_order(product_id, unit_price, quantity=1, recipient_email='', sender_name='SimPhantom',
                    country_iso2=None, custom_identifier=None):
    """Place a gift card order. unit_price is in the product's recipient currency."""
    body = {
        'productId': product_id,
        'quantity': quantity,
        'unitPrice': unit_price,
        'senderName': sender_name,
        'recipientEmail': recipient_email,
    }
    if country_iso2:
        body['countryCode'] = country_iso2.upper()
    if custom_identifier:
        body['customIdentifier'] = custom_identifier
    return _request('giftcards', 'POST', '/orders', json_body=body)


def gift_card_redeem_code(transaction_id):
    """Fetch the card number / PIN for a completed gift card order."""
    data = _request('giftcards', 'GET', f'/orders/transactions/{transaction_id}/cards')
    if isinstance(data, dict) and 'error' in data:
        return data
    return data  # list of {cardNumber, pinCode}


# ── Utility Bill Payments ─────────────────────────────────────────────────────

def billers(country_iso2=None, biller_type=None, size=200, page=1):
    """List utility billers (electricity, water, TV, internet). Returns list or {'error'}."""
    params = {'size': size, 'page': page}
    if country_iso2:
        params['countryISOCode'] = country_iso2.upper()
    if biller_type:
        params['type'] = biller_type  # ELECTRICITY_BILL_PAYMENT, WATER_BILL_PAYMENT, TV_BILL_PAYMENT, INTERNET_BILL_PAYMENT
    cache_key = f'reloadly_billers_{country_iso2 or "all"}_{biller_type or "all"}_{"sb" if SANDBOX else "live"}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached
    data = _request('utilities', 'GET', '/billers', params=params)
    if isinstance(data, dict) and 'error' in data:
        return data
    result = data.get('content', []) if isinstance(data, dict) else data
    if isinstance(result, list):
        cache.set(cache_key, result, 3600)
    return result


def pay_bill(biller_id, amount, subscriber_account, use_local_amount=True, reference=None):
    """Pay a utility bill. Returns the transaction dict or {'error': ...}."""
    body = {
        'billerId': biller_id,
        'amount': amount,
        'subscriberAccountNumber': subscriber_account,
        'useLocalAmount': use_local_amount,
    }
    if reference:
        body['referenceId'] = reference
    return _request('utilities', 'POST', '/pay', json_body=body)


def utility_transaction(transaction_id):
    return _request('utilities', 'GET', f'/transactions/{transaction_id}')

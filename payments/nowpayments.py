"""
NOWPayments crypto deposit integration.

Flow: create a hosted invoice → redirect the user to NOWPayments' checkout →
they pay in crypto → NOWPayments calls our IPN webhook → we verify the HMAC
signature and credit the naira wallet (via payments.views.credit_wallet_once).
"""
import hashlib
import hmac
import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger('payments')

# Popular coins we advertise (the actual list shown at checkout is controlled by
# which coins are enabled in the NOWPayments dashboard → Settings → Coins).
POPULAR_COINS = ['btc', 'eth', 'usdttrc20', 'usdtbsc', 'usdc', 'bnbbsc', 'ltc', 'trx']


def base_url():
    return ('https://api-sandbox.nowpayments.io/v1'
            if settings.NOWPAYMENTS_SANDBOX else 'https://api.nowpayments.io/v1')


def _headers():
    return {'x-api-key': settings.NOWPAYMENTS_API_KEY, 'Content-Type': 'application/json'}


def api_status():
    """Health check — returns {'message': 'OK'} when the API key/base are valid."""
    try:
        r = requests.get(f'{base_url()}/status', headers=_headers(), timeout=15)
        return r.json()
    except Exception as e:
        return {'error': str(e)}


def create_invoice(price_amount, order_id, order_description, *,
                   price_currency='usd', ipn_callback_url='', success_url='', cancel_url=''):
    """
    Create a hosted invoice. Returns {'id', 'invoice_url', ...} or {'error': ...}.
    price_amount is in price_currency (we price crypto deposits in USD).
    """
    body = {
        'price_amount': round(float(price_amount), 2),
        'price_currency': price_currency,
        'order_id': order_id,
        'order_description': order_description,
        'is_fixed_rate': True,
        'is_fee_paid_by_user': True,
    }
    if ipn_callback_url:
        body['ipn_callback_url'] = ipn_callback_url
    if success_url:
        body['success_url'] = success_url
    if cancel_url:
        body['cancel_url'] = cancel_url
    try:
        r = requests.post(f'{base_url()}/invoice', headers=_headers(), json=body, timeout=25)
        data = r.json()
        if r.status_code >= 400:
            logger.warning('[NOWPayments] invoice error %s: %s', r.status_code, data)
            return {'error': data.get('message', 'Could not create crypto invoice')}
        return data
    except Exception as e:
        logger.exception('[NOWPayments] create_invoice failed')
        return {'error': str(e)}


def payment_status(payment_id):
    try:
        r = requests.get(f'{base_url()}/payment/{payment_id}', headers=_headers(), timeout=15)
        return r.json()
    except Exception as e:
        return {'error': str(e)}


def verify_ipn(raw_body: bytes, signature: str) -> bool:
    """
    Verify a NOWPayments IPN callback. They HMAC-SHA512 the JSON payload sorted
    by keys, using the IPN secret. Compare in constant time.
    """
    secret = settings.NOWPAYMENTS_IPN_SECRET
    if not secret or not signature:
        return False
    try:
        data = json.loads(raw_body)
    except (ValueError, TypeError):
        return False
    sorted_payload = json.dumps(data, sort_keys=True, separators=(',', ':'))
    computed = hmac.new(secret.encode('utf-8'), sorted_payload.encode('utf-8'),
                        hashlib.sha512).hexdigest()
    return hmac.compare_digest(computed, signature)

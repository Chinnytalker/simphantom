import requests
from django.conf import settings
from .config import pack_naira_price

# Twilio cost per SMS (adjust to your Twilio rate for your destination country)
SMS_COST_PER_CREDIT_USD = 0.0079   # default: US domestic rate

# Twilio Lookup API v2 cost per lookup (standard Twilio rate)
LOOKUP_COST_PER_CREDIT_USD = 0.01


def _sms_price(credits):
    return int(pack_naira_price(SMS_COST_PER_CREDIT_USD * credits))


def _lookup_price(credits):
    return int(pack_naira_price(LOOKUP_COST_PER_CREDIT_USD * credits))


LOOKUP_PLANS = [
    {'id': 'lookup_10',   'credits': 10,   'price_ngn': _lookup_price(10),   'badge': None,         'description': 'Quick spot-checks'},
    {'id': 'lookup_50',   'credits': 50,   'price_ngn': _lookup_price(50),   'badge': None,         'description': 'Regular verification needs'},
    {'id': 'lookup_100',  'credits': 100,  'price_ngn': _lookup_price(100),  'badge': 'Popular',    'description': 'Great for small businesses'},
    {'id': 'lookup_500',  'credits': 500,  'price_ngn': _lookup_price(500),  'badge': None,         'description': 'High-volume validation'},
    {'id': 'lookup_1000', 'credits': 1000, 'price_ngn': _lookup_price(1000), 'badge': 'Best Value', 'description': 'Maximum savings per lookup'},
]

LOOKUP_PLAN_MAP = {p['id']: p for p in LOOKUP_PLANS}

SMS_PLANS = [
    {'id': 'sms_100',   'credits': 100,   'price_ngn': _sms_price(100),   'badge': None,         'description': 'Great for small campaigns'},
    {'id': 'sms_500',   'credits': 500,   'price_ngn': _sms_price(500),   'badge': None,         'description': 'Growing your reach'},
    {'id': 'sms_1000',  'credits': 1000,  'price_ngn': _sms_price(1000),  'badge': 'Popular',    'description': 'Most chosen by marketers'},
    {'id': 'sms_5000',  'credits': 5000,  'price_ngn': _sms_price(5000),  'badge': None,         'description': 'Scale your outreach'},
    {'id': 'sms_10000', 'credits': 10000, 'price_ngn': _sms_price(10000), 'badge': 'Best Value', 'description': 'Maximum reach, minimum cost'},
]

SMS_PLAN_MAP = {p['id']: p for p in SMS_PLANS}


def lookup_phone(phone_number):
    """
    Lookup a phone number via Twilio Lookup API v2.
    Returns a dict with carrier, line type, country, etc., or {'error': '...'}.
    """
    sid   = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')

    if not sid or not token:
        return {'error': 'Lookup service not configured.'}

    from urllib.parse import quote
    url = f'https://lookups.twilio.com/v2/PhoneNumbers/{quote(phone_number)}?Fields=line_type_intelligence'
    try:
        resp = requests.get(url, auth=(sid, token), timeout=10)
        data = resp.json()
        if resp.status_code != 200:
            return {'error': data.get('message', 'Lookup failed.')}

        lti = data.get('line_type_intelligence') or {}
        return {
            'phone_number':   data.get('phone_number', phone_number),
            'national_format': data.get('national_format', ''),
            'country_code':   data.get('country_code', ''),
            'calling_code':   data.get('calling_country_code', ''),
            'valid':          data.get('valid', False),
            'line_type':      lti.get('type', 'unknown'),
            'carrier':        lti.get('carrier_name', 'Unknown'),
            'mobile_country_code': lti.get('mobile_country_code', ''),
            'mobile_network_code': lti.get('mobile_network_code', ''),
        }
    except Exception as e:
        return {'error': str(e)}


def send_sms(to_number, message_body):
    """
    Send a single SMS via Twilio.
    Returns {'success': True, 'sid': '...'} or {'success': False, 'error': '...'}.
    """
    sid   = getattr(settings, 'TWILIO_ACCOUNT_SID', '')
    token = getattr(settings, 'TWILIO_AUTH_TOKEN', '')
    from_ = getattr(settings, 'TWILIO_FROM_NUMBER', '')

    if not sid or not token or not from_:
        return {'success': False, 'error': 'SMS service not configured.'}

    url = f'https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json'
    try:
        resp = requests.post(
            url,
            auth=(sid, token),
            data={'From': from_, 'To': to_number, 'Body': message_body},
            timeout=15,
        )
        data = resp.json()
        if resp.status_code in (200, 201):
            return {'success': True, 'sid': data.get('sid', '')}
        return {'success': False, 'error': data.get('message', 'Twilio error')}
    except Exception as e:
        return {'success': False, 'error': str(e)}

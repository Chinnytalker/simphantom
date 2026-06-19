import random
import string
from django.conf import settings
from .config import pack_naira_price

# ── Cost per GB from BrightData (set to your actual reseller/partner rate) ────
# BrightData list price is ~$8.40/GB. Partners typically get 30–50% off.
# Update this to your negotiated rate once you have your BrightData account.
PROXY_COST_PER_GB_USD = 8.40


def _proxy_price(gb):
    return int(pack_naira_price(PROXY_COST_PER_GB_USD * gb))


# ── Plans ──────────────────────────────────────────────────────────────────────
PROXY_PLANS = [
    {
        'id': 'starter',
        'name': 'Starter',
        'gb': 1,
        'price_ngn': _proxy_price(1),
        'description': 'Perfect for light use & testing',
        'badge': None,
    },
    {
        'id': 'basic',
        'name': 'Basic',
        'gb': 3,
        'price_ngn': _proxy_price(3),
        'description': 'Small projects & research',
        'badge': None,
    },
    {
        'id': 'standard',
        'name': 'Standard',
        'gb': 5,
        'price_ngn': _proxy_price(5),
        'description': 'Everyday scraping & automation',
        'badge': 'Popular',
    },
    {
        'id': 'pro',
        'name': 'Pro',
        'gb': 10,
        'price_ngn': _proxy_price(10),
        'description': 'Heavy-duty data collection',
        'badge': None,
    },
    {
        'id': 'business',
        'name': 'Business',
        'gb': 25,
        'price_ngn': _proxy_price(25),
        'description': 'Teams & commercial projects',
        'badge': 'Best Value',
    },
    {
        'id': 'enterprise',
        'name': 'Enterprise',
        'gb': 50,
        'price_ngn': _proxy_price(50),
        'description': 'Large-scale enterprise usage',
        'badge': None,
    },
]

PLAN_MAP = {p['id']: p for p in PROXY_PLANS}


def _session_id():
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=12))


def is_configured():
    """Return True when both customer ID and zone password are set."""
    return bool(
        getattr(settings, 'BRIGHTDATA_CUSTOMER_ID', '') and
        getattr(settings, 'BRIGHTDATA_ZONE_PASS', '')
    )


def create_session_credentials(zone_name=None):
    """
    Generate session-based proxy credentials instantly — no API call needed.
    Bright Data routes any username formatted as:
      brd-customer-{customer_id}-zone-{zone}-session-{session_id}
    through the zone automatically.
    """
    customer_id = getattr(settings, 'BRIGHTDATA_CUSTOMER_ID', '')
    zone        = zone_name or getattr(settings, 'BRIGHTDATA_ZONE_NAME', 'SimPhantom_res')
    zone_pass   = getattr(settings, 'BRIGHTDATA_ZONE_PASS', '')

    if not customer_id or not zone_pass:
        return {
            'provisioned': False,
            'error': 'Proxy service not fully configured yet.',
        }

    session = _session_id()
    username = f'brd-customer-{customer_id}-zone-{zone}-session-{session}'

    return {
        'provisioned': True,
        'host': 'brd.superproxy.io',
        'port': 22225,
        'port_https': 22226,
        'port_socks5': 33335,
        'username': username,
        'password': zone_pass,
        'zone': zone,
        'session': session,
    }


def build_proxy_string(creds):
    """Return ready-to-use HTTP proxy URL."""
    return f"http://{creds['username']}:{creds['password']}@brd.superproxy.io:22225"

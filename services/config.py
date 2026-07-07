_FX_FALLBACK = 1650.0
_FX_CACHE_KEY = 'usd_to_ngn_rate'
_FX_TTL = 6 * 3600  # refresh at most every 6 hours


def _fetch_usd_to_ngn():
    """Fetch live USD→NGN rate. Falls back to hardcoded rate on any error."""
    try:
        import requests
        r = requests.get(
            'https://open.er-api.com/v6/latest/USD',
            timeout=4
        )
        rate = float(r.json()['rates']['NGN'])
        if rate > 0:
            return rate
    except Exception:
        pass
    return _FX_FALLBACK


def get_usd_to_ngn():
    """
    Current USD→NGN rate, cached in the shared Django cache with a TTL so the
    rate actually refreshes while the app runs (instead of being frozen at
    process import). All workers share one value when Redis is configured.
    """
    from django.core.cache import cache
    rate = cache.get(_FX_CACHE_KEY)
    if rate is None:
        rate = _fetch_usd_to_ngn()
        cache.set(_FX_CACHE_KEY, rate, _FX_TTL)
    return rate


def __getattr__(name):
    # Backwards compatibility: `from services.config import USD_TO_NGN` and
    # `config.USD_TO_NGN` still work, now resolving to the live cached rate.
    if name == 'USD_TO_NGN':
        return get_usd_to_ngn()
    raise AttributeError(f'module {__name__!r} has no attribute {name!r}')

# Flat markup for 5sim (OTP / virtual numbers — costs are tiny, flat works well)
FLAT_MARKUP_NGN = 1500  # flat ₦1500 profit on every virtual number sale
OTP_MARKUP_NGN  = 1700  # flat ₦1700 profit on every OTP verification sale

# ── Reloadly percentage markups (tune here) ───────────────────────────────────
AIRTIME_MARKUP_PCT = 0.15   # 15% on INTERNATIONAL airtime/data (UK, USA, etc.)
GIFTCARD_MARKUP_PCT = 0.10  # 10% on gift cards (on top of Reloadly's discount)
UTILITY_MARKUP_PCT = 0.07   # 7% on utility bills

# Airtime/data top-ups TO these countries are sold at EXACT FACE VALUE — the
# customer pays the same amount they're topping up (e.g. ₦100 airtime = ₦100).
# We absorb any provider FX difference to stay competitive at home, and take our
# margin on international top-ups instead.
AIRTIME_HOME_COUNTRIES = {'NG'}


def _reloadly_naira(cost_usd: float, pct: float) -> float:
    """USD cost → NGN price with a percentage markup, rounded to whole naira."""
    return round(cost_usd * get_usd_to_ngn() * (1 + pct), 0)


def airtime_naira_price(cost_usd: float) -> float:
    """NGN price for an INTERNATIONAL airtime/data top-up (our cost + markup).
    Home-country top-ups are priced at face value directly in the view."""
    return _reloadly_naira(cost_usd, AIRTIME_MARKUP_PCT)


def giftcard_naira_price(cost_usd: float) -> float:
    return _reloadly_naira(cost_usd, GIFTCARD_MARKUP_PCT)


def utility_naira_price(cost_usd: float) -> float:
    return _reloadly_naira(cost_usd, UTILITY_MARKUP_PCT)


def pack_naira_price(cost_usd: float) -> float:
    """
    Tiered markup for fixed credit packs (SMS, Lookup, Proxy).
    Bigger packs get a lower % so bulk buyers still see value.
    """
    cost_ngn = cost_usd * USD_TO_NGN
    if cost_usd <= 1:
        pct = 0.70
    elif cost_usd <= 5:
        pct = 0.55
    elif cost_usd <= 15:
        pct = 0.45
    elif cost_usd <= 50:
        pct = 0.35
    else:
        pct = 0.25
    return round(cost_ngn * (1 + pct), 2)


def esim_naira_price(price_usd: float) -> float:
    """
    Tiered percentage markup for eSIM packages.
    Cheaper packages get a higher % so you still profit.
    Expensive packages get a lower % so prices stay competitive.
    """
    cost_ngn = price_usd * USD_TO_NGN
    if price_usd <= 5:
        pct = 0.40      # 40% on cheap plans
    elif price_usd <= 15:
        pct = 0.30      # 30% on mid-range
    elif price_usd <= 30:
        pct = 0.25      # 25% on larger plans
    else:
        pct = 0.20      # 20% on premium plans
    return round(cost_ngn * (1 + pct), 2)

# Service catalog with pricing and details
SERVICES = {
    'virtual-numbers': {
        'name': 'Virtual Numbers',
        'icon': '📱',
        'description': 'Get instant access to virtual phone numbers from 190+ countries',
        'service_type': 'VIRTUAL_NUMBER',
        'popular': True,
    },
    'otp-verification': {
        'name': 'OTP Verification',
        'icon': '🔐',
        'description': 'Receive one-time passwords for account verification',
        'service_type': 'OTP_VERIFICATION',
        'popular': True,
    },
    'temporary-email': {
        'name': 'Temporary Email',
        'icon': '📧',
        'description': 'Disposable email addresses for privacy',
        'service_type': 'TEMPORARY_EMAIL',
        'popular': False,
    },
    'vpn-subscription': {
        'name': 'VPN Subscription',
        'icon': '🛡️',
        'description': 'Secure your internet connection with enterprise-grade encryption',
        'service_type': 'VPN',
        'popular': True,
    },
    'esim-packages': {
        'name': 'eSIM Packages',
        'icon': '💳',
        'description': 'Digital SIM cards for global connectivity',
        'service_type': 'ESIM',
        'popular': False,
    },
    'residential-proxies': {
        'name': 'Residential Proxies',
        'icon': '🌍',
        'description': 'Real residential IP addresses for web scraping and automation',
        'service_type': 'RESIDENTIAL_PROXY',
        'popular': True,
    },
    'bulk-sms': {
        'name': 'Bulk SMS',
        'icon': '💬',
        'description': 'Send SMS messages in bulk to multiple recipients',
        'service_type': 'BULK_SMS',
        'popular': False,
    },
    'phone-number-lookup': {
        'name': 'Phone Number Lookup',
        'icon': '🔍',
        'description': 'Get detailed information about phone numbers',
        'service_type': 'PHONE_LOOKUP',
        'popular': False,
    },
    'airtime': {
        'name': 'Airtime & Data',
        'icon': '📶',
        'description': 'Top up airtime and data to any phone in 140+ countries',
        'service_type': 'AIRTIME',
        'popular': True,
    },
    'gift-cards': {
        'name': 'Gift Cards',
        'icon': '🎁',
        'description': 'Buy Amazon, Google Play, Steam and hundreds more gift cards',
        'service_type': 'GIFT_CARD',
        'popular': True,
    },
    'utility-bills': {
        'name': 'Utility Bills',
        'icon': '💡',
        'description': 'Pay electricity, water, TV and internet bills',
        'service_type': 'UTILITY',
        'popular': False,
    },
}

VPN_PLANS = {
    '1m-us': {'name': '1 Month — USA',    'duration_days': 30,  'location': 'us', 'price_ngn': 2500},
    '3m-us': {'name': '3 Months — USA',   'duration_days': 90,  'location': 'us', 'price_ngn': 6500},
    '6m-us': {'name': '6 Months — USA',   'duration_days': 180, 'location': 'us', 'price_ngn': 11000},
    '1y-us': {'name': '1 Year — USA',     'duration_days': 365, 'location': 'us', 'price_ngn': 18000},
    '1m-uk': {'name': '1 Month — UK',     'duration_days': 30,  'location': 'uk', 'price_ngn': 2500},
    '3m-uk': {'name': '3 Months — UK',    'duration_days': 90,  'location': 'uk', 'price_ngn': 6500},
    '6m-uk': {'name': '6 Months — UK',    'duration_days': 180, 'location': 'uk', 'price_ngn': 11000},
    '1y-uk': {'name': '1 Year — UK',      'duration_days': 365, 'location': 'uk', 'price_ngn': 18000},
}
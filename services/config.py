def _fetch_usd_to_ngn():
    """Fetch live USD→NGN rate. Falls back to hardcoded rate on any error."""
    try:
        import requests
        r = requests.get(
            'https://open.er-api.com/v6/latest/USD',
            timeout=4
        )
        rate = r.json()['rates']['NGN']
        return float(rate)
    except Exception:
        return 1650.0

USD_TO_NGN = _fetch_usd_to_ngn()

# Flat markup for 5sim (OTP / virtual numbers — costs are tiny, flat works well)
FLAT_MARKUP_NGN = 1500  # flat ₦1500 profit on every virtual number sale
OTP_MARKUP_NGN  = 1700  # flat ₦1700 profit on every OTP verification sale


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
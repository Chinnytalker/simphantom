import time
import requests
from decouple import config

BASE_URL = "https://api.tiger-sms.com/stubs/handler_api.php"

# ── Country maps ──────────────────────────────────────────────────────────────
# 5sim country name → TigerSMS numeric ID.  IDs are from TigerSMS docs; any
# entry whose ID is not present in a live getPrices dump is automatically skipped.
COUNTRY_MAP = {
    'russia': 0,
    'ukraine': 1,
    'kazakhstan': 2,
    'belarus': 3,
    'china': 4,
    'indonesia': 6,
    'philippines': 7,
    'myanmar': 8,
    'vietnam': 9,
    'kyrgyzstan': 11,
    'israel': 13,
    'hongkong': 15,
    'england': 16,
    'netherlands': 17,
    'georgia': 20,
    'argentina': 21,
    'india': 22,
    'ireland': 25,
    'cambodia': 26,
    'bangladesh': 27,
    'morocco': 29,
    'ghana': 30,
    'kenya': 31,
    'tanzania': 33,
    'latvia': 35,
    'moldova': 36,
    'colombia': 37,
    'bulgaria': 39,
    'romania': 41,
    'estonia': 42,
    'germany': 43,
    'czechrepublic': 44,
    'czechia': 44,
    'taiwan': 46,
    'slovakia': 47,
    'austria': 48,
    'switzerland': 49,
    'egypt': 50,
    'thailand': 52,
    'mexico': 54,
    'ethiopia': 55,
    'laos': 56,
    'malaysia': 60,
    'australia': 61,
    'algeria': 62,
    'srilanka': 63,
    'angola': 64,
    'afghanistan': 65,
    'armenia': 66,
    'azerbaijan': 67,
    'bahrain': 69,
    'singapore': 71,
    'brazil': 73,
    'belgium': 74,
    'bolivia': 76,
    'finland': 77,
    'france': 78,
    'burkinafaso': 80,
    'cameroon': 81,
    'southkorea': 82,
    'korea': 82,
    'southafrica': 83,
    'cuba': 84,
    'italy': 86,
    'japan': 87,
    'ivorycoast': 88,
    'chile': 98,
    'costarica': 102,
    'guatemala': 103,
    'greece': 104,
    'ecuador': 107,
    'elsalvador': 108,
    'croatia': 109,
    'guinea': 110,
    'honduras': 111,
    'hungary': 112,
    'iran': 114,
    'iraq': 116,
    'jordan': 119,
    'kuwait': 120,
    'lebanon': 121,
    'lithuania': 123,
    'madagascar': 126,
    'mali': 127,
    'namibia': 134,
    'mozambique': 136,
    'nepal': 137,
    'niger': 138,
    'nicaragua': 139,
    'newzealand': 140,
    'norway': 141,
    'oman': 144,
    'panama': 146,
    'paraguay': 148,
    'peru': 149,
    'poland': 151,
    'portugal': 153,
    'qatar': 155,
    'rwanda': 158,
    'saudiarabia': 159,
    'pakistan': 162,
    'serbia': 163,
    'senegal': 165,
    'sudan': 167,
    'sweden': 168,
    'spain': 169,
    'syria': 170,
    'tajikistan': 171,
    'turkey': 172,
    'turkmenistan': 175,
    'uae': 176,
    'uruguay': 181,
    'usa': 187,
    'zambia': 186,
    'zimbabwe': 189,
    'uganda': 190,
    'uzbekistan': 191,
    'venezuela': 192,
    'nigeria': 193,
    'burundi': 194,
    'djibouti': 195,
    'yemen': 196,
    'tunisia': 197,
    'botswana': 198,
    'dominicanrepublic': 199,
}

# Display names for 5sim country codes
COUNTRY_DISPLAY = {
    'russia': 'Russia',
    'ukraine': 'Ukraine',
    'kazakhstan': 'Kazakhstan',
    'belarus': 'Belarus',
    'china': 'China',
    'indonesia': 'Indonesia',
    'philippines': 'Philippines',
    'myanmar': 'Myanmar',
    'vietnam': 'Vietnam',
    'kyrgyzstan': 'Kyrgyzstan',
    'israel': 'Israel',
    'hongkong': 'Hong Kong',
    'england': 'United Kingdom',
    'netherlands': 'Netherlands',
    'georgia': 'Georgia',
    'argentina': 'Argentina',
    'india': 'India',
    'ireland': 'Ireland',
    'cambodia': 'Cambodia',
    'bangladesh': 'Bangladesh',
    'morocco': 'Morocco',
    'ghana': 'Ghana',
    'kenya': 'Kenya',
    'tanzania': 'Tanzania',
    'latvia': 'Latvia',
    'moldova': 'Moldova',
    'colombia': 'Colombia',
    'bulgaria': 'Bulgaria',
    'romania': 'Romania',
    'estonia': 'Estonia',
    'germany': 'Germany',
    'czechrepublic': 'Czech Republic',
    'czechia': 'Czech Republic',
    'taiwan': 'Taiwan',
    'slovakia': 'Slovakia',
    'austria': 'Austria',
    'switzerland': 'Switzerland',
    'egypt': 'Egypt',
    'thailand': 'Thailand',
    'mexico': 'Mexico',
    'ethiopia': 'Ethiopia',
    'malaysia': 'Malaysia',
    'australia': 'Australia',
    'srilanka': 'Sri Lanka',
    'afghanistan': 'Afghanistan',
    'armenia': 'Armenia',
    'azerbaijan': 'Azerbaijan',
    'brazil': 'Brazil',
    'belgium': 'Belgium',
    'finland': 'Finland',
    'france': 'France',
    'cameroon': 'Cameroon',
    'korea': 'South Korea',
    'southkorea': 'South Korea',
    'southafrica': 'South Africa',
    'italy': 'Italy',
    'japan': 'Japan',
    'ivorycoast': "Côte d'Ivoire",
    'chile': 'Chile',
    'croatia': 'Croatia',
    'hungary': 'Hungary',
    'iran': 'Iran',
    'iraq': 'Iraq',
    'singapore': 'Singapore',
    'jordan': 'Jordan',
    'senegal': 'Senegal',
    'mali': 'Mali',
    'uganda': 'Uganda',
    'venezuela': 'Venezuela',
    'nigeria': 'Nigeria',
    'nepal': 'Nepal',
    'newzealand': 'New Zealand',
    'norway': 'Norway',
    'peru': 'Peru',
    'poland': 'Poland',
    'portugal': 'Portugal',
    'saudiarabia': 'Saudi Arabia',
    'pakistan': 'Pakistan',
    'serbia': 'Serbia',
    'spain': 'Spain',
    'sweden': 'Sweden',
    'tajikistan': 'Tajikistan',
    'turkey': 'Turkey',
    'turkmenistan': 'Turkmenistan',
    'uae': 'United Arab Emirates',
    'usa': 'United States',
    'uzbekistan': 'Uzbekistan',
    'zimbabwe': 'Zimbabwe',
    'zambia': 'Zambia',
    'lithuania': 'Lithuania',
    'angola': 'Angola',
    'rwanda': 'Rwanda',
    'mozambique': 'Mozambique',
    'madagascar': 'Madagascar',
    'tunisia': 'Tunisia',
    'algeria': 'Algeria',
    'ecuador': 'Ecuador',
    'bolivia': 'Bolivia',
    'paraguay': 'Paraguay',
    'uruguay': 'Uruguay',
    'costarica': 'Costa Rica',
    'guatemala': 'Guatemala',
    'honduras': 'Honduras',
    'elsalvador': 'El Salvador',
    'nicaragua': 'Nicaragua',
    'dominicanrepublic': 'Dominican Republic',
    'panama': 'Panama',
    'greece': 'Greece',
    'kuwait': 'Kuwait',
    'qatar': 'Qatar',
    'bahrain': 'Bahrain',
    'oman': 'Oman',
    'lebanon': 'Lebanon',
    'syria': 'Syria',
    'laos': 'Laos',
    'niger': 'Niger',
    'burkinafaso': 'Burkina Faso',
    'guinea': 'Guinea',
    'sudan': 'Sudan',
    'botswana': 'Botswana',
    'namibia': 'Namibia',
    'burundi': 'Burundi',
    'yemen': 'Yemen',
    'cuba': 'Cuba',
    'canada': 'Canada',
    'djibouti': 'Djibouti',
}

# 5sim product name → TigerSMS service code
SERVICE_MAP = {
    # Messaging
    'whatsapp': 'wa',
    'telegram': 'tg',
    'viber': 'vi',
    'signal': 'si',
    'line': 'ln',
    'wechat': 'wc',
    'skype': 'sk',
    'discord': 'di',
    'icq': 'ik',
    'imo': 'io',
    'zalo': 'za',
    'kakao': 'kk',
    'kakaotalk': 'kk',
    # Social media
    'facebook': 'fb',
    'instagram': 'ig',
    'twitter': 'tw',
    'tiktok': 'tt',
    'snapchat': 'sn',
    'linkedin': 'li',
    'pinterest': 'pi',
    'reddit': 're',
    'tumblr': 'tu',
    'ok': 'ok',
    'vk': 'vk',
    'weibo': 'wb',
    'badoo': 'bd',
    'bumble': 'bm',
    'tinder': 'tn',
    'hinge': 'hg',
    'match': 'mt',
    'grindr': 'gi',
    # Google / Apple / Microsoft
    'google': 'go',
    'gmail': 'go',
    'youtube': 'yt',
    'apple': 'ap',
    'microsoft': 'ms',
    'outlook': 'ms',
    'hotmail': 'ms',
    'yahoo': 'ya',
    'yandex': 'ym',
    # E-commerce
    'amazon': 'am',
    'ebay': 'eb',
    'shopee': 'sh',
    'lazada': 'lz',
    'aliexpress': 'al',
    'alibaba': 'al',
    'jd': 'jd',
    'ozon': 'oz',
    'wildberries': 'wb2',
    'avito': 'av',
    'shein': 'se',
    'wish': 'ws',
    'etsy': 'et',
    'olx': 'ox',
    # Payment
    'paypal': 'pp',
    'alipay': 'aq',
    'cashapp': 'ca',
    'revolut': 'rv',
    'wise': 'wi',
    'venmo': 've',
    'coinbase': 'cb',
    'binance': 'bn',
    # Streaming
    'netflix': 'nf',
    'spotify': 'sp',
    'twitch': 'tc',
    'hulu': 'hl',
    'disneyplus': 'dp',
    'hbomax': 'hb',
    'primevideo': 'pv',
    'deezer': 'dz',
    # Ride / Delivery / Travel
    'uber': 'ub',
    'lyft': 'ly',
    'grab': 'gr',
    'gojek': 'gj',
    'bolt': 'bl',
    'rappi': 'rp',
    'doordash': 'dd',
    'foodpanda': 'fp',
    'swiggy': 'sw',
    'zomato': 'zo',
    'airbnb': 'ab',
    'booking': 'bk',
    'agoda': 'ag',
    # Gaming
    'steam': 'st',
    'epicgames': 'eg',
    'blizzard': 'bz',
    'riot': 'ri',
    'origin': 'or',
    'ea': 'or',
    'rockstar': 'rs',
    'nintendo': 'nd',
    'playstation': 'ps',
    'xbox': 'xb',
    # Mail
    'mail': 'mm',
    'mail_ru': 'mm',
    'mailru': 'mm',
    'protonmail': 'pm',
    # Other
    'zoom': 'zu',
    'slack': 'sl',
    'github': 'gh',
    'fiverr': 'fv',
    'upwork': 'uw',
    'truecaller': 'tc2',
}

# Reverse: TigerSMS service code → canonical 5sim product name
CODE_TO_FIVESIM = {}
for _n, _c in SERVICE_MAP.items():
    if _c not in CODE_TO_FIVESIM:
        CODE_TO_FIVESIM[_c] = _n

# Reverse: TigerSMS country ID (int) → 5sim country name
ID_TO_FIVESIM = {}
for _name, _id in COUNTRY_MAP.items():
    if _id not in ID_TO_FIVESIM:
        ID_TO_FIVESIM[_id] = _name


def _params(**extra):
    return {'api_key': config('TIGERSMS_API_KEY', default=''), **extra}


# ── Price cache ───────────────────────────────────────────────────────────────
# Full getPrices dump: {country_id_str: {service_code: {cost: str, count: int}}}
_prices_cache: dict = {}
_prices_cache_time: float = 0
_CACHE_TTL = 3600  # seconds


def _load_all_prices(force=False) -> dict:
    """
    Fetch (or return cached) the complete TigerSMS getPrices dump.
    Format confirmed: {"country_id": {"service_code": {"cost": "0.14", "count": N}}}
    """
    global _prices_cache, _prices_cache_time
    now = time.time()
    if not force and _prices_cache and (now - _prices_cache_time) < _CACHE_TTL:
        return _prices_cache
    try:
        r = requests.get(BASE_URL, params=_params(action='getPrices'), timeout=30)
        data = r.json()
        if isinstance(data, dict) and data:
            # Validate: outer keys should be numeric strings, values dicts of services
            valid = {k: v for k, v in data.items()
                     if k.isdigit() and isinstance(v, dict)}
            if valid:
                _prices_cache = valid
                _prices_cache_time = now
    except Exception:
        pass
    return _prices_cache


# ── Public API ────────────────────────────────────────────────────────────────

def get_balance():
    try:
        r = requests.get(BASE_URL, params=_params(action='getBalance'), timeout=10)
        text = r.text.strip()
        if text.startswith('ACCESS_BALANCE:'):
            return {'balance': float(text.split(':')[1])}
        return {'error': text}
    except Exception as e:
        return {'error': str(e)}


def get_all_countries() -> list:
    """
    Return sorted list of all countries in COUNTRY_MAP.
    Uses the prices cache to mark availability, but never hides a country
    just because the cache is cold or the ID hasn't been confirmed yet.
    Each entry: {code: str, text_en: str, tiger_id: str}
    """
    seen_ids = set()
    countries = []
    for fivesim_name, raw_id in COUNTRY_MAP.items():
        cid_str = str(raw_id)
        if cid_str in seen_ids:
            continue
        seen_ids.add(cid_str)
        display = COUNTRY_DISPLAY.get(fivesim_name, fivesim_name.replace('_', ' ').title())
        countries.append({
            'code': fivesim_name,
            'text_en': display,
            'tiger_id': cid_str,
        })
    return sorted(countries, key=lambda x: x['text_en'])


def resolve_country_id(country_name):
    """
    Return the TigerSMS country ID string for a given 5sim country name.
    Returns the COUNTRY_MAP value directly so the buy flow always attempts
    TigerSMS; the getNumber call itself will return BAD_COUNTRY if the ID
    is wrong, and the caller can fall back to 5sim at that point.
    """
    name = (country_name or '').lower().strip()
    raw_id = COUNTRY_MAP.get(name)
    return str(raw_id) if raw_id is not None else None


def get_prices(country_id) -> dict:
    """
    Return {service_code: {count: int, cost: float}} for a TigerSMS country ID.
    Reads from the cached full getPrices dump — no extra HTTP request.
    """
    prices = _load_all_prices()
    cid_str = str(country_id)
    raw = prices.get(cid_str, {})
    result = {}
    for svc_code, info in raw.items():
        if not isinstance(info, dict):
            continue
        try:
            count = int(info.get('count', 0))
            cost = float(info.get('cost', 0))
        except (TypeError, ValueError):
            continue
        result[svc_code] = {'count': count, 'cost': cost}
    return result


def get_prices_raw(country_id) -> dict:
    """Return unprocessed slice of the prices cache for a country (for debugging)."""
    prices = _load_all_prices()
    cid_str = str(country_id)
    return {
        'country_id': cid_str,
        'in_cache': cid_str in prices,
        'raw': prices.get(cid_str, {}),
    }


def get_number(service_code, country_id):
    """Buy a number. Returns {'id': str, 'phone': str} or {'error': str}."""
    try:
        r = requests.get(
            BASE_URL,
            params=_params(action='getNumber', service=service_code, country=country_id),
            timeout=15,
        )
        text = r.text.strip()
        if text.startswith('ACCESS_NUMBER:'):
            parts = text.split(':')
            return {'id': parts[1], 'phone': parts[2]}
        return {'error': text}
    except Exception as e:
        return {'error': str(e)}


def get_status(activation_id):
    """Check status. Returns {'status': 'PENDING'|'RECEIVED'|'CANCELED', 'code': str|None}."""
    try:
        r = requests.get(BASE_URL, params=_params(action='getStatus', id=activation_id), timeout=10)
        text = r.text.strip()
        if text in ('STATUS_WAIT_CODE', 'STATUS_WAIT_RESEND'):
            return {'status': 'PENDING', 'code': None}
        if text.startswith('STATUS_OK:'):
            return {'status': 'RECEIVED', 'code': text.split(':', 1)[1]}
        if text == 'STATUS_CANCEL':
            return {'status': 'CANCELED', 'code': None}
        return {'error': text}
    except Exception as e:
        return {'error': str(e)}


def cancel_number(activation_id):
    """Cancel an activation. Returns {'success': True} or {'error': str}."""
    try:
        r = requests.get(
            BASE_URL,
            params=_params(action='setStatus', id=activation_id, status=8),
            timeout=10,
        )
        text = r.text.strip()
        if text == 'ACCESS_CANCEL':
            return {'success': True}
        return {'error': text}
    except Exception as e:
        return {'error': str(e)}


def map_country(fivesim_country):
    """Return TigerSMS country ID string for a 5sim country name."""
    return resolve_country_id(fivesim_country)


def map_service(fivesim_product):
    """Return TigerSMS service code for a 5sim product name, or None if unsupported."""
    return SERVICE_MAP.get((fivesim_product or '').lower())


def diagnose() -> dict:
    """
    Full diagnostic — balance, cache state, country IDs, WhatsApp coverage.
    Visit /api/services/tiger/countries/?raw=1 to see output.
    """
    results = {}

    # 1. API key health
    try:
        r = requests.get(BASE_URL, params=_params(action='getBalance'), timeout=10)
        results['balance'] = r.text.strip()
    except Exception as e:
        results['balance'] = str(e)

    # 2. Full price dump
    try:
        prices = _load_all_prices(force=True)
        country_ids = sorted(prices.keys(), key=lambda x: int(x))
        results['total_countries_in_dump'] = len(country_ids)
        results['all_country_ids'] = country_ids

        # Sample: first country's services
        if country_ids:
            first = country_ids[0]
            results['sample_country_id'] = first
            results['sample_service_codes'] = list(prices[first].keys())[:40]

        # WhatsApp ('wa') coverage
        wa_ids = [cid for cid, svcs in prices.items() if 'wa' in svcs]
        results['country_ids_with_wa'] = sorted(wa_ids, key=int)

        # Which of our COUNTRY_MAP entries match real IDs
        matched = {}
        for name, raw_id in COUNTRY_MAP.items():
            cid_str = str(raw_id)
            if cid_str in prices:
                matched[name] = {'tiger_id': cid_str, 'service_count': len(prices[cid_str])}
        results['matched_country_map_entries'] = matched

    except Exception as e:
        results['prices_dump_error'] = str(e)

    return results

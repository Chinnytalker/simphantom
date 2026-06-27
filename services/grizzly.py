import time
import requests
from decouple import config
from .tigersms import SERVICE_MAP, CODE_TO_FIVESIM, COUNTRY_DISPLAY

BASE_URL = "https://api.grizzlysms.com/stubs/handler_api.php"

# Grizzly uses its own country numeric IDs — completely different from TigerSMS.
# Mapped from Grizzly's live getCountries endpoint (June 2026).
# Russia is not available on Grizzly — orders for Russia fall back to 5sim.
COUNTRY_MAP = {
    'ukraine': 1,
    'kazakhstan': 2,
    'china': 3,
    'philippines': 4,
    'myanmar': 5,
    'indonesia': 6,
    'malaysia': 7,
    'kenya': 8,
    'tanzania': 9,
    'vietnam': 10,
    'kyrgyzstan': 11,
    'israel': 13,
    'hongkong': 14,
    'poland': 15,
    'england': 16,
    'madagascar': 17,
    'nigeria': 19,
    'egypt': 21,
    'india': 22,
    'ireland': 23,
    'cambodia': 24,
    'laos': 25,
    'ivorycoast': 27,
    'serbia': 29,
    'yemen': 30,
    'southafrica': 31,
    'romania': 32,
    'colombia': 33,
    'estonia': 34,
    'azerbaijan': 35,
    'canada': 36,
    'morocco': 37,
    'ghana': 38,
    'argentina': 39,
    'uzbekistan': 40,
    'cameroon': 41,
    'germany': 43,
    'lithuania': 44,
    'croatia': 45,
    'sweden': 46,
    'iraq': 47,
    'netherlands': 48,
    'latvia': 49,
    'austria': 50,
    'belarus': 51,
    'thailand': 52,
    'saudiarabia': 53,
    'mexico': 54,
    'taiwan': 55,
    'spain': 56,
    'algeria': 58,
    'czechrepublic': 63,
    'czechia': 63,
    'srilanka': 64,
    'peru': 65,
    'pakistan': 66,
    'newzealand': 67,
    'guinea': 68,
    'mali': 69,
    'venezuela': 70,
    'ethiopia': 71,
    'brazil': 73,
    'afghanistan': 74,
    'uganda': 75,
    'angola': 76,
    'france': 78,
    'mozambique': 80,
    'nepal': 81,
    'belgium': 82,
    'bulgaria': 83,
    'hungary': 84,
    'moldova': 85,
    'italy': 86,
    'japan': 182,
    'paraguay': 87,
    'honduras': 88,
    'tunisia': 89,
    'nicaragua': 90,
    'bolivia': 92,
    'costarica': 93,
    'guatemala': 94,
    'uae': 95,
    'zimbabwe': 96,
    'togo': 99,
    'kuwait': 100,
    'elsalvador': 101,
    'trinidadandtobago': 104,
    'ecuador': 105,
    'swaziland': 106,
    'oman': 107,
    'dominicanrepublic': 109,
    'syria': 110,
    'qatar': 111,
    'panama': 112,
    'cuba': 113,
    'jordan': 116,
    'portugal': 117,
    'burundi': 119,
    'bahrain': 145,
    'botswana': 123,
    'burkinafaso': 152,
    'greece': 129,
    'georgia': 128,
    'slovakia': 141,
    'tajikistan': 143,
    'turkmenistan': 161,
    'finland': 163,
    'djibouti': 168,
    'norway': 174,
    'australia': 175,
    'southkorea': 10350,
    'korea': 10350,
    'singapore': 10351,
    'iran': 10016,
    'switzerland': 173,
    'rwanda': 140,
    'namibia': 138,
    'niger': 139,
    'senegal': 61,
    'turkey': 62,
    'usa': 187,
    'uruguay': 156,
    'zambia': 147,
}

_prices_cache: dict = {}
_prices_cache_time: float = 0
_CACHE_TTL = 3600


def _params(**extra):
    return {'api_key': config('GRIZZLY_API_KEY', default=''), **extra}


def _load_all_prices(force=False) -> dict:
    global _prices_cache, _prices_cache_time
    now = time.time()
    if not force and _prices_cache and (now - _prices_cache_time) < _CACHE_TTL:
        return _prices_cache
    try:
        r = requests.get(BASE_URL, params=_params(action='getPrices'), timeout=30)
        data = r.json()
        if isinstance(data, dict) and data:
            valid = {k: v for k, v in data.items() if isinstance(v, dict)}
            if valid:
                _prices_cache = valid
                _prices_cache_time = now
    except Exception:
        pass
    return _prices_cache


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
    seen_ids = set()
    countries = []
    for fivesim_name, raw_id in COUNTRY_MAP.items():
        cid_str = str(raw_id)
        if cid_str in seen_ids:
            continue
        seen_ids.add(cid_str)
        display = COUNTRY_DISPLAY.get(fivesim_name, fivesim_name.replace('_', ' ').title())
        countries.append({'code': fivesim_name, 'text_en': display, 'grizzly_id': cid_str})
    return sorted(countries, key=lambda x: x['text_en'])


def resolve_country_id(country_name):
    name = (country_name or '').lower().strip()
    raw_id = COUNTRY_MAP.get(name)
    return str(raw_id) if raw_id is not None else None


def _extract_cost(info: dict) -> float:
    for key in ('cost', 'retail_price', 'rate', 'price'):
        val = info.get(key)
        if val is not None:
            try:
                return float(val)
            except (TypeError, ValueError):
                continue
    return 0.0


def _extract_count(info: dict) -> int:
    for key in ('count', 'qty', 'cnt', 'quantity'):
        val = info.get(key)
        if val is not None:
            try:
                return int(val)
            except (TypeError, ValueError):
                continue
    return 0


def get_prices(country_id) -> dict:
    prices = _load_all_prices()
    cid_str = str(country_id)
    raw = prices.get(cid_str, {})
    result = {}
    for svc_code, info in raw.items():
        if not isinstance(info, dict):
            continue
        count = _extract_count(info)
        cost = _extract_cost(info)
        if count <= 0 or cost <= 0:
            continue
        result[svc_code] = {'count': count, 'cost': cost}
    return result


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
            parts = text.split(':', 2)
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
        if text in ('STATUS_CANCEL', 'NO_ACTIVATION'):
            # NO_ACTIVATION means the order expired/was removed on Grizzly's side
            return {'status': 'CANCELED', 'code': None}
        return {'error': text}
    except Exception as e:
        return {'error': str(e)}


def cancel_number(activation_id):
    """Cancel an activation. Returns {'success': True} or {'error': str}."""
    try:
        # status=6 is the cancel code on SMS-Activate style APIs (status=8 means FINISH)
        r = requests.get(
            BASE_URL,
            params=_params(action='setStatus', id=activation_id, status=6),
            timeout=10,
        )
        text = r.text.strip()
        if text == 'ACCESS_CANCEL':
            return {'success': True}
        return {'error': text}
    except Exception as e:
        return {'error': str(e)}


def map_country(fivesim_country):
    return resolve_country_id(fivesim_country)


def map_service(fivesim_product):
    return SERVICE_MAP.get((fivesim_product or '').lower())

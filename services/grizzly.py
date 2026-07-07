import re
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

# Grizzly's price dump contains thousands of $0.0001 placeholder services with
# fake stock that always return NO_NUMBERS (verified live July 2026) — anything
# below this floor is junk and never shown or bought.
MIN_REAL_COST_USD = 0.01

# ── Dynamic service map (getServicesList) ─────────────────────────────────────
# Grizzly publishes its official code -> display-name list. We layer it UNDER
# the static SERVICE_MAP so every existing product name stays identical, while
# services we never mapped by hand become buyable under a generated slug
# (e.g. "C6 Bank" -> 'c6_bank', which the frontend renders back as "C6 Bank").

_services_cache: dict = {}          # code -> display name
_services_cache_time: float = 0
_services_last_attempt: float = 0
_SERVICES_TTL = 86400               # refresh daily
_SERVICES_RETRY_AFTER = 300         # don't hammer the API when it's down

_dynamic_maps_cache = None
_dynamic_maps_src_time = None


def _load_services(force=False) -> dict:
    global _services_cache, _services_cache_time, _services_last_attempt
    now = time.time()
    if not force and _services_cache and (now - _services_cache_time) < _SERVICES_TTL:
        return _services_cache
    if not force and not _services_cache and (now - _services_last_attempt) < _SERVICES_RETRY_AFTER:
        return _services_cache
    _services_last_attempt = now
    try:
        r = requests.get(BASE_URL, params=_params(action='getServicesList'), timeout=30)
        data = r.json()
        items = data.get('services', []) if isinstance(data, dict) else []
        parsed = {}
        for it in items:
            if not isinstance(it, dict):
                continue
            code = (it.get('code') or '').strip()
            name = (it.get('name') or '').strip()
            if code and name:
                parsed[code] = name
        if parsed:
            _services_cache = parsed
            _services_cache_time = now
    except Exception:
        pass
    return _services_cache


def _slugify(name: str) -> str:
    return re.sub(r'[^a-z0-9]+', '_', name.lower()).strip('_')


def _dynamic_maps():
    """(code -> product slug, product slug -> code) learned from Grizzly's list.
    Static SERVICE_MAP entries always win for codes/names they already cover."""
    global _dynamic_maps_cache, _dynamic_maps_src_time
    services = _load_services()
    if _dynamic_maps_cache is not None and _dynamic_maps_src_time == _services_cache_time:
        return _dynamic_maps_cache

    code_to_product = {}
    product_to_code = {}
    for code, display in services.items():
        if code in CODE_TO_FIVESIM:
            continue  # static mapping wins
        slug = _slugify(display)
        if not slug or slug in SERVICE_MAP or slug in product_to_code:
            continue
        code_to_product[code] = slug
        product_to_code[slug] = code

    _dynamic_maps_cache = (code_to_product, product_to_code)
    _dynamic_maps_src_time = _services_cache_time
    return _dynamic_maps_cache


def code_to_product(service_code):
    """Service code -> product name (static map first, then Grizzly's own list)."""
    name = CODE_TO_FIVESIM.get(service_code)
    if name:
        return name
    return _dynamic_maps()[0].get(service_code)


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
        if count <= 0 or cost < MIN_REAL_COST_USD:
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
        # SMS-Activate protocol: status=8 cancels the activation and returns
        # ACCESS_CANCEL; status=6 FINISHES it (we get charged) and returns
        # ACCESS_ACTIVATION — so 6 here silently paid for every "cancel".
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


def get_service_catalog() -> list:
    """Return [{name (5sim product name), qty}] for every service available in the Grizzly price dump."""
    prices = _load_all_prices()
    service_counts: dict = {}
    for country_data in prices.values():
        if not isinstance(country_data, dict):
            continue
        for svc_code, info in country_data.items():
            if not isinstance(info, dict):
                continue
            # Codes with no product name (static or dynamic) can't be bought — skip
            if not code_to_product(svc_code):
                continue
            count = _extract_count(info)
            cost = _extract_cost(info)
            if count <= 0 or cost < MIN_REAL_COST_USD:
                continue
            service_counts[svc_code] = service_counts.get(svc_code, 0) + count

    result = []
    for svc_code, total_count in service_counts.items():
        result.append({'name': code_to_product(svc_code), 'qty': total_count})
    result.sort(key=lambda x: x['name'])
    return result


def get_prices_by_service(fivesim_product_name: str) -> list:
    """Return [{country, cost_usd, count}] for all countries offering the given 5sim product name."""
    svc_code = map_service(fivesim_product_name)
    if not svc_code:
        return []

    prices = _load_all_prices()

    # Reverse COUNTRY_MAP: grizzly_id_str → country_name (first match wins)
    id_to_country: dict = {}
    for country_name, cid in COUNTRY_MAP.items():
        cid_str = str(cid)
        if cid_str not in id_to_country:
            id_to_country[cid_str] = country_name

    result = []
    for country_id_str, country_data in prices.items():
        if not isinstance(country_data, dict) or svc_code not in country_data:
            continue
        info = country_data[svc_code]
        if not isinstance(info, dict):
            continue
        count = _extract_count(info)
        cost_usd = _extract_cost(info)
        if count <= 0 or cost_usd < MIN_REAL_COST_USD:
            continue
        country_name = id_to_country.get(country_id_str)
        if not country_name:
            continue
        result.append({'country': country_name, 'cost_usd': cost_usd, 'count': count})
    return result


def map_country(fivesim_country):
    return resolve_country_id(fivesim_country)


def map_service(fivesim_product):
    name = (fivesim_product or '').lower()
    code = SERVICE_MAP.get(name)
    if code:
        return code
    return _dynamic_maps()[1].get(name)

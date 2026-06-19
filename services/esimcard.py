import requests
from django.conf import settings

BASE_URL = 'https://portal.esimcard.com/api/developer/reseller'


def _headers():
    return {
        'Authorization': f'Bearer {settings.ESIMCARD_API_TOKEN}',
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }


def _get(path, params=None):
    try:
        r = requests.get(f'{BASE_URL}{path}', headers=_headers(), params=params, timeout=15)
        return r.json()
    except Exception as e:
        return {'status': False, 'error': str(e)}


def _post(path, data=None):
    try:
        r = requests.post(f'{BASE_URL}{path}', headers=_headers(), json=data or {}, timeout=30)
        return r.json()
    except Exception as e:
        return {'status': False, 'error': str(e)}


def get_countries():
    return _get('/packages/country')


def get_country_packages(country_id, package_type='DATA-ONLY'):
    return _get(f'/packages/country/{country_id}', params={'package_type': package_type})


def get_package_detail(package_id):
    return _get(f'/package/detail/{package_id}')


def purchase_esim(package_type_id):
    return _post('/package/purchase', {'package_type_id': package_type_id})


def get_my_esims():
    return _get('/my-esims')


def get_esim_detail(esim_id):
    return _get(f'/my-esims/{esim_id}')


def get_esim_usage(esim_id):
    return _get(f'/my-sim/{esim_id}/usage')


def get_balance():
    return _get('/balance')

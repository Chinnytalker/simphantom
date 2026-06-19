import requests
from decouple import config

BASE_URL = "https://5sim.net/v1"

def get_headers():
    return {
        "Authorization": f"Bearer {config('FIVESIM_API_KEY')}",
        "Accept": "application/json"
    }

def get_countries():
    """Get list of all countries"""
    try:
        url = f"{BASE_URL}/guest/countries"
        response = requests.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {'error': str(e)}

def get_products(country, operator='any'):
    """Get available services and prices for a country"""
    try:
        url = f"{BASE_URL}/guest/products/{country}/{operator}"
        response = requests.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {'error': str(e)}

def buy_number(country, operator, product):
    """Purchase a virtual number"""
    try:
        url = f"{BASE_URL}/user/buy/activation/{country}/{operator}/{product}"
        response = requests.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {'error': str(e)}

def check_order(order_id):
    """Check order status and get SMS"""
    try:
        url = f"{BASE_URL}/user/check/{order_id}"
        response = requests.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {'error': str(e)}

def cancel_order(order_id):
    """Cancel an order"""
    try:
        url = f"{BASE_URL}/user/cancel/{order_id}"
        response = requests.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {'error': str(e)}

def get_prices_by_product(product, country=None):
    """Get available countries (or one country) for a given product, with pricing"""
    try:
        params = {'product': product}
        if country:
            params['country'] = country
        url = f"{BASE_URL}/guest/prices"
        response = requests.get(url, headers=get_headers(), params=params)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {'error': str(e)}


def get_balance():
    """Check your 5sim account balance"""
    try:
        url = f"{BASE_URL}/user/profile"
        response = requests.get(url, headers=get_headers())
        response.raise_for_status()
        return response.json()
    except Exception as e:
        return {'error': str(e)}
import random
import string
import requests

BASE_URL = "https://api.mail.tm"


def _headers(token=None):
    h = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def get_domains():
    try:
        r = requests.get(f"{BASE_URL}/domains", headers=_headers(), timeout=10)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("hydra:member", [])
    except Exception as e:
        return {"error": str(e)}


def create_account(address, password):
    try:
        r = requests.post(f"{BASE_URL}/accounts", headers=_headers(),
                          json={"address": address, "password": password}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def get_token(address, password):
    try:
        r = requests.post(f"{BASE_URL}/token", headers=_headers(),
                          json={"address": address, "password": password}, timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def get_messages(token):
    try:
        r = requests.get(f"{BASE_URL}/messages?page=1", headers=_headers(token), timeout=10)
        r.raise_for_status()
        data = r.json()
        return data if isinstance(data, list) else data.get("hydra:member", [])
    except Exception as e:
        return {"error": str(e)}


def get_message(token, message_id):
    try:
        r = requests.get(f"{BASE_URL}/messages/{message_id}", headers=_headers(token), timeout=10)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        return {"error": str(e)}


def delete_account(token, account_id):
    try:
        r = requests.delete(f"{BASE_URL}/accounts/{account_id}", headers=_headers(token), timeout=10)
        r.raise_for_status()
        return {"success": True}
    except Exception as e:
        return {"error": str(e)}


def random_address():
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choices(chars, k=12))


def random_password():
    chars = string.ascii_letters + string.digits + "!@#$%"
    return ''.join(random.choices(chars, k=20))

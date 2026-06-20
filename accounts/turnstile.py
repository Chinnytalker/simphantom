import requests
from django.conf import settings


def verify_turnstile(token, ip=None):
    if not token:
        return False
    data = {
        'secret':   settings.CLOUDFLARE_TURNSTILE_SECRET_KEY,
        'response': token,
    }
    if ip:
        data['remoteip'] = ip
    try:
        r = requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data=data,
            timeout=5,
        )
        return r.json().get('success', False)
    except Exception:
        return False

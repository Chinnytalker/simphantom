import os
import urllib.parse

import requests

VPN_SERVERS = {
    'us': {
        'name': 'United States',
        'endpoint': os.getenv('VPN_US_ENDPOINT', ''),
        'public_key': os.getenv('VPN_US_PUBKEY', ''),
        'api_url': os.getenv('VPN_US_API_URL', ''),
        'api_key': os.getenv('VPN_US_API_KEY', ''),
    },
    'uk': {
        'name': 'United Kingdom',
        'endpoint': os.getenv('VPN_UK_ENDPOINT', ''),
        'public_key': os.getenv('VPN_UK_PUBKEY', ''),
        'api_url': os.getenv('VPN_UK_API_URL', ''),
        'api_key': os.getenv('VPN_UK_API_KEY', ''),
    },
}


def _headers(location):
    return {'X-API-Key': VPN_SERVERS[location]['api_key']}


def add_peer(location, public_key):
    """
    Register a new WireGuard peer on the server.
    Returns {'assigned_ip': str, 'server_public_key': str} or {'error': str}.
    """
    server = VPN_SERVERS.get(location)
    if not server or not server['api_url']:
        return {'error': f'VPN server for "{location}" is not configured yet.'}

    try:
        resp = requests.post(
            f"{server['api_url'].rstrip('/')}/peers",
            json={'public_key': public_key},
            headers=_headers(location),
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            'assigned_ip': data['assigned_ip'],
            'server_public_key': data.get('server_public_key', server['public_key']),
        }
    except requests.RequestException as exc:
        return {'error': str(exc)}


def remove_peer(location, public_key):
    """Remove a WireGuard peer from the server. Returns {'success': True} or {'error': str}."""
    server = VPN_SERVERS.get(location)
    if not server or not server['api_url']:
        return {'error': 'Server not configured'}

    try:
        encoded = urllib.parse.quote(public_key, safe='')
        resp = requests.delete(
            f"{server['api_url'].rstrip('/')}/peers/{encoded}",
            headers=_headers(location),
            timeout=15,
        )
        resp.raise_for_status()
        return {'success': True}
    except requests.RequestException as exc:
        return {'error': str(exc)}

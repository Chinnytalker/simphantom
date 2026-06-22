import ipaddress
import json
import os
import subprocess
import threading
import urllib.parse

from fastapi import FastAPI, HTTPException, Header, Depends
from pydantic import BaseModel

# Read keys from files (written by setup_server.sh) with env var fallback
def _read_key(path, env_var):
    try:
        return open(path).read().strip()
    except FileNotFoundError:
        return os.environ[env_var]

WG_PUBLIC_KEY = _read_key('/etc/wireguard/server_public.key', 'WG_PUBLIC_KEY')
API_KEY       = os.environ['API_KEY']
WG_IFACE      = 'wg0'
PEERS_FILE    = '/opt/vpn-api/peers.json'
SUBNET        = os.getenv('WG_SUBNET', '10.8.0.0/24')

network  = ipaddress.IPv4Network(SUBNET, strict=False)
ip_pool  = list(network.hosts())[1:]  # .1 is the server
lock     = threading.Lock()


def _load_peers():
    try:
        return json.load(open(PEERS_FILE))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_peers(peers):
    json.dump(peers, open(PEERS_FILE, 'w'), indent=2)


def _next_ip(peers):
    used = {p['ip'] for p in peers.values()}
    for ip in ip_pool:
        if str(ip) not in used:
            return str(ip)
    return None


def _wg_add(public_key, ip):
    subprocess.run(['wg', 'set', WG_IFACE, 'peer', public_key, 'allowed-ips', f'{ip}/32'], check=True)
    subprocess.run(['wg-quick', 'save', WG_IFACE], check=False)


def _wg_remove(public_key):
    subprocess.run(['wg', 'set', WG_IFACE, 'peer', public_key, 'remove'], check=True)
    subprocess.run(['wg-quick', 'save', WG_IFACE], check=False)


app = FastAPI(docs_url=None, redoc_url=None)


def _auth(x_api_key: str = Header(...)):
    if x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail='Invalid API key')


class AddPeerRequest(BaseModel):
    public_key: str


@app.get('/health')
def health():
    return {'ok': True}


@app.get('/pubkey')
def pubkey():
    return {'public_key': WG_PUBLIC_KEY}


@app.post('/peers', dependencies=[Depends(_auth)])
def add_peer(body: AddPeerRequest):
    with lock:
        peers = _load_peers()
        if body.public_key in peers:
            return {'assigned_ip': peers[body.public_key]['ip'], 'server_public_key': WG_PUBLIC_KEY}
        ip = _next_ip(peers)
        if not ip:
            raise HTTPException(status_code=503, detail='IP pool exhausted')
        try:
            _wg_add(body.public_key, ip)
        except subprocess.CalledProcessError as exc:
            raise HTTPException(status_code=500, detail=f'wg set failed: {exc}')
        peers[body.public_key] = {'ip': ip}
        _save_peers(peers)
    return {'assigned_ip': ip, 'server_public_key': WG_PUBLIC_KEY}


@app.delete('/peers/{public_key}', dependencies=[Depends(_auth)])
def remove_peer(public_key: str):
    public_key = urllib.parse.unquote(public_key)
    with lock:
        peers = _load_peers()
        if public_key not in peers:
            raise HTTPException(status_code=404, detail='Peer not found')
        try:
            _wg_remove(public_key)
        except Exception:
            pass
        del peers[public_key]
        _save_peers(peers)
    return {'success': True}


@app.on_event('startup')
def reload_peers():
    peers = _load_peers()
    for pub, info in peers.items():
        try:
            _wg_add(pub, info['ip'])
        except Exception:
            pass


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='0.0.0.0', port=int(os.getenv('PORT', 8080)))

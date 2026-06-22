#!/bin/sh
set -e

DATA=/data
mkdir -p "$DATA"

# Generate server keys once and persist them
if [ ! -f "$DATA/server_private.key" ]; then
    wg genkey > "$DATA/server_private.key"
    wg pubkey < "$DATA/server_private.key" > "$DATA/server_public.key"
    echo "[vpn] Generated new WireGuard keypair."
fi

PRIVATE_KEY=$(cat "$DATA/server_private.key")
PUBLIC_KEY=$(cat "$DATA/server_public.key")

export WG_PUBLIC_KEY="$PUBLIC_KEY"
export PEERS_FILE="$DATA/peers.json"

# Write WireGuard server config
cat > /etc/wireguard/wg0.conf << EOF
[Interface]
PrivateKey = $PRIVATE_KEY
Address = 10.8.0.1/24
ListenPort = 51820
PostUp   = iptables -A FORWARD -i wg0 -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i wg0 -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
EOF

sysctl -w net.ipv4.ip_forward=1 || true
wg-quick up wg0 || true

echo "[vpn] Server public key: $PUBLIC_KEY"
echo "[vpn] API starting on port 8080..."

exec uvicorn main:app --host 0.0.0.0 --port 8080

#!/bin/bash
# SimPhantom VPN API Server — one-shot setup for Ubuntu/Debian AWS EC2
# Run as root: sudo bash install_on_server.sh
set -e

API_KEY="SimPhantom200"
VPN_PORT=51820
API_PORT=8080
SERVER_IP=$(curl -s ifconfig.me)
WG_IFACE="wg0"
SUBNET="10.8.0.0/24"
SERVER_PRIVATE_IP="10.8.0.1"

echo "=== SimPhantom VPN Server Setup ==="
echo "Public IP: $SERVER_IP"
echo "API Port:  $API_PORT"
echo "WG Port:   $VPN_PORT"

# ── 1. Install dependencies ────────────────────────────────────────────────────
apt-get update -qq
apt-get install -y wireguard python3 python3-pip python3-venv ufw

# ── 2. Generate WireGuard server keys ─────────────────────────────────────────
mkdir -p /etc/wireguard /opt/vpn-api
umask 077
if [ ! -f /etc/wireguard/server_private.key ]; then
    wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key
    echo "Generated new WireGuard keypair."
else
    echo "WireGuard keys already exist — skipping."
fi

PRIVATE_KEY=$(cat /etc/wireguard/server_private.key)
PUBLIC_KEY=$(cat /etc/wireguard/server_public.key)
echo "Server Public Key: $PUBLIC_KEY"

# ── 3. Write WireGuard server config ──────────────────────────────────────────
if [ ! -f /etc/wireguard/${WG_IFACE}.conf ]; then
    cat > /etc/wireguard/${WG_IFACE}.conf <<EOF
[Interface]
PrivateKey = $PRIVATE_KEY
Address = $SERVER_PRIVATE_IP/24
ListenPort = $VPN_PORT
PostUp   = iptables -A FORWARD -i ${WG_IFACE} -j ACCEPT; iptables -t nat -A POSTROUTING -o eth0 -j MASQUERADE
PostDown = iptables -D FORWARD -i ${WG_IFACE} -j ACCEPT; iptables -t nat -D POSTROUTING -o eth0 -j MASQUERADE
EOF
    echo "Written /etc/wireguard/${WG_IFACE}.conf"
fi

# ── 4. Enable IP forwarding ────────────────────────────────────────────────────
if ! grep -q "net.ipv4.ip_forward=1" /etc/sysctl.conf; then
    echo "net.ipv4.ip_forward=1" >> /etc/sysctl.conf
fi
sysctl -p

# ── 5. Start WireGuard ────────────────────────────────────────────────────────
systemctl enable wg-quick@${WG_IFACE}
systemctl start wg-quick@${WG_IFACE} || systemctl restart wg-quick@${WG_IFACE}
echo "WireGuard started."

# ── 6. Set up Python venv + FastAPI ──────────────────────────────────────────
python3 -m venv /opt/vpn-api/venv
/opt/vpn-api/venv/bin/pip install -q fastapi uvicorn[standard] pydantic

# Copy main.py to server
cp "$(dirname "$0")/main.py" /opt/vpn-api/main.py

# ── 7. Create systemd service ─────────────────────────────────────────────────
cat > /etc/systemd/system/vpn-api.service <<EOF
[Unit]
Description=SimPhantom VPN API
After=network.target wg-quick@${WG_IFACE}.service
Requires=wg-quick@${WG_IFACE}.service

[Service]
Type=simple
Environment="API_KEY=${API_KEY}"
Environment="WG_SUBNET=${SUBNET}"
WorkingDirectory=/opt/vpn-api
ExecStart=/opt/vpn-api/venv/bin/uvicorn main:app --host 0.0.0.0 --port ${API_PORT}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable vpn-api
systemctl restart vpn-api
echo "vpn-api service started."

# ── 8. Firewall rules ─────────────────────────────────────────────────────────
ufw allow ${VPN_PORT}/udp comment "WireGuard"
ufw allow ${API_PORT}/tcp comment "SimPhantom VPN API"
ufw allow 22/tcp comment "SSH"
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
echo "Firewall rules applied."

# ── 9. Done ───────────────────────────────────────────────────────────────────
echo ""
echo "=============================="
echo " SimPhantom VPN Server Ready"
echo "=============================="
echo " Public Key : $PUBLIC_KEY"
echo " Endpoint   : $SERVER_IP:$VPN_PORT"
echo " API URL    : http://$SERVER_IP:$API_PORT"
echo " API Key    : $API_KEY"
echo ""
echo " Add these to your Django .env:"
echo "   VPN_US_PUBKEY=$PUBLIC_KEY"
echo "   VPN_US_ENDPOINT=$SERVER_IP:$VPN_PORT"
echo "   VPN_US_API_URL=http://$SERVER_IP:$API_PORT"
echo "   VPN_US_API_KEY=$API_KEY"
echo ""
echo " Test: curl http://$SERVER_IP:$API_PORT/health"

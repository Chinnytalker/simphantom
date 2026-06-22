#!/bin/bash
# Upload this file AND main.py to the server, then run: bash setup_server.sh
set -e

echo "=== Installing WireGuard and Python ==="
sudo apt-get update -y
sudo apt-get install -y wireguard wireguard-tools python3 python3-pip python3-venv iptables iproute2

echo "=== Generating WireGuard server keys ==="
sudo mkdir -p /etc/wireguard
WG_PRIVATE=$(wg genkey)
WG_PUBLIC=$(echo "$WG_PRIVATE" | wg pubkey)
echo "$WG_PRIVATE" | sudo tee /etc/wireguard/server_private.key > /dev/null
sudo chmod 600 /etc/wireguard/server_private.key
echo "$WG_PUBLIC"  | sudo tee /etc/wireguard/server_public.key  > /dev/null

echo "=== Creating WireGuard config ==="
IFACE=$(ip route | awk '/default/ {print $5; exit}')

cat << EOF | sudo tee /etc/wireguard/wg0.conf > /dev/null
[Interface]
PrivateKey = $WG_PRIVATE
Address = 10.8.0.1/24
ListenPort = 51820
PostUp   = sysctl -w net.ipv4.ip_forward=1; iptables -t nat -A POSTROUTING -s 10.8.0.0/24 -o $IFACE -j MASQUERADE
PostDown = iptables -t nat -D POSTROUTING -s 10.8.0.0/24 -o $IFACE -j MASQUERADE
EOF

sudo chmod 600 /etc/wireguard/wg0.conf

echo "=== Starting WireGuard ==="
sudo systemctl enable wg-quick@wg0
sudo systemctl restart wg-quick@wg0

echo "=== Setting up management API ==="
sudo mkdir -p /opt/vpn-api

# main.py must be in the same directory as this script
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
if [ -f "$SCRIPT_DIR/main.py" ]; then
    sudo cp "$SCRIPT_DIR/main.py" /opt/vpn-api/main.py
elif [ -f "$HOME/main.py" ]; then
    sudo cp "$HOME/main.py" /opt/vpn-api/main.py
else
    echo "ERROR: main.py not found. Upload it alongside this script and try again."
    exit 1
fi

echo "=== Installing Python dependencies ==="
sudo python3 -m venv /opt/vpn-api/.venv
sudo /opt/vpn-api/.venv/bin/pip install --quiet fastapi uvicorn pydantic

echo ""
read -p "Enter an API key (make up any long password, e.g. SimPhantomVPN2024): " INPUT_API_KEY
echo ""

echo "=== Creating systemd service ==="
cat << EOF | sudo tee /etc/systemd/system/vpn-api.service > /dev/null
[Unit]
Description=VPN Management API
After=network.target wg-quick@wg0.service
Requires=wg-quick@wg0.service

[Service]
Environment=API_KEY=$INPUT_API_KEY
Environment=WG_SUBNET=10.8.0.0/24
Environment=PORT=8080
ExecStart=/opt/vpn-api/.venv/bin/python /opt/vpn-api/main.py
Restart=always
RestartSec=5
WorkingDirectory=/opt/vpn-api

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable vpn-api
sudo systemctl restart vpn-api

EXTERNAL_IP=$(curl -s ifconfig.me)
SERVER_PUBKEY=$(cat /etc/wireguard/server_public.key)

echo ""
echo "=========================================="
echo "      SETUP COMPLETE — SAVE THESE"
echo "=========================================="
echo ""
echo "VPN_US_PUBKEY=$SERVER_PUBKEY"
echo "VPN_US_ENDPOINT=$EXTERNAL_IP:51820"
echo "VPN_US_API_URL=http://$EXTERNAL_IP:8080"
echo "VPN_US_API_KEY=$INPUT_API_KEY"
echo ""
echo "=========================================="

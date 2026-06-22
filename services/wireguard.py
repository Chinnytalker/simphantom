import base64
import io

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding, NoEncryption, PrivateFormat, PublicFormat,
)


def generate_keypair():
    """Return (private_key_b64, public_key_b64) — a fresh WireGuard key pair."""
    private = X25519PrivateKey.generate()
    priv_b64 = base64.b64encode(
        private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())
    ).decode()
    pub_b64 = base64.b64encode(
        private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    return priv_b64, pub_b64


def build_client_config(client_private_key, assigned_ip, server_public_key, server_endpoint):
    """Build the .conf file text that the user imports into the WireGuard app."""
    return (
        "[Interface]\n"
        f"PrivateKey = {client_private_key}\n"
        f"Address = {assigned_ip}/32\n"
        "DNS = 1.1.1.1, 1.0.0.1\n"
        "\n"
        "[Peer]\n"
        f"PublicKey = {server_public_key}\n"
        f"Endpoint = {server_endpoint}\n"
        "AllowedIPs = 0.0.0.0/0, ::/0\n"
        "PersistentKeepalive = 25\n"
    )


def config_to_qr_base64(config_str):
    """Return a base64-encoded PNG QR code of the config, or None if qrcode is not installed."""
    try:
        import qrcode
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_L)
        qr.add_data(config_str)
        qr.make(fit=True)
        img = qr.make_image(fill_color='black', back_color='white')
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        return base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        return None

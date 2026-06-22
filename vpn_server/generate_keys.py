"""
Run this on your PC to generate WireGuard keys for each server.
Usage:  python generate_keys.py
"""

import base64
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat, PublicFormat


def gen():
    private = X25519PrivateKey.generate()
    priv = base64.b64encode(private.private_bytes(Encoding.Raw, PrivateFormat.Raw, NoEncryption())).decode()
    pub  = base64.b64encode(private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
    return priv, pub


us_priv, us_pub = gen()
uk_priv, uk_pub = gen()

print("=" * 60)
print("USA SERVER KEYS")
print("=" * 60)
print(f"Private key: {us_priv}")
print(f"Public key:  {us_pub}")
print()
print("=" * 60)
print("UK SERVER KEYS")
print("=" * 60)
print(f"Private key: {uk_priv}")
print(f"Public key:  {uk_pub}")
print()
print("SAVE THESE. You will need them in the next steps.")

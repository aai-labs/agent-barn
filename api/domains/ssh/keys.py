"""Key parsing only; OpenSSH owns authentication signing and destination checks."""

import base64
import hashlib

from cryptography.hazmat.primitives.asymmetric import ec, ed25519, rsa
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
    load_pem_private_key,
    load_ssh_private_key,
    load_ssh_public_key,
)


def fingerprint(public_key: str) -> str:
    blob = base64.b64decode(public_key.split()[1], validate=True)
    return "SHA256:" + base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")


def normalize_public_key(value: str) -> str:
    if "\n" in value or "\r" in value:
        raise ValueError("Supply one SSH host public key per entry")
    try:
        parts = value.split()
        if len(parts) >= 3 and not parts[0].startswith(("ssh-", "ecdsa-")):
            value = " ".join(parts[1:])
        key = load_ssh_public_key(value.encode())
        return key.public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
    except Exception:
        raise ValueError("Invalid SSH host public key") from None


def prepare_key(private_key: str | None, passphrase: str | None, *, generate: bool) -> tuple[str, str, str]:
    """Return normalized private/public material and algorithm; never echo submitted data."""
    try:
        if generate:
            key = ed25519.Ed25519PrivateKey.generate()
        else:
            data = (private_key or "").encode()
            password = passphrase.encode() if passphrase else None
            loader = load_ssh_private_key if b"BEGIN OPENSSH PRIVATE KEY" in data else load_pem_private_key
            key = loader(data, password=password)
        if isinstance(key, rsa.RSAPrivateKey):
            if key.key_size < 2048:
                raise ValueError("RSA too small")
        elif isinstance(key, ec.EllipticCurvePrivateKey):
            if not isinstance(key.curve, (ec.SECP256R1, ec.SECP384R1, ec.SECP521R1)):
                raise TypeError("Unsupported curve")
        elif not isinstance(key, ed25519.Ed25519PrivateKey):
            raise TypeError("Unsupported key")
        public = key.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
        private = key.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()).decode()
        return private, public, public.split()[0]
    except Exception:
        raise ValueError(
            "Use a valid Ed25519, RSA (2048+ bits), or NIST ECDSA private key and its passphrase"
        ) from None

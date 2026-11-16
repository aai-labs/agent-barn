"""Generate a disposable local signing-listener certificate, never a production identity."""

import ipaddress
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat


def main() -> None:
    root = Path(__file__).resolve().parents[2] / ".scratch/ssh-tls"
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    if (root / "key.pem").exists() or (root / "cert.pem").exists():
        raise SystemExit("Local SSH TLS files already exist; remove them explicitly to rotate")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "Agent Barn local SSH signer")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=30))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName("localhost"),
                    x509.DNSName("host.docker.internal"),
                    x509.DNSName("host.k3d.internal"),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.1")),
                ]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    (root / "key.pem").write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    (root / "cert.pem").write_bytes(cert.public_bytes(Encoding.PEM))
    # Private parent protects the host file; Compose binds only these individual
    # files into the non-root signer, which needs permission to read its TLS key.
    (root / "key.pem").chmod(0o644)
    print("Local-only signing TLS files created in .scratch/ssh-tls (30 day expiry)")


if __name__ == "__main__":
    main()

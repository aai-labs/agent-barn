"""Disposable real SSH/WSS boundaries. No installed accounts or infrastructure credentials."""

import ipaddress
import socket
import threading
import time
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import docker
import docker.errors
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat


@contextmanager
def tls_listener(app, root: Path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, "localhost")])
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]),
            False,
        )
        .sign(key, hashes.SHA256())
    )
    cert, pem = root / "tls-cert.pem", root / "tls-key.pem"
    cert.write_bytes(certificate.public_bytes(Encoding.PEM))
    pem.write_bytes(key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    pem.chmod(0o600)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(app, log_level="error", ssl_certfile=str(cert), ssl_keyfile=str(pem), ws_max_size=262144)
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError("Test signing listener did not start")
            time.sleep(0.02)
        yield f"wss://127.0.0.1:{port}/ssh/v1/agent", cert
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()


@contextmanager
def ssh_server(root: Path, public_key: str):
    """A local Docker SSH server accepting only one disposable key."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import PublicFormat

    client = docker.from_env()
    image = "agentbarn-ssh-fixture:bookworm-v1"
    try:
        client.images.get(image)
    except docker.errors.ImageNotFound:
        client.images.build(path=str(Path(__file__).parents[1] / "fixtures/ssh"), tag=image, rm=True)
    root.mkdir()
    root.chmod(0o755)
    host = Ed25519PrivateKey.generate()
    private = root / "host_key"
    private.write_bytes(host.private_bytes(Encoding.PEM, PrivateFormat.OpenSSH, NoEncryption()))
    private.chmod(0o600)
    host_public = host.public_key().public_bytes(Encoding.OpenSSH, PublicFormat.OpenSSH).decode()
    (root / "authorized_keys").write_text(public_key + "\n")
    (root / "sshd_config").write_text(
        "Port 2222\nHostKey /run/sshd/host_key\nAuthorizedKeysFile /run/sshd/authorized_keys\n"
        "StrictModes yes\nPermitRootLogin prohibit-password\nPasswordAuthentication no\n"
        "KbdInteractiveAuthentication no\nUsePAM no\nPidFile /tmp/sshd.pid\n"
        "Subsystem sftp internal-sftp\nLogLevel VERBOSE\n"
    )
    container = client.containers.run(
        image,
        # CI bind mounts retain the runner UID. sshd's StrictModes requires the
        # root account's authorized_keys to be owned by root inside the server.
        entrypoint="sh",
        command=[
            "-c",
            (
                "cp /fixture/host_key /fixture/authorized_keys /fixture/sshd_config /run/sshd/"
                " && chmod 600 /run/sshd/host_key /run/sshd/authorized_keys"
                " && exec /usr/sbin/sshd -D -e -f /run/sshd/sshd_config"
            ),
        ],
        detach=True,
        ports={"2222/tcp": ("127.0.0.1", None)},
        volumes={str(root): {"bind": "/fixture", "mode": "ro"}},
    )
    try:
        container.reload()
        port = int(container.attrs["NetworkSettings"]["Ports"]["2222/tcp"][0]["HostPort"])
        deadline = time.monotonic() + 15
        while True:
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=1):
                    break
            except OSError:
                if time.monotonic() > deadline:
                    raise RuntimeError("Disposable SSH server did not start") from None
                time.sleep(0.05)
        yield port, host_public
    finally:
        container.remove(force=True)
        client.close()


@contextmanager
def relay_client(artifacts, ca: Path, root: Path):
    """Run the shipped relay with only its public files and generation token."""
    import importlib.util
    import json
    import os
    import subprocess
    import sys
    from types import SimpleNamespace

    relay = root / "ssh-agent-relay.py"
    relay.write_text(artifacts.files["ssh-agent-relay.py"])
    manifest = root / "profiles.json"
    manifest.write_text(artifacts.files["ssh-client.json"])
    spec = importlib.util.spec_from_file_location("ssh_relay_fixture", relay)
    if spec is None or spec.loader is None:
        raise RuntimeError("Relay module cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    directory = root / "relay"
    module.configure(directory, str(manifest), root / "home/config")
    env = {
        **os.environ,
        **artifacts.env,
        "SSH_AUTH_SOCK": str(directory / "agent.sock"),
        "AGENTBARN_SSH_DIRECTORY": str(directory),
        "AGENTBARN_SSH_CA_FILE": str(ca),
    }
    process = subprocess.Popen([sys.executable, str(relay)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    try:
        deadline = time.monotonic() + 10
        while not (directory / "agent.sock").exists():
            if process.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError("Relay did not start")
            time.sleep(0.02)
        config = str(directory / "config")

        def run(command, **kwargs):
            return subprocess.run(command, env=env, capture_output=True, timeout=30, check=False, **kwargs)

        yield SimpleNamespace(
            run=run,
            alias=json.loads(manifest.read_text())[0]["alias"],
            config=config,
            directory=directory,
            git_env={**env, "GIT_SSH_COMMAND": f"ssh -vvv -F {config}"},
        )
    finally:
        process.terminate()
        process.wait(timeout=5)
        if process.stderr:
            stderr = process.stderr.read().decode()
            if stderr:
                print("Relay diagnostics:", stderr)

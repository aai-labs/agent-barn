import base64
import os
import socket
import struct
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Self

from api.domains.ssh.models import SshCredential, SshServer
from api.domains.ssh.protocol import MAX_FRAME, string
from api.infrastructure.crypto import decrypt_token


class OpenSshSigner:
    """An isolated keyring and session-binding connection for one runtime socket."""

    def __init__(self, keys: list[SshCredential], encryption_key: str, directory: str, timeout: float = 10):
        self.keys = keys
        self.encryption_key = encryption_key
        self.directory = directory
        self.timeout = timeout
        self.process: subprocess.Popen | None = None
        self.connection: socket.socket | None = None
        self.temporary: tempfile.TemporaryDirectory | None = None

    def __enter__(self) -> Self:
        self.temporary = tempfile.TemporaryDirectory(prefix="ssh-", dir=self.directory)
        root = Path(self.temporary.name)
        sock = str(root / "agent.sock")
        try:
            self.process = subprocess.Popen(
                ["ssh-agent", "-D", "-a", sock, "-P", ""],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env={"PATH": os.defpath, "HOME": str(root)},
                start_new_session=True,
            )
            deadline = time.monotonic() + self.timeout
            while not Path(sock).exists():
                if self.process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError("SSH signer could not start")
                time.sleep(0.01)
            for key in self.keys:
                servers = [SshServer.model_validate(server) for server in key.servers]
                if key.mode == "restricted" and not servers:
                    continue
                args = ["ssh-add"]
                if key.mode == "restricted":
                    known = root / (str(key.id) + ".known_hosts")
                    # Synthetic names avoid DNS/port ambiguity: the actual restriction is the public host key.
                    known.write_text(
                        "".join(
                            f"server-{index} {host_key}\n"
                            for index, server in enumerate(servers)
                            for host_key in server.host_keys
                        )
                    )
                    args += ["-H", str(known)]
                    for index, server in enumerate(servers):
                        args += ["-h", f"{server.username}@server-{index}"]
                args += ["-"]
                private = decrypt_token(key.private_key_encrypted, self.encryption_key).encode()
                result = subprocess.run(
                    args,
                    check=False,
                    input=private,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=self.timeout,
                    env={"PATH": os.defpath, "HOME": str(root), "SSH_AUTH_SOCK": sock},
                )
                del private
                if result.returncode:
                    raise RuntimeError("SSH credential could not be loaded")
            self.connection = socket.socket(socket.AF_UNIX)
            self.connection.settimeout(self.timeout)
            self.connection.connect(sock)
            return self
        except BaseException:
            self.close()
            raise

    def exchange(self, payload: bytes) -> bytes:
        if self.connection is None:
            raise RuntimeError("SSH signer is closed")
        self.connection.sendall(string(payload))
        size = struct.unpack(">I", self._read(4))[0]
        if size < 1 or size > MAX_FRAME:
            raise ValueError("Invalid SSH-agent response")
        return self._read(size)

    def _read(self, size: int) -> bytes:
        if self.connection is None:
            raise RuntimeError("SSH signer is closed")
        result = bytearray()
        while len(result) < size:
            part = self.connection.recv(size - len(result))
            if not part:
                raise ConnectionError("SSH signer closed")
            result.extend(part)
        return bytes(result)

    def key_for_blob(self, blob: bytes) -> SshCredential | None:
        return next((key for key in self.keys if base64.b64decode(key.public_key.split()[1]) == blob), None)

    def close(self) -> None:
        if self.connection:
            self.connection.close()
            self.connection = None
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
            self.process = None
        if self.temporary:
            self.temporary.cleanup()
            self.temporary = None

    def __exit__(self, *args) -> None:
        self.close()

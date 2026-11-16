"""Unix SSH_AUTH_SOCK to authenticated WSS. Runs unchanged in both runtimes."""

import asyncio
import json
import os
import ssl
import struct
import sys
import time
from pathlib import Path

from websockets.asyncio.client import connect
from websockets.typing import Subprotocol

MAX_FRAME = 256 * 1024
SUBPROTOCOL = "agentbarn.ssh-agent.v1"


def configure(root, profiles_path, config_path):
    """Only public files. root is an ephemeral volume outside the Agent PVC."""
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(root, 0o700)
    profiles = json.loads(Path(profiles_path).read_text())
    known = []
    config = []
    for profile in profiles:
        identity = root / (profile["key_id"] + ".pub")
        identity.write_text(profile["public_key"] + "\n")
        identity.chmod(0o600)
        host_alias = profile["alias"]
        config.extend(
            [
                f"Host {host_alias}",
                f"    HostName {profile['hostname']}",
                f"    User {profile['username']}",
                f"    Port {profile['port']}",
                f"    HostKeyAlias {host_alias}",
                f"    IdentityFile {identity}",
                "    IdentitiesOnly yes",
                "",
            ]
        )
        destination = profile["hostname"] if profile["port"] == 22 else f"[{profile['hostname']}]:{profile['port']}"
        known.extend(f"{host_alias},{destination} {key}\n" for key in profile["host_keys"])
    config.extend(
        [
            "Host *",
            f"    IdentityAgent {root / 'agent.sock'}",
            f"    UserKnownHostsFile {root / 'known_hosts'}",
            "    StrictHostKeyChecking yes",
            "    ForwardAgent no",
            "    BatchMode yes",
            "",
        ]
    )
    (root / "known_hosts").write_text("".join(known))
    (root / "config").write_text("\n".join(config))
    # A managed include is first so normal SSH resolves the aliases automatically.
    # Preserve all unrelated user content and remove stale includes on every boot.
    config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    marker = "Include /run/agentbarn-ssh/config"
    previous = config_path.read_text() if config_path.exists() else ""
    lines = [line for line in previous.splitlines() if line != marker]
    config_path.write_text(marker + "\n" + "\n".join(lines) + "\n")
    config_path.chmod(0o600)


class Relay:
    def __init__(self):
        self.active = 0

    async def handle(self, reader, writer):
        if self.active >= 8:
            writer.close()
            await writer.wait_closed()
            return
        self.active += 1
        stage = "connect"
        try:
            url = os.environ["AGENTBARN_SSH_SIGNER_URL"]
            if not url.startswith("wss://"):
                raise ValueError("Verified TLS is required")
            async with connect(
                url,
                additional_headers={"Authorization": "Bearer " + os.environ["AGENTBARN_SSH_SIGNER_TOKEN"]},
                subprotocols=[Subprotocol(SUBPROTOCOL)],
                max_size=MAX_FRAME,
                open_timeout=10,
                close_timeout=2,
                proxy=None,
                ssl=ssl.create_default_context(cafile=os.environ.get("AGENTBARN_SSH_CA_FILE")),
            ) as upstream:
                if upstream.subprotocol != SUBPROTOCOL:
                    raise ValueError("Unsupported signing protocol")
                stage = "exchange"
                while True:
                    async with asyncio.timeout(60):
                        size = struct.unpack(">I", await reader.readexactly(4))[0]
                        if not 1 <= size <= MAX_FRAME:
                            raise ValueError("Invalid frame size")
                        payload = await reader.readexactly(size)
                    await upstream.send(payload)
                    response = await asyncio.wait_for(upstream.recv(), timeout=15)
                    if not isinstance(response, bytes) or not 1 <= len(response) <= MAX_FRAME:
                        raise ValueError("Invalid signing response")
                    writer.write(struct.pack(">I", len(response)) + response)
                    await asyncio.wait_for(writer.drain(), timeout=15)
        except asyncio.IncompleteReadError:
            pass
        except Exception as exc:
            # Fixed text: errors may contain URLs, credentials, or protocol contents.
            print(
                f"[ssh] Signing service unavailable or access refused ({stage}: {type(exc).__name__})", file=sys.stderr
            )
            try:
                writer.write(b"\x00\x00\x00\x01\x05")
                await asyncio.wait_for(writer.drain(), timeout=2)
            except OSError:
                pass
        finally:
            self.active -= 1
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass


async def serve(path):
    relay = Relay()
    async with await asyncio.start_unix_server(relay.handle, path=path, backlog=8) as server:
        os.chmod(path, 0o600)
        await server.serve_forever()


def main():
    root = Path(os.environ.get("AGENTBARN_SSH_DIRECTORY", "/run/agentbarn-ssh"))
    path = root / "agent.sock"
    if sys.argv[1:] == ["--wait"]:
        for _ in range(100):
            if path.exists():
                return
            time.sleep(0.05)
        raise SystemExit("SSH relay did not start")
    if sys.argv[1:] == ["--configure"]:
        configure(root, "/app/config/ssh-client.json", Path.home() / ".ssh/config")
        return
    os.umask(0o077)
    if path.exists():
        path.unlink()
    asyncio.run(serve(str(path)))


if __name__ == "__main__":
    main()

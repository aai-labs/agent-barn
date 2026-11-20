"""Unix SSH_AUTH_SOCK to authenticated WSS. Runs unchanged in both runtimes."""

import asyncio
import json
import os
import ssl
import struct
import sys
import time
from pathlib import Path
from uuid import UUID

from websockets.asyncio.client import connect
from websockets.typing import Subprotocol

MAX_FRAME = 256 * 1024
SUBPROTOCOL = "agentbarn.ssh-agent.v1"


def configure(root, profiles_path, config_path, additional=()):
    """Only public files. root is an ephemeral volume outside the Agent PVC."""
    known = []
    config = []
    for directory, manifest in [(root, profiles_path), *additional]:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        for profile in json.loads(Path(manifest).read_text()):
            identity = directory / (profile["key_id"] + ".pub")
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
            "    IdentityAgent ${AGENTBARN_SSH_DIRECTORY}/agent.sock",
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
    marker = f"Include {root / 'config'}"
    previous = config_path.read_text() if config_path.exists() else ""
    lines = [line for line in previous.splitlines() if line != marker]
    config_path.write_text(marker + "\n" + "\n".join(lines) + "\n")
    config_path.chmod(0o600)


class Relay:
    def __init__(self, environment):
        self.active = 0
        self.environment = environment

    async def handle(self, reader, writer):
        if self.active >= 8:
            writer.close()
            await writer.wait_closed()
            return
        self.active += 1
        stage = "connect"
        try:
            url = self.environment["AGENTBARN_SSH_SIGNER_URL"]
            if not url.startswith("wss://"):
                raise ValueError("Verified TLS is required")
            async with connect(
                url,
                additional_headers={"Authorization": "Bearer " + self.environment["AGENTBARN_SSH_SIGNER_TOKEN"]},
                subprotocols=[Subprotocol(SUBPROTOCOL)],
                max_size=MAX_FRAME,
                open_timeout=10,
                close_timeout=2,
                proxy=None,
                ssl=ssl.create_default_context(cafile=self.environment.get("AGENTBARN_SSH_CA_FILE")),
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


async def serve(path, environment):
    relay = Relay(environment)
    async with await asyncio.start_unix_server(relay.handle, path=path, backlog=8) as server:
        os.chmod(path, 0o600)
        await server.serve_forever()


def runtime_connections(root):
    """Each socket retains its own generation token, including in a shared Bot pod."""
    connections = []
    if os.environ.get("AGENTBARN_SSH_SIGNER_TOKEN"):
        connections.append((root, Path("/app/config"), dict(os.environ)))
    manifest = Path("/app/config/bots.json")
    if manifest.exists():
        for bot in json.loads(manifest.read_text()).get("bots", []):
            bot_id = str(UUID(bot["id"]))
            secret = Path("/run/agentbarn/bots") / bot_id
            token = secret / "AGENTBARN_SSH_SIGNER_TOKEN"
            identity = secret / "AGENT_ID"
            config = Path("/app/bots") / bot_id
            if (
                not token.is_file()
                or not identity.is_file()
                or identity.read_text() != bot_id
                or not (config / "ssh-client.json").is_file()
            ):
                continue
            environment = {
                path.name: path.read_text()
                for path in secret.iterdir()
                if path.is_file() and path.name.startswith("AGENTBARN_SSH_")
            }
            if "AGENTBARN_SSH_CA_FILE" in environment:
                environment["AGENTBARN_SSH_CA_FILE"] = str(config / "ssh-ca.pem")
            connections.append((root / bot_id, config, environment))
    return connections


async def serve_all(connections):
    await asyncio.gather(*(serve(str(directory / "agent.sock"), env) for directory, _, env in connections))


def main():
    root = Path(os.environ.get("AGENTBARN_SSH_DIRECTORY") or "/run/agentbarn-ssh")
    connections = runtime_connections(root)
    if not connections:
        return
    if sys.argv[1:] == ["--wait"]:
        for _ in range(100):
            if all((directory / "agent.sock").exists() for directory, _, _ in connections):
                return
            time.sleep(0.05)
        raise SystemExit("SSH relay did not start")
    if sys.argv[1:] == ["--configure"]:
        configure(
            root,
            "/app/config/ssh-client.json",
            Path.home() / ".ssh/config",
            [(directory, config / "ssh-client.json") for directory, config, _ in connections if directory != root],
        )
        return
    os.umask(0o077)
    for directory, _, _ in connections:
        path = directory / "agent.sock"
        if path.exists():
            path.unlink()
    asyncio.run(serve_all(connections))


if __name__ == "__main__":
    main()

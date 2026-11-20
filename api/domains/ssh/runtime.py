"""Public client configuration and a scoped token; never private-key material."""

import json
from pathlib import Path
from urllib.parse import urlsplit

from api.domains.integrations.plugins.base import RuntimeArtifacts
from api.domains.ssh.models import SshCredential, SshServer

SOCKET = "/run/agentbarn-ssh/agent.sock"
RELAY = (Path(__file__).parents[1] / "agents/scripts/ssh-agent-relay.py").read_text()


def materialize(
    keys: list[SshCredential],
    *,
    enabled: bool,
    url: str,
    token: str = "",
    ca_certificate: str = "",
    socket_directory: str = str(Path(SOCKET).parent),
) -> RuntimeArtifacts:
    if keys and (not enabled or urlsplit(url).scheme != "wss" or not urlsplit(url).hostname):
        raise ValueError("SSH access requires an enabled signer and a verified wss:// URL")
    files = {"ssh-agent-relay.py": RELAY, "ssh-client.json": "[]"}
    if not keys:
        return RuntimeArtifacts(files=files)
    profiles = []
    for key in keys:
        for raw in key.servers:
            server = SshServer.model_validate(raw)
            profiles.append(
                {
                    "alias": f"ab-{key.id.hex}-{server.name}",
                    "hostname": server.hostname,
                    "port": server.port,
                    "username": server.username,
                    "host_keys": server.host_keys,
                    "public_key": key.public_key,
                    "key_id": str(key.id),
                }
            )
    files["ssh-client.json"] = json.dumps(profiles)
    if ca_certificate:
        files["ssh-ca.pem"] = ca_certificate
    aliases = "\n".join(f"- `ssh {profile['alias']}`" for profile in profiles)
    return RuntimeArtifacts(
        files=files,
        env={
            "SSH_AUTH_SOCK": f"{socket_directory}/agent.sock",
            "AGENTBARN_SSH_DIRECTORY": socket_directory,
            "AGENTBARN_SSH_SIGNER_URL": url,
            "AGENTBARN_SSH_SIGNER_TOKEN": token,
            **({"AGENTBARN_SSH_CA_FILE": "/app/config/ssh-ca.pem"} if ca_certificate else {}),
        },
        policy_md="\n\n## SSH access\nUse ordinary ssh, git, scp and sftp through your terminal tool. "
        "Agent Barn holds the private keys and authenticates on your behalf. "
        "Remote account permissions govern what you can do. Existing activity history records terminal requests, "
        "not every action inside a remote script or interactive shell. Unknown or changed host keys must be "
        "verified by an administrator; do not bypass host verification. Configured connections:\n" + aliases + "\n",
    )

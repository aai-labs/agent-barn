"""Start a real runtime image on Agent Barn's MCP configuration and watch it reach the gateway.

A stub of the gateway's MCP route runs in its own container on a private Docker network; the
runtime container starts through its image's real start script with the generated ConfigMap.
When the start script hands over to the runtime binary, a wrapper runs the runtime's own MCP
client against the stub instead of a full gateway, and saves what it saw.
"""

import json
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from api.domains.agents.builders.hermes import build_hermes_config_map, build_hermes_gateway_config
from api.domains.agents.builders.openclaw import build_config_map, build_openclaw_gateway_config
from api.domains.mcp_servers import runtime as mcp_runtime
from api.domains.mcp_servers.models import McpServerScope, OrganizationMcpServer
from api.runtime_tests.memory_helpers import AGENT_ID, ORG_ID

STUB = Path(__file__).parent / "fixtures" / "mcp_gateway_stub.py"
TOKEN = "mcp-contract-gateway-token"
PORT = 18765
ALIAS = "mcp-gateway"
GATEWAY_URL = f"http://{ALIAS}:{PORT}/gateway/v1"


@dataclass
class RuntimeRun:
    completed: subprocess.CompletedProcess
    out_dir: Path
    requests: list[dict]

    def output(self, name: str) -> str:
        path = self.out_dir / name
        return path.read_text() if path.exists() else ""


def _server(identifier: str, **fields) -> OrganizationMcpServer:
    return OrganizationMcpServer(
        organization_id=ORG_ID,
        identifier=identifier,
        name=identifier.title(),
        url="https://mcp.example.com/mcp",
        scope=McpServerScope.ALL_AGENTS.value,
        credentials_encrypted="unused",
        **fields,
    )


_ARGS = (
    AGENT_ID,
    ORG_ID,
    "agent-farm",
    "Test soul.",
    "Test identity.",
    "Template user.",
    "Test tools.",
    "Test agents.",
)


def _config_map(runtime: str, servers: list[OrganizationMcpServer]) -> dict[str, str]:
    if runtime == "hermes":
        config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000")
        config["mcp_servers"] = mcp_runtime.hermes_mcp_servers(servers, GATEWAY_URL)
        return build_hermes_config_map(*_ARGS, "", "", config).data
    overlay = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000")
    overlay["mcp"] = {"servers": mcp_runtime.openclaw_mcp_servers(servers, GATEWAY_URL)}
    return build_config_map(*_ARGS, "", "", "", overlay).data


# The start script ends by handing over to the runtime binary; these wrappers take that
# hand-over and run the runtime's own MCP client instead, then save the merged config.
_HERMES_WRAPPER = """#!/bin/sh
/opt/hermes/bin/hermes mcp test "$MCP_CONTRACT_SERVER" > /contract-out/mcp-test.txt 2>&1
cp /opt/data/config.yaml /contract-out/config.yaml
"""
_OPENCLAW_WRAPPER = """#!/bin/sh
case "$1" in
  --version) echo "OpenClaw 2026.8.2" ;;
  plugins|doctor) exit 0 ;;
  gateway)
    /usr/local/bin/openclaw mcp probe "$MCP_CONTRACT_SERVER" --json > /contract-out/probe.json 2>/contract-out/probe.err
    cp /home/node/.openclaw/openclaw.json /contract-out/openclaw.json ;;
  *) exit 0 ;;
esac
"""


def start_runtime(
    runtime: str,
    image: str,
    root: Path,
    servers: list[OrganizationMcpServer],
    *,
    probe: str,
    saved_openclaw_config: dict | None = None,
) -> RuntimeRun:
    config_dir, state_dir, commands_dir, out_dir = (root / name for name in ("config", "state", "commands", "out"))
    for directory in (config_dir, state_dir, commands_dir, out_dir):
        directory.mkdir()
        directory.chmod(0o777)
    for name, content in _config_map(runtime, servers).items():
        (config_dir / name).write_text(content)
    if saved_openclaw_config is not None:
        (state_dir / "openclaw.json").write_text(json.dumps(saved_openclaw_config))
        (state_dir / "openclaw.json").chmod(0o666)
    wrapper = commands_dir / runtime
    wrapper.write_text(_HERMES_WRAPPER if runtime == "hermes" else _OPENCLAW_WRAPPER)
    wrapper.chmod(0o755)
    log = out_dir / "gateway.jsonl"
    log.touch()
    log.chmod(0o666)
    shutil.copy(STUB, commands_dir / STUB.name)

    suffix = uuid.uuid4().hex[:10]
    network, stub = f"mcp-contract-{suffix}", f"mcp-stub-{suffix}"
    subprocess.run(["docker", "network", "create", network], check=True, capture_output=True)
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                stub,
                "--network",
                network,
                "--network-alias",
                ALIAS,
                "-v",
                f"{commands_dir}:/contract-commands:ro",
                "-v",
                f"{out_dir}:/contract-out",
                "--entrypoint",
                "python3",
                image,
                f"/contract-commands/{STUB.name}",
                str(PORT),
                "/contract-out/gateway.jsonl",
                TOKEN,
            ],
            check=True,
            capture_output=True,
        )
        time.sleep(1)
        mount = "/opt/data" if runtime == "hermes" else "/home/node/.openclaw"
        command = [
            "docker",
            "run",
            "--rm",
            "--network",
            network,
            "--entrypoint",
            "sh",
            "-v",
            f"{config_dir}:/app/config:ro",
            "-v",
            f"{state_dir}:{mount}",
            "-v",
            f"{commands_dir}:/contract-commands:ro",
            "-v",
            f"{out_dir}:/contract-out",
            "-e",
            "PATH=/contract-commands:/opt/hermes/bin:/opt/hermes/.venv/bin:/usr/local/bin:/usr/bin:/bin",
            "-e",
            "AGENTBARN_SCHEDULED_DELIVERY=0",
            "-e",
            "HERMES_HOME=/opt/data",
            "-e",
            f"{mcp_runtime.GATEWAY_TOKEN_ENV}={TOKEN}",
            "-e",
            f"MCP_CONTRACT_SERVER={probe}",
        ]
        if runtime == "hermes":
            workspace = state_dir / "workspace"
            workspace.mkdir()
            workspace.chmod(0o777)
            command += ["-v", f"{workspace}:/workspace"]
        command += [image, "/app/config/start.sh"]
        completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=240)
    finally:
        subprocess.run(["docker", "rm", "-f", stub], check=False, capture_output=True)
        subprocess.run(["docker", "network", "rm", network], check=False, capture_output=True)
        # The runtime writes as its own user; let the test's tmp_path cleanup remove it.
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--user",
                "0",
                "--entrypoint",
                "sh",
                "-v",
                f"{root}:/root-dir",
                image,
                "-c",
                "chmod -R a+rwX /root-dir",
            ],
            check=False,
            capture_output=True,
        )
    requests = [json.loads(line) for line in log.read_text().splitlines() if line.strip()]
    return RuntimeRun(completed=completed, out_dir=out_dir, requests=requests)


server = _server

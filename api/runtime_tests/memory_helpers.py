"""Start generated memory-enabled runtimes and observe their actual HTTP consumers."""

import json
import os
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import UUID

import pytest

from api.domains.agents.builders.hermes import build_hermes_config_map, build_hermes_gateway_config
from api.domains.agents.builders.openclaw import build_config_map, build_openclaw_gateway_config
from api.tests.core.givenpy import LambdaWith

AGENT_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
ORG_ID = UUID("11111111-2222-3333-4444-555555555555")
RECALLED_FACT = "durable-memory-sentinel: Releases go out on Tuesdays."
NATIVE_FACT = "native-memory-sentinel: Use concise release notes."
NATIVE_USER = "native-user-sentinel: The user prefers plain language."
RUNTIME_KEY = "current-runtime-contract-key"
FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures" / "agent_memory"


def selected_image(runtime: str) -> str:
    name = f"{runtime.upper()}_TEST_IMAGE"
    image = os.environ.get(name)
    if not image:
        pytest.fail(f"{name} must name an already-built {runtime} image")
    subprocess.run(["docker", "image", "inspect", image], check=True, capture_output=True)
    return image


def runtime_is_present(runtime: str, image: str, root: Path):
    def step(context):
        context.runtime, context.image = runtime, image
        context.root = root
        context.config_dir = root / "config"
        context.state_dir = root / "state"
        context.commands_dir = root / "commands"
        for directory in (root, context.config_dir, context.state_dir, context.commands_dir):
            directory.mkdir(exist_ok=True)
            directory.chmod(0o777)
        native = context.state_dir / ("memories" if runtime == "hermes" else "workspace")
        native.mkdir()
        native.chmod(0o777)
        (native / "MEMORY.md").write_text(NATIVE_FACT)
        (native / "USER.md").write_text(NATIVE_USER)
        for file in native.iterdir():
            file.chmod(0o666)

        def cleanup():
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
                    f"{context.state_dir}:/state",
                    image,
                    "-c",
                    "chmod -R a+rwX /state",
                ],
                check=False,
                capture_output=True,
            )

        return LambdaWith(lambda: None, cleanup)

    return step


def memory_http_boundary_is_ready(*, health_denials: int = 0):
    def step(context):
        context.requests = []
        context.health_denials = health_denials

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.respond()

            def do_POST(self):
                self.respond()

            def do_PATCH(self):
                self.respond()

            def respond(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                payload = json.loads(body) if body else None
                context.requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "payload": payload,
                    }
                )
                if self.path == "/llm/v1/chat/completions" and isinstance(payload, dict) and payload.get("stream"):
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    self.end_headers()
                    for delta, finish_reason in (
                        ({"role": "assistant", "content": "Memory contract response."}, None),
                        ({}, "stop"),
                    ):
                        chunk = {
                            "id": "contract-completion",
                            "object": "chat.completion.chunk",
                            "created": 1,
                            "model": "memory-contract-model",
                            "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
                        }
                        self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    self.wfile.write(b"data: [DONE]\n\n")
                    return
                status, response = self.response_for(payload)
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

            def response_for(self, payload):
                if self.path == "/llm/v1/chat/completions":
                    return 200, {
                        "id": "contract-completion",
                        "object": "chat.completion",
                        "created": 1,
                        "model": "memory-contract-model",
                        "choices": [
                            {
                                "index": 0,
                                "finish_reason": "stop",
                                "message": {
                                    "role": "assistant",
                                    "content": "Memory contract response.",
                                },
                            }
                        ],
                        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                    }
                if self.headers.get("Authorization") != f"Bearer {RUNTIME_KEY}":
                    return 401, {"detail": "Unauthorized"}
                if self.path == "/memory/v1/health":
                    if context.health_denials:
                        context.health_denials -= 1
                        return 401, {"detail": "Credential not yet persisted"}
                    return 200, {"status": "ok"}
                if self.path == "/memory/v1/version":
                    return 200, {"version": "0.10.2"}
                if self.path == "/memory/v1/organization-memory":
                    return 202, {"status": "accepted"}
                if self.path.endswith("/memories/recall"):
                    return 200, {"results": [{"id": str(AGENT_ID), "text": RECALLED_FACT, "type": "world"}]}
                if self.path.endswith("/memories") and self.command == "POST":
                    return 200, {"success": True, "bank_id": "agentbarn", "items_count": 1, "async": True}
                return 403, {"detail": "Forbidden"}

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        context.base_url = f"http://127.0.0.1:{server.server_port}"

        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join()

        return LambdaWith(thread.start, cleanup)

    return step


def runtime_memory_is_configured(*, enabled: bool):
    def step(context):
        configure_memory(context, enabled=enabled)

    return step


def stale_memory_settings_are_present():
    def step(context):
        if context.runtime == "hermes":
            target = context.state_dir / "hindsight" / "config.json"
            target.parent.mkdir()
            target.parent.chmod(0o777)
            target.write_text(
                json.dumps(
                    {
                        "mode": "cloud",
                        "api_url": "http://127.0.0.1:9",
                        "api_key": "stale-runtime-contract-key",
                        "auto_recall": False,
                    }
                )
            )
        else:
            target = context.state_dir / "openclaw.json"
            target.write_text(
                json.dumps(
                    {
                        "plugins": {
                            "entries": {
                                "hindsight-openclaw": {
                                    "enabled": True,
                                    "config": {
                                        "hindsightApiToken": "stale-runtime-contract-key",
                                        "bankMission": "Stale mission",
                                        "autoRecall": False,
                                    },
                                }
                            }
                        }
                    }
                )
            )
        target.chmod(0o666)

    return step


def configure_memory(context, *, enabled: bool):
    context.memory_enabled = enabled
    args = (
        AGENT_ID,
        ORG_ID,
        "agent-farm",
        "Test soul.",
        "Test identity.",
        "Template user.",
        "Test tools.",
        "Test agents.",
        "",
        "",
    )
    if context.runtime == "hermes":
        config = build_hermes_gateway_config("litellm/gpt-5", "http://litellm:4000", memory_enabled=enabled)
        config_map = build_hermes_config_map(*args, config)
        driver = "hermes_runtime_driver.py"
        command = "#!/bin/sh\nexec python3 /contract-commands/hermes_runtime_driver.py\n"
    else:
        config = build_openclaw_gateway_config("litellm/gpt-5", "http://litellm:4000", memory_enabled=enabled)
        config_map = build_config_map(*args[:-1], "", args[-1], config)
        driver = "openclaw_runtime_driver.mjs"
        # Channel installation is unrelated to memory; the driver uses the real core loader.
        command = (
            '#!/bin/sh\ncase "$1" in\n'
            '  --version) echo "OpenClaw 2026.8.2" ;;\n'
            "  plugins|doctor) exit 0 ;;\n"
            "  gateway) exec node /contract-commands/openclaw_runtime_driver.mjs ;;\n  *) exit 0 ;;\nesac\n"
        )
    for name, content in config_map.data.items():
        target = context.config_dir / name
        target.write_text(content)
        target.chmod(0o644)
    shutil.copy(FIXTURES / driver, context.commands_dir / driver)
    wrapper = context.commands_dir / context.runtime
    wrapper.write_text(command)
    wrapper.chmod(0o755)


def start_memory_runtime(context):
    mount = "/opt/data" if context.runtime == "hermes" else "/home/node/.openclaw"
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "host",
        "--entrypoint",
        "sh",
        "-v",
        f"{context.config_dir}:/app/config:ro",
        "-v",
        f"{context.state_dir}:{mount}",
        "-v",
        f"{context.commands_dir}:/contract-commands:ro",
        "-e",
        "PATH=/contract-commands:/opt/hermes/bin:/opt/hermes/.venv/bin:/usr/local/bin:/usr/bin:/bin",
        "-e",
        "AGENTBARN_SCHEDULED_DELIVERY=0",
        "-e",
        "HERMES_HOME=/opt/data",
        "-e",
        f"CONTRACT_MODEL_URL={context.base_url}/llm/v1",
    ]
    if context.runtime == "hermes":
        workspace = context.state_dir / "workspace"
        workspace.mkdir(exist_ok=True)
        workspace.chmod(0o777)
        command += ["-v", f"{workspace}:/workspace"]
    if context.memory_enabled:
        command += ["-e", f"MEMORY_URL={context.base_url}/memory/v1", "-e", f"MEMORY_API_KEY={RUNTIME_KEY}"]
    command += [context.image, "/app/config/start.sh"]
    completed = subprocess.run(command, check=False, capture_output=True, text=True, timeout=120)
    context.completed = completed
    context.result = {}
    for line in completed.stdout.splitlines():
        if line.startswith("MEMORY_RUNTIME_CONTRACT="):
            context.result = json.loads(line.removeprefix("MEMORY_RUNTIME_CONTRACT="))
    return completed


def memory_requests(context):
    return [request for request in context.requests if request["path"].startswith("/memory/v1/")]

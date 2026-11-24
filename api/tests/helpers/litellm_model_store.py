import json
import socket
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from testcontainers.postgres import PostgresContainer

from api.tests.core.givenpy import LambdaWith

IMAGE = "ghcr.io/berriai/litellm:v1.108.6"
MASTER_KEY = "sk-model-store-contract-master"
SALT_KEY = "model-store-contract-salt"
REPOSITORY_CONFIG = Path(__file__).resolve().parents[3] / "docker" / "litellm" / "config.yaml"
OPENROUTER_API_BASE = "https://openrouter.ai/api/v1"
READY_TIMEOUT_SECONDS = 120
COMPLETION = {
    "id": "gen-contract",
    "object": "chat.completion",
    "created": 1,
    "model": "openai/gpt-4o-mini",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}],
    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
}


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


class ChatCompletionsStub:
    """An OpenAI-compatible chat endpoint that records each request's key and model and sends `reply`."""

    def __init__(self):
        self.keys: list[str] = []
        self.models: list[str] = []
        self.reply: dict = COMPLETION
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                posted = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
                stub.keys.append(self.headers.get("Authorization", "").removeprefix("Bearer "))
                stub.models.append(posted.get("model"))
                body = json.dumps(stub.reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", _free_port()), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/api/v1"


def chat_stub_is_running():
    def step(context):
        stub = ChatCompletionsStub()
        context.chat_stub = stub
        thread = threading.Thread(target=stub.server.serve_forever, daemon=True)

        def stop():
            stub.server.shutdown()
            stub.server.server_close()

        return LambdaWith(thread.start, stop)

    return step


def _wait_until_ready(url: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            if httpx.get(f"{url}/health/readiness", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise AssertionError("Pinned LiteLLM did not become ready")


def pinned_litellm_runs_the_repository_config(openrouter_api_key: str):
    """The repository's LiteLLM config with its OpenRouter route pointed at `context.chat_stub`, using the
    price list bundled in the image."""

    def step(context):
        source = REPOSITORY_CONFIG.read_text(encoding="utf-8")
        assert source.count(OPENROUTER_API_BASE) == 1, "The repository config no longer has one OpenRouter route"
        database = PostgresContainer("postgres:16")
        directory = tempfile.TemporaryDirectory()
        config_file = Path(directory.name) / "config.yaml"
        config_file.write_text(source.replace(OPENROUTER_API_BASE, context.chat_stub.url), encoding="utf-8")
        context.litellm_container = None

        def start():
            database.start()
            port = _free_port()
            context.litellm_url = f"http://127.0.0.1:{port}"
            environment = {
                "DATABASE_URL": database.get_connection_url().replace("+psycopg2", ""),
                "LITELLM_MASTER_KEY": MASTER_KEY,
                "LITELLM_SALT_KEY": SALT_KEY,
                "OPENROUTER_API_KEY": openrouter_api_key,
                "LITELLM_LOCAL_MODEL_COST_MAP": "true",
            }
            context.litellm_container = subprocess.run(
                [
                    "docker",
                    "run",
                    "-d",
                    "--network",
                    "host",
                    "-v",
                    f"{config_file}:/contract.yaml:ro",
                    *[argument for name, value in environment.items() for argument in ("-e", f"{name}={value}")],
                    IMAGE,
                    "--config",
                    "/contract.yaml",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            _wait_until_ready(context.litellm_url)

        def stop():
            if context.litellm_container:
                subprocess.run(["docker", "rm", "-f", context.litellm_container], check=False, capture_output=True)
            database.stop()
            directory.cleanup()

        return LambdaWith(start, stop)

    return step


def restart_litellm(context) -> None:
    subprocess.run(["docker", "restart", context.litellm_container], check=True, capture_output=True)
    _wait_until_ready(context.litellm_url)

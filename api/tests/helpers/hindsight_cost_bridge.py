"""Observe the pinned Hindsight provider's actual outgoing model requests."""

import json
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from api.tests.core.givenpy import LambdaWith

ROOT = Path(__file__).resolve().parents[3]
IMAGE = "ghcr.io/vectorize-io/hindsight:0.10.2"


def hindsight_cost_boundary_is_ready():
    def step(context):
        exists = subprocess.run(["docker", "image", "inspect", IMAGE], check=False, capture_output=True)
        if exists.returncode:
            subprocess.run(["docker", "pull", IMAGE], check=True, capture_output=True)
        context.model_requests = []
        context.settings_unavailable = False
        context.selected_model = "openrouter/contract/first"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if context.settings_unavailable:
                    self.send_response(503)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                payload = {"model": context.selected_model}
                bank = parse_qs(urlsplit(self.path).query).get("bank", [None])[0]
                if bank:
                    payload["api_key"] = f"memory-key-{bank}"
                self.wfile.write(json.dumps(payload).encode())

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                if self.path == "/settings":
                    context.selected_model = payload.get("model", context.selected_model)
                    context.settings_unavailable = payload.get("unavailable", False)
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"{}")
                    return
                payload["authorization"] = self.headers.get("Authorization")
                context.model_requests.append(payload)
                response = {
                    "id": "contract-model-response",
                    "object": "chat.completion",
                    "created": 1,
                    "model": "memory-cost-contract-model",
                    "choices": [
                        {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "{}"}}
                    ],
                    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode())

            def log_message(self, format, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context.model_url = f"http://127.0.0.1:{server.server_port}/v1"
        thread = threading.Thread(target=server.serve_forever, daemon=True)

        def cleanup():
            server.shutdown()
            server.server_close()
            thread.join()

        return LambdaWith(thread.start, cleanup)

    return step


def run_hindsight_cost_driver(context, *, dynamic_model=False):
    context.completed = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--network",
            "host",
            "--entrypoint",
            "/app/api/.venv/bin/python",
            "-v",
            f"{ROOT / 'helm/hindsight/files'}:/opt/agentbarn:ro",
            "-v",
            f"{ROOT / 'api/tests/fixtures/agent_memory'}:/contract:ro",
            "-e",
            f"CONTRACT_URL={context.model_url}",
            *(
                ["-e", f"CONTRACT_SETTINGS_URL={context.model_url.removesuffix('/v1')}/settings"]
                if dynamic_model
                else []
            ),
            IMAGE,
            "/contract/hindsight_cost_driver.py",
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=90,
    )

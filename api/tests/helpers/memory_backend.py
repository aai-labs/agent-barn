import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import uvicorn
from starlette.testclient import TestClient

from api.core.config import get_config
from api.memory_app import create_memory_app
from api.tests.core.givenpy import LambdaWith


def memory_gateway_is_ready():
    """A real HTTP boundary records what the gateway sends upstream."""

    def step(context):
        context.backend_requests = []
        context.backend_status = 200
        context.backend_response = {"accepted": True}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.respond()

            def do_POST(self):
                self.respond()

            def respond(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                context.backend_requests.append(
                    {
                        "method": self.command,
                        "path": self.path,
                        "authorization": self.headers.get("Authorization"),
                        "payload": json.loads(body) if body else None,
                    }
                )
                self.send_response(context.backend_status)
                self.send_header("Content-Type", "application/json")
                self.send_header("X-Backend-Secret", "must-not-forward")
                self.end_headers()
                self.wfile.write(json.dumps(context.backend_response).encode())

            def log_message(self, format: str, *args: object) -> None:
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        config = get_config()
        previous_url, previous_key = config.hindsight_base_url, config.hindsight_api_key

        def open_gateway():
            config.hindsight_base_url = f"http://127.0.0.1:{server.server_port}"
            config.hindsight_api_key = "gateway-upstream-test-key"
            thread.start()
            context.memory_client = TestClient(create_memory_app(context.injector))

        def close_gateway():
            context.memory_client.close()
            server.shutdown()
            server.server_close()
            thread.join()
            config.hindsight_base_url, config.hindsight_api_key = previous_url, previous_key

        return LambdaWith(open_gateway, close_gateway)

    return step


def memory_viewer_is_served():
    """Serves the gateway over HTTP so the product API's viewer client crosses a real boundary.

    Use after `memory_gateway_is_ready`, which supplies the recording Hindsight stand-in.
    """

    def step(context):
        config = get_config()
        previous_url = config.memory_view_base_url
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(create_memory_app(context.injector), host="127.0.0.1", port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)

        def open_viewer():
            thread.start()
            deadline = time.monotonic() + 10
            while not server.started and time.monotonic() < deadline:
                time.sleep(0.02)
            config.memory_view_base_url = f"http://127.0.0.1:{port}/memory/view/v1"
            context.viewer_port = port

        def close_viewer():
            server.should_exit = True
            thread.join()
            config.memory_view_base_url = previous_url

        return LambdaWith(open_viewer, close_viewer)

    return step

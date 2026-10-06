import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to

SCRIPT = Path(__file__).parents[2] / "domains/agents/scripts/agentbarn_memory.py"


@pytest.mark.parametrize("status", [202, 403])
def test_explicit_shared_write_sends_only_content_and_uses_runtime_credential(status):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(
                (
                    self.path,
                    self.headers["Authorization"],
                    json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                )
            )
            self.send_response(status)
            self.end_headers()
            self.wfile.write(b'{"status":"accepted"}' if status == 202 else b'{"detail":"private backend error"}')

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = subprocess.run(
            [sys.executable, str(SCRIPT), "remember-organization"],
            input="The organization uses EUR invoices.",
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
            env={
                **os.environ,
                "MEMORY_URL": f"http://127.0.0.1:{server.server_port}/memory/v1",
                "MEMORY_API_KEY": "runtime-key",
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    assert_that(
        requests,
        equal_to(
            [
                (
                    "/memory/v1/organization-memory",
                    "Bearer runtime-key",
                    {"content": "The organization uses EUR invoices."},
                )
            ]
        ),
    )
    assert_that(result.returncode, equal_to(0 if status == 202 else 1))
    assert_that(
        result.stdout if status == 202 else result.stderr,
        contains_string("asynchronous" if status == 202 else "write access is required"),
    )
    assert_that("private backend error" in result.stdout + result.stderr, equal_to(False))

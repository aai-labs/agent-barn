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


@pytest.mark.parametrize("thorough", [False, True])
@pytest.mark.parametrize(
    "status,response,expected",
    [
        (
            200,
            {"results": [{"text": "Billing uses EUR.", "metadata": {"secret": "hidden"}}]},
            {"status": "found", "memories": ["Billing uses EUR."]},
        ),
        (200, {"results": []}, {"status": "not_found", "memories": []}),
        (503, {"detail": "private backend error"}, {"status": "unavailable"}),
        (200, {"unexpected": "private backend error"}, {"status": "unavailable"}),
    ],
)
def test_explicit_recall_reports_search_outcome_without_backend_metadata(thorough, status, response, expected):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            requests.append(
                {
                    "path": self.path,
                    "authorization": self.headers["Authorization"],
                    "payload": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                }
            )
            self.send_response(status)
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

        def log_message(self, format: str, *args: object) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        command = [sys.executable, str(SCRIPT), "recall"] + (["--thorough"] if thorough else [])
        result = subprocess.run(
            command,
            input="Billing invoice currency",
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
                {
                    "path": "/memory/v1/v1/default/banks/agentbarn/memories/recall",
                    "authorization": "Bearer runtime-key",
                    "payload": {
                        "query": "Billing invoice currency",
                        "budget": "high" if thorough else "mid",
                        "max_tokens": 8192 if thorough else 4096,
                        "types": ["world", "experience", "observation"],
                    },
                }
            ]
        ),
    )
    assert_that(json.loads(result.stdout), equal_to(expected))
    assert_that(result.returncode, equal_to(1 if expected["status"] == "unavailable" else 0))
    assert_that("private backend error" in result.stdout + result.stderr, equal_to(False))

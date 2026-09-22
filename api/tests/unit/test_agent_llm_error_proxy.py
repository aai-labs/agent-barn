"""The in-pod proxy is the only thing that shapes what an Agent's user sees when a
model call fails, so both runtimes are exercised for real here rather than mocked.

A budget rejection arrives as a 400 whose error type is `budget_exceeded`, and its
upstream text names an internal team id — replacing it is the point.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, not_

_SCRIPTS = Path(__file__).resolve().parents[2] / "domains" / "agents" / "scripts"
_HERMES = _SCRIPTS / "hermes" / "healthz-server.py"
_OPENCLAW = _SCRIPTS / "openclaw" / "healthz-server.js"

BUDGET_BODY = {
    "error": {
        "message": "Budget has been exceeded! Team=01a0a4cc-eed2-7420-aba6-05a48119f48c "
        "Current cost: 0.011985, Max budget: 0.01",
        "type": "budget_exceeded",
        "param": None,
        "code": "400",
    }
}
UNKNOWN_MODEL_BODY = {"error": {"message": "model 'nope' not found", "type": "invalid_request_error"}}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def _upstream(status: int, payload: dict):
    """Stands in for the proxy that would answer the Agent's model call."""

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = HTTPServer(("127.0.0.1", _free_port()), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def _wait_for(port: int) -> None:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError("proxy did not start")


@contextmanager
def _proxy(runtime: str, target: str):
    healthz_port, proxy_port = _free_port(), _free_port()
    env = {
        **os.environ,
        "HEALTHZ_PORT": str(healthz_port),
        "LITELLM_PROXY_TARGET": target,
        "LLM_PROXY_PORT": str(proxy_port),
    }
    if runtime == "hermes":
        command = [sys.executable, str(_HERMES)]
    else:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is required to exercise the OpenClaw proxy")
        command = [node, str(_OPENCLAW)]
    proc = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_for(proxy_port)
        yield f"http://127.0.0.1:{proxy_port}"
    finally:
        proc.terminate()
        proc.wait(timeout=5)


def _post(base: str) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{base}/chat/completions", data=b"{}", headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
@pytest.mark.parametrize("upstream_status", [400, 429])
def test_a_budget_rejection_is_rewritten_for_the_user(runtime, upstream_status):
    """Observed as a 400 on v1.96.2 and documented as a 429; both must be caught, or a
    proxy upgrade silently starts leaking the team id again."""
    with _upstream(upstream_status, BUDGET_BODY) as target, _proxy(runtime, target) as proxy:
        status, body = _post(proxy)
    assert_that(status, equal_to(upstream_status))
    message = body["error"]["message"]
    assert_that(message, contains_string("reached its model spend limit"))
    # The upstream text names the Organization's internal team id; it must not reach
    # whoever is talking to the Agent.
    assert_that(message, not_(contains_string("01a0a4cc")))
    assert_that(message, not_(contains_string("Team=")))


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_other_400s_keep_their_own_error(runtime):
    """400 also covers malformed requests and unknown models, which the runtime and
    the user both need to see as themselves."""
    with _upstream(400, UNKNOWN_MODEL_BODY) as target, _proxy(runtime, target) as proxy:
        status, body = _post(proxy)
    assert_that(status, equal_to(400))
    assert_that(body["error"]["message"], equal_to("model 'nope' not found"))


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_a_successful_call_passes_through_untouched(runtime):
    with _upstream(200, {"choices": [{"message": {"content": "hi"}}]}) as target, _proxy(runtime, target) as proxy:
        status, body = _post(proxy)
    assert_that(status, equal_to(200))
    assert_that(body["choices"][0]["message"]["content"], equal_to("hi"))

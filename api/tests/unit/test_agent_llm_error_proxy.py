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
# An Agent's own limit: same error type, but the upstream text names the key instead.
KEY_BUDGET_BODY = {
    "error": {
        "message": "Budget has been exceeded! Key=88dc28d0f030c55ed4ab77ed8faf098196cb1c05df778539800c9f1243fe6b4b "
        "Spend=20.01, Max budget=20.0",
        "type": "budget_exceeded",
        "param": None,
        "code": "429",
    }
}
# Neutral on purpose: the same rejection comes back whether the Agent's own limit or
# its Organization's ran out, and nothing in-pod can tell them apart reliably.
SPEND_LIMIT_MESSAGE = (
    "This agent has reached its model spend limit. "
    "Contact your administrator to raise it or wait for the limit to reset."
)
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
@pytest.mark.parametrize("upstream_status", [400, 422, 429])
def test_a_budget_rejection_is_rewritten_for_the_user(runtime, upstream_status):
    """Observed as a 400, documented as a 429, and 422 by default on LiteLLM releases
    after the pinned one; all must be caught, or a proxy upgrade silently starts
    leaking the team id again."""
    with _upstream(upstream_status, BUDGET_BODY) as target, _proxy(runtime, target) as proxy:
        status, body = _post(proxy)
    # Always 402, whatever the proxy answered: both runtimes retry a 429 as a rate
    # limit, indefinitely, so the person chatting would never hear back at all.
    assert_that(status, equal_to(402))
    message = body["error"]["message"]
    assert_that(message, equal_to(SPEND_LIMIT_MESSAGE))
    # The upstream text names the Organization's internal team id; it must not reach
    # whoever is talking to the Agent.
    assert_that(message, not_(contains_string("01a0a4cc")))
    assert_that(message, not_(contains_string("Team=")))


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_an_agents_own_limit_running_out_is_rewritten_too(runtime):
    """The key-level rejection names the key's hash; it must not reach the user either."""
    with _upstream(429, KEY_BUDGET_BODY) as target, _proxy(runtime, target) as proxy:
        status, body = _post(proxy)
    assert_that(status, equal_to(402))
    assert_that(body["error"]["message"], equal_to(SPEND_LIMIT_MESSAGE))


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_an_ordinary_rate_limit_is_still_a_429(runtime):
    """Only a spent limit becomes terminal; a real rate limit must stay retryable."""
    rate_limited = {"error": {"message": "Rate limit reached", "type": "rate_limit_error"}}
    with _upstream(429, rate_limited) as target, _proxy(runtime, target) as proxy:
        status, body = _post(proxy)
    assert_that(status, equal_to(429))
    assert_that(body["error"]["message"], equal_to("Rate limit reached"))


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

"""The in-pod proxy is the only thing that shapes what an Agent's user sees when a
model call fails, so both runtimes are exercised for real here rather than mocked.

A budget rejection arrives as a 400 whose error type is `budget_exceeded`, and its
upstream text names an internal team id — replacing it is the point.
"""

import itertools
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import contextmanager
from enum import StrEnum
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, not_, starts_with

_SCRIPTS = Path(__file__).resolve().parents[2] / "domains" / "agents" / "scripts"
_HERMES = _SCRIPTS / "hermes" / "healthz-server.py"
_OPENCLAW = _SCRIPTS / "openclaw" / "healthz-server.js"
_START_ATTEMPTS = 3
_START_TIMEOUT_SECONDS = 15
_PORT_IN_USE_MARKERS = ("EADDRINUSE", "Address already in use", "Errno 98", "WinError 10048")

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
    "A model spend limit has been reached, so this agent cannot reply right now. "
    "Contact your administrator to raise it or wait for the limit to renew."
)
# On credit there is no limit beneath the balance, so the reply says what to do about it.
CREDIT_MESSAGE = (
    "This organization has used all its credit, so this agent cannot reply right now. "
    "Ask the organization's owner to add more credit."
)
PROVIDER_OUT_OF_CREDIT_MESSAGE = (
    "The model provider's account has run out of credit. Ask a Platform Administrator to add credit."
)
PROVIDER_OUT_OF_CREDIT_BODY = {"error": {"message": "Insufficient credits", "type": "insufficient_quota"}}
UNKNOWN_MODEL_BODY = {"error": {"message": "model 'nope' not found", "type": "invalid_request_error"}}

_COUNT_START = """
import os, pathlib, socket, sys, time
starts = pathlib.Path(os.environ["STARTS_FILE"])
count = len(starts.read_text()) if starts.exists() else 0
starts.write_text("x" * (count + 1))
"""
_PORT_TAKEN_THEN_LISTEN = (
    _COUNT_START
    + """
if count == 0:
    sys.stderr.write("OSError: [Errno 98] Address already in use\\n")
    sys.stderr.flush()
    time.sleep(60)
server = socket.create_server(("127.0.0.1", int(os.environ["PORT"])))
while True:
    server.accept()[0].close()
"""
)
_CRASH = (
    _COUNT_START
    + """
sys.stderr.write("boom")
sys.exit(3)
"""
)


# Readiness is "something accepts on the child's port", so the port must be one nothing
# else can be on. A port from bind(0) is released before the child binds it, and under
# pytest-xdist another worker's bind(0) (say, a stand-in upstream answering 400) can take it
# first: the child then fails to bind while that stranger answers in its place. So each
# worker picks from a range of its own below every OS's ephemeral range (Linux 32768+,
# macOS 49152+), where neither the OS nor another worker hands out ports.
_PORT_RANGE_START = 20_000
_PORTS_PER_WORKER = 300  # 40 workers fit below 32768
_next_port = itertools.count()


def _worker_index() -> int:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "")
    return int(worker.removeprefix("gw")) if worker.startswith("gw") else 0


def _free_port() -> int:
    base = _PORT_RANGE_START + (_worker_index() % 40) * _PORTS_PER_WORKER
    for _ in range(_PORTS_PER_WORKER):
        port = base + next(_next_port) % _PORTS_PER_WORKER
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
            except OSError:
                continue  # still held by an earlier child of this worker
        return port
    raise RuntimeError(f"no free port in {base}-{base + _PORTS_PER_WORKER - 1}")


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

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


class _Start(StrEnum):
    READY = "ready"
    PORT_IN_USE = "port in use"
    EXITED = "exited"
    TIMED_OUT = "timed out"


def _accepts(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


def _port_in_use(log: Path) -> bool:
    text = log.read_text(errors="replace")
    return any(marker in text for marker in _PORT_IN_USE_MARKERS)


def _wait_until_started(proc: subprocess.Popen, port: int, log: Path) -> _Start:
    deadline = time.monotonic() + _START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _accepts(port):
            return _Start.READY
        if _port_in_use(log):
            return _Start.PORT_IN_USE
        if proc.poll() is not None:
            return _Start.PORT_IN_USE if _port_in_use(log) else _Start.EXITED
        time.sleep(0.1)
    return _Start.TIMED_OUT


def _stop(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.terminate()
    proc.wait(timeout=5)


@contextmanager
def _launch(command: list[str], env_for: Callable[[], tuple[dict[str, str], int]]):
    """Start ``command`` and yield the port it listens on.

    ``env_for`` picks fresh ports per attempt. A picked port can be taken by another
    process before the child binds it, so a start that fails on a taken port is retried;
    any other failure raises at once with the child's stderr.
    """
    with tempfile.TemporaryDirectory() as logs:
        stderr = ""
        for attempt in range(_START_ATTEMPTS):
            env, port = env_for()
            log = Path(logs) / f"attempt-{attempt}.log"
            with log.open("wb") as sink:
                proc = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=sink)
            try:
                start = _wait_until_started(proc, port, log)
                if start is _Start.READY:
                    yield port
                    return
            finally:
                _stop(proc)
            stderr = log.read_text(errors="replace")
            if start is not _Start.PORT_IN_USE:
                raise RuntimeError(f"{command[-1]} did not start ({start.value}): {stderr}")
        raise RuntimeError(f"{command[-1]} did not start after {_START_ATTEMPTS} taken ports: {stderr}")


@contextmanager
def _proxy(runtime: str, target: str, extra_env: dict[str, str] | None = None):
    if runtime == "hermes":
        command = [sys.executable, str(_HERMES)]
    else:
        node = shutil.which("node")
        if node is None:
            pytest.skip("node is required to exercise the OpenClaw proxy")
        command = [node, str(_OPENCLAW)]

    def env_for() -> tuple[dict[str, str], int]:
        proxy_port = _free_port()
        env = {
            **os.environ,
            "HEALTHZ_PORT": str(_free_port()),
            "LITELLM_PROXY_TARGET": target,
            "LLM_PROXY_PORT": str(proxy_port),
            **(extra_env or {}),
        }
        return env, proxy_port

    with _launch(command, env_for) as proxy_port:
        yield f"http://127.0.0.1:{proxy_port}"


def _post(base: str, path: str = "/chat/completions", payload: bytes = b"{}") -> tuple[int, dict]:
    request = urllib.request.Request(f"{base}{path}", data=payload, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as error:
        return error.code, json.loads(error.read())


def _post_stream(base: str) -> tuple[int, str, list[str]]:
    request = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps({"model": "litellm/m", "stream": True, "messages": []}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        text = response.read().decode()
        events = [line.removeprefix("data: ") for line in text.splitlines() if line.startswith("data: ")]
        return response.status, response.headers.get("Content-Type", ""), events


def test_a_childs_port_is_this_workers_own_and_never_one_the_os_hands_out(monkeypatch):
    """Under xdist a port the OS gave someone else (bind(0)) once answered in place of
    the proxy; a child's port must come from the worker's own range below them."""
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw3")
    start = _PORT_RANGE_START + 3 * _PORTS_PER_WORKER

    ports = [_free_port() for _ in range(_PORTS_PER_WORKER + 5)]

    assert_that(all(start <= port < start + _PORTS_PER_WORKER for port in ports), equal_to(True))
    assert_that(max(ports) < 32_768, equal_to(True))


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
@pytest.mark.parametrize("upstream_status", [400, 422, 429])
def test_a_budget_rejection_is_rewritten_for_the_user(runtime, upstream_status):
    """Observed as a 400, documented as a 429, and 422 by default on LiteLLM releases
    after the pinned one; all must be caught, or a proxy upgrade silently starts
    leaking the team id again."""
    with _upstream(upstream_status, BUDGET_BODY) as target, _proxy(runtime, target) as proxy:
        status, body = _post(proxy)
    # Answered as an ordinary completion, never the upstream 429 (which both runtimes
    # retry as a rate limit, indefinitely) nor an error (which native chat replaces
    # with the runtime's own billing text): the native channel posts the notice itself.
    assert_that(status, equal_to(200))
    message = body["choices"][0]["message"]["content"]
    assert_that(message, equal_to(SPEND_LIMIT_MESSAGE))
    assert_that(body["choices"][0]["finish_reason"], equal_to("stop"))
    # The upstream text names the Organization's internal team id; it must not reach
    # whoever is talking to the Agent.
    assert_that(message, not_(contains_string("01a0a4cc")))
    assert_that(message, not_(contains_string("Team=")))


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_running_out_of_credit_says_to_add_more_and_is_recorded_as_such(runtime, tmp_path):
    marker = tmp_path / "marker.json"
    extra = {"AGENTBARN_SPEND_LIMIT_KIND": "credit", "AGENTBARN_LLM_ERROR_MARKER": str(marker)}
    with _upstream(400, BUDGET_BODY) as target, _proxy(runtime, target, extra) as proxy:
        status, body = _post(proxy)
        recorded = json.loads(marker.read_text())
    # The same ordinary reply as a spent limit, worded for credit.
    assert_that(status, equal_to(200))
    assert_that(body["choices"][0]["message"]["content"], equal_to(CREDIT_MESSAGE))
    assert_that(recorded["code"], equal_to("CREDIT_EXHAUSTED"))


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_a_spent_limit_is_recorded_as_such_off_credit(runtime, tmp_path):
    marker = tmp_path / "marker.json"
    with (
        _upstream(400, BUDGET_BODY) as target,
        _proxy(runtime, target, {"AGENTBARN_LLM_ERROR_MARKER": str(marker)}) as proxy,
    ):
        _post(proxy)
        recorded = json.loads(marker.read_text())
    assert_that(recorded["code"], equal_to("SPEND_LIMIT_REACHED"))


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_an_agents_own_limit_running_out_is_rewritten_too(runtime):
    """The key-level rejection names the key's hash; it must not reach the user either."""
    with _upstream(429, KEY_BUDGET_BODY) as target, _proxy(runtime, target) as proxy:
        status, body = _post(proxy)
    assert_that(status, equal_to(200))
    assert_that(body["choices"][0]["message"]["content"], equal_to(SPEND_LIMIT_MESSAGE))


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_a_streamed_completion_gets_the_notice_as_a_stream(runtime):
    """Native runtimes stream their completions; the notice must arrive in that format."""
    with _upstream(429, BUDGET_BODY) as target, _proxy(runtime, target) as proxy:
        status, content_type, events = _post_stream(proxy)
    assert_that(status, equal_to(200))
    assert_that(content_type, starts_with("text/event-stream"))
    assert_that(events[-1], equal_to("[DONE]"))
    chunks = [json.loads(event) for event in events[:-1]]
    text = "".join(chunk["choices"][0]["delta"].get("content") or "" for chunk in chunks)
    assert_that(text, equal_to(SPEND_LIMIT_MESSAGE))
    assert_that(chunks[-1]["choices"][0]["finish_reason"], equal_to("stop"))
    assert_that(chunks[0]["model"], equal_to("litellm/m"))


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_a_spent_limit_outside_chat_completions_stays_a_terminal_402(runtime):
    """Only a chat completion can carry the notice as a reply; anything else keeps the
    terminal 402 so the runtime does not retry it as a rate limit."""
    with _upstream(429, BUDGET_BODY) as target, _proxy(runtime, target) as proxy:
        status, body = _post(proxy, path="/embeddings")
    assert_that(status, equal_to(402))
    assert_that(body["error"]["message"], equal_to(SPEND_LIMIT_MESSAGE))


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_a_provider_out_of_credit_is_answered_without_naming_a_provider(runtime):
    with _upstream(402, PROVIDER_OUT_OF_CREDIT_BODY) as target, _proxy(runtime, target) as proxy:
        status, body = _post(proxy)
    assert_that(status, equal_to(402))
    assert_that(body["error"]["message"], equal_to(PROVIDER_OUT_OF_CREDIT_MESSAGE))


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


def _stand_in_env(starts: Path):
    def env_for() -> tuple[dict[str, str], int]:
        port = _free_port()
        return {**os.environ, "PORT": str(port), "STARTS_FILE": str(starts)}, port

    return env_for


def test_launch_retries_with_fresh_ports_when_the_port_is_taken(tmp_path):
    starts = tmp_path / "starts"

    with _launch([sys.executable, "-c", _PORT_TAKEN_THEN_LISTEN], _stand_in_env(starts)) as port:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            pass

    assert_that(starts.read_text(), equal_to("xx"))


def test_launch_reports_a_crash_with_its_stderr_without_retrying(tmp_path):
    starts = tmp_path / "starts"
    started = time.monotonic()

    with pytest.raises(RuntimeError, match="boom"):
        with _launch([sys.executable, "-c", _CRASH], _stand_in_env(starts)):
            pass

    assert_that(time.monotonic() - started < _START_TIMEOUT_SECONDS, equal_to(True))
    assert_that(starts.read_text(), equal_to("x"))

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
from hamcrest import assert_that, contains_string, equal_to, not_

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
def _proxy(runtime: str, target: str):
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
        }
        return env, proxy_port

    with _launch(command, env_for) as proxy_port:
        yield f"http://127.0.0.1:{proxy_port}"


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

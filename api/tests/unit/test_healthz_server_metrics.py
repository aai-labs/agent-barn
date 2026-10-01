import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, not_

_SCRIPT = Path(__file__).resolve().parents[2] / "domains" / "agents" / "scripts" / "hermes" / "healthz-server.py"
_START_ATTEMPTS = 3
_START_TIMEOUT_SECONDS = 10
_PORT_IN_USE_MARKERS = ("EADDRINUSE", "Address already in use", "Errno 98", "WinError 10048")
_EXIT_ON_TAKEN_PORT_THEN_SERVE = """
import os, pathlib, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
starts = pathlib.Path(os.environ["STARTS_FILE"])
count = len(starts.read_text()) if starts.exists() else 0
starts.write_text("x" * (count + 1))
if count == 0:
    sys.stderr.write("OSError: [Errno 98] Address already in use\\n")
    sys.exit(1)

class Ready(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass

HTTPServer(("127.0.0.1", int(os.environ["HEALTHZ_PORT"])), Ready).serve_forever()
"""


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _Start(StrEnum):
    READY = "ready"
    PORT_IN_USE = "port in use"
    EXITED = "exited"
    TIMED_OUT = "timed out"


def _ready(base: str) -> bool:
    try:
        urllib.request.urlopen(f"{base}/ready", timeout=1)
        return True
    except urllib.error.URLError, ConnectionError:
        return False


def _port_in_use(log: Path) -> bool:
    text = log.read_text(errors="replace")
    return any(marker in text for marker in _PORT_IN_USE_MARKERS)


def _wait_until_started(proc: subprocess.Popen, base: str, log: Path) -> _Start:
    deadline = time.monotonic() + _START_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if _ready(base):
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
    """Start ``command`` and yield its base URL once ``/ready`` answers.

    ``env_for`` picks a fresh port per attempt. A picked port can be taken by another
    process before the child binds it, so a start that fails on a taken port is retried;
    any other failure raises at once with the child's stderr.
    """
    with tempfile.TemporaryDirectory() as logs:
        stderr = ""
        for attempt in range(_START_ATTEMPTS):
            env, port = env_for()
            base = f"http://127.0.0.1:{port}"
            log = Path(logs) / f"attempt-{attempt}.log"
            with log.open("wb") as sink:
                proc = subprocess.Popen(command, env=env, stdout=subprocess.DEVNULL, stderr=sink)
            try:
                start = _wait_until_started(proc, base, log)
                if start is _Start.READY:
                    yield base
                    return
            finally:
                _stop(proc)
            stderr = log.read_text(errors="replace")
            if start is not _Start.PORT_IN_USE:
                raise RuntimeError(f"{command[-1]} did not start ({start.value}): {stderr}")
        raise RuntimeError(f"{command[-1]} did not start after {_START_ATTEMPTS} taken ports: {stderr}")


@contextmanager
def _run_healthz_server(env_overrides: dict[str, str] | None = None):
    def env_for() -> tuple[dict[str, str], int]:
        port = _free_port()
        return {**os.environ, "HEALTHZ_PORT": str(port), **(env_overrides or {})}, port

    with _launch([sys.executable, str(_SCRIPT)], env_for) as base:
        yield base


@pytest.fixture
def healthz_server():
    with _run_healthz_server() as base:
        yield base


def _get(url: str):
    try:
        response = urllib.request.urlopen(url, timeout=5)
        return response.status, dict(response.headers), response.read().decode()
    except urllib.error.HTTPError as err:
        return err.code, dict(err.headers), err.read().decode()


def test_metrics_endpoint_returns_prometheus_text(healthz_server):
    status, headers, body = _get(f"{healthz_server}/metrics")

    assert_that(status, equal_to(200))
    assert_that(headers["Content-Type"], contains_string("text/plain"))
    # Hermes runtime is unreachable in the test, so the agent is not healthy
    # and has never connected.
    assert_that(body, contains_string("agent_healthz_ok 0"))
    assert_that(body, contains_string("agent_healthz_ever_connected 0"))
    assert_that(body, not_(contains_string("tokens_ok")))


def test_metrics_endpoint_declares_gauge_types(healthz_server):
    _, _, body = _get(f"{healthz_server}/metrics")

    assert_that(body, contains_string("# TYPE agent_healthz_ok gauge"))
    assert_that(body, contains_string("# TYPE agent_healthz_ever_connected gauge"))


def test_healthz_endpoint_still_reports_starting(healthz_server):
    status, _, body = _get(f"{healthz_server}/healthz")

    assert_that(status, equal_to(503))
    assert_that(body, contains_string("starting"))


def test_live_endpoint_ignores_provider_gateway_state(tmp_path):
    (tmp_path / "gateway_state.json").write_text(
        '{"platforms":{"discord":{"state":"paused","error_message":"connection timed out"}}}',
        encoding="utf-8",
    )

    with _run_healthz_server({"HERMES_HOME": str(tmp_path)}) as base:
        status, _, body = _get(f"{base}/live")

    assert_that(status, equal_to(200))
    assert_that(body, contains_string('"live": true'))


def test_unknown_path_still_returns_404(healthz_server):
    status, _, _ = _get(f"{healthz_server}/nope")

    assert_that(status, equal_to(404))


def test_launch_retries_with_a_fresh_port_when_the_server_exits_on_a_taken_port(tmp_path):
    starts = tmp_path / "starts"

    def env_for() -> tuple[dict[str, str], int]:
        port = _free_port()
        return {**os.environ, "HEALTHZ_PORT": str(port), "STARTS_FILE": str(starts)}, port

    with _launch([sys.executable, "-c", _EXIT_ON_TAKEN_PORT_THEN_SERVE], env_for) as base:
        status, _, _ = _get(f"{base}/ready")

    assert_that(status, equal_to(200))
    assert_that(starts.read_text(), equal_to("xx"))

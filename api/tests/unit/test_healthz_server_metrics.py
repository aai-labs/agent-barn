import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, not_

_SCRIPT = Path(__file__).resolve().parents[2] / "domains" / "agents" / "scripts" / "hermes" / "healthz-server.py"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextmanager
def _run_healthz_server(env_overrides: dict[str, str] | None = None):
    port = _free_port()
    env = {
        **os.environ,
        "HEALTHZ_PORT": str(port),
        **(env_overrides or {}),
    }
    proc = subprocess.Popen(
        [sys.executable, str(_SCRIPT)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                urllib.request.urlopen(f"{base}/ready", timeout=1)
                break
            except urllib.error.URLError, ConnectionError:
                if time.monotonic() > deadline:
                    raise TimeoutError("healthz server did not start")
                time.sleep(0.1)
        yield base
    finally:
        proc.terminate()
        proc.wait(timeout=5)


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

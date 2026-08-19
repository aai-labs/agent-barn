import importlib.util
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to

_SCRIPT = Path(__file__).resolve().parents[2] / "domains" / "agents" / "scripts" / "hermes" / "healthz-server.py"


@pytest.fixture
def healthz_module():
    spec = importlib.util.spec_from_file_location("hermes_healthz_server", _SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load Hermes health server")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def healthz_server():
    port = _free_port()
    env = {
        **os.environ,
        "SKIP_SLACK_TOKEN_VALIDATION": "1",
        "HEALTHZ_PORT": str(port),
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
    # Hermes gateway is unreachable in the test, so the agent is not healthy
    # and has never connected; Slack validation is skipped so tokens read ok.
    assert_that(body, contains_string("agent_healthz_ok 0"))
    assert_that(body, contains_string("agent_healthz_ever_connected 0"))
    assert_that(body, contains_string("agent_slack_tokens_ok 1"))


def test_metrics_endpoint_declares_gauge_types(healthz_server):
    _, _, body = _get(f"{healthz_server}/metrics")

    assert_that(body, contains_string("# TYPE agent_healthz_ok gauge"))
    assert_that(body, contains_string("# TYPE agent_healthz_ever_connected gauge"))
    assert_that(body, contains_string("# TYPE agent_slack_tokens_ok gauge"))


def test_healthz_endpoint_still_reports_starting(healthz_server):
    status, _, body = _get(f"{healthz_server}/healthz")

    assert_that(status, equal_to(503))
    assert_that(body, contains_string("starting"))


def test_unknown_path_still_returns_404(healthz_server):
    status, _, _ = _get(f"{healthz_server}/nope")

    assert_that(status, equal_to(404))


def test_missing_discord_token_has_platform_specific_error(healthz_module):
    assert_that(
        healthz_module._check_discord_token(""),
        equal_to((False, "No Discord bot token was provided.")),
    )

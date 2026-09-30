import ast
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_entries, has_key, is_not, not_
from prometheus_client.parser import text_string_to_metric_families

_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "domains" / "agents" / "scripts"
_SCRIPTS = {
    "hermes": _SCRIPTS_DIR / "hermes" / "healthz-server.py",
    "openclaw": _SCRIPTS_DIR / "openclaw" / "healthz-server.js",
}
_RUNTIMES = list(_SCRIPTS)
_HERMES_IMAGE_FILES = [
    _SCRIPTS["hermes"],
    Path(__file__).resolve().parents[1] / "fixtures" / "hermes_healthz_metrics_driver.py",
]

# A real cgroup v2 sample from a running agent container (1Gi / 0.5 core limits).
_CGROUP_FILES = {
    "memory.current": "442335232\n",
    "memory.max": "1073741824\n",
    "memory.stat": "anon 263245824\nfile 15556608\ninactive_file 83718144\nactive_file 1000\n",
    "cpu.stat": (
        "usage_usec 73445876\nuser_usec 65000000\nsystem_usec 8445876\n"
        "core_sched.force_idle_usec 0\nnr_periods 35702\nnr_throttled 664\n"
        "throttled_usec 12345678\nnr_bursts 0\nburst_usec 0\n"
    ),
    "cpu.max": "50000 100000\n",
}
_EXPECTED_SAMPLES = {
    "agent_cgroup_metrics_available": 1.0,
    "agent_memory_working_set_bytes": 358617088.0,  # 442335232 - 83718144
    "agent_memory_limit_bytes": 1073741824.0,
    "agent_cpu_usage_seconds_total": 73.445876,
    "agent_cpu_limit_cores": 0.5,
    "agent_cpu_periods_total": 35702.0,
    "agent_cpu_throttled_periods_total": 664.0,
}
_RESOURCE_SAMPLE_NAMES = set(_EXPECTED_SAMPLES)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _command(runtime: str) -> list[str]:
    script = str(_SCRIPTS[runtime])
    if runtime == "hermes":
        return [sys.executable, script]
    node = shutil.which("node")
    # A missing node must fail rather than skip (docs/guidelines/testing.md).
    assert node is not None, "node is required to test the OpenClaw healthz server"
    return [node, script]


@contextmanager
def _run_healthz_server(runtime: str = "hermes", env_overrides: dict[str, str] | None = None):
    port = _free_port()
    env = {
        **os.environ,
        "HEALTHZ_PORT": str(port),
        **(env_overrides or {}),
    }
    proc = subprocess.Popen(
        _command(runtime),
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


def _write_cgroup(root: Path, overrides: dict[str, str | None] | None = None) -> Path:
    """Write the sample files; an override of None leaves that file out."""
    for name, content in {**_CGROUP_FILES, **(overrides or {})}.items():
        if content is not None:
            (root / name).write_text(content, encoding="utf-8")
    return root


def _metrics(runtime: str, cgroup_root: Path) -> tuple[int, str]:
    with _run_healthz_server(runtime, {"HEALTHZ_CGROUP_ROOT": str(cgroup_root)}) as base:
        status, _, body = _get(f"{base}/metrics")
    return status, body


def _samples(body: str) -> dict[str, float]:
    """Parsing with prometheus_client also proves the exposition text is valid."""
    return {
        sample.name: sample.value
        for family in text_string_to_metric_families(body)
        for sample in family.samples
        if sample.name.startswith("agent_")
    }


def _resource_samples(body: str) -> dict[str, float]:
    return {name: value for name, value in _samples(body).items() if name in _RESOURCE_SAMPLE_NAMES}


def _declarations(body: str) -> list[str]:
    return [line for line in body.splitlines() if line.startswith(("# HELP", "# TYPE"))]


@pytest.mark.parametrize("path", _HERMES_IMAGE_FILES, ids=lambda path: path.name)
def test_files_that_run_in_the_hermes_image_parse_on_its_python(path):
    # The image runs Python 3.13, older than this suite, and ruff formats for the suite's
    # version. It would turn `except (A, B):` into the 3.14-only `except A, B:`, which is
    # a SyntaxError in the pod. The per-file target versions in pyproject.toml prevent that
    # for the scripts; this catches a file they do not cover.
    ast.parse(path.read_text(encoding="utf-8"), filename=str(path), feature_version=(3, 13))


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

    with _run_healthz_server("hermes", {"HERMES_HOME": str(tmp_path)}) as base:
        status, _, body = _get(f"{base}/live")

    assert_that(status, equal_to(200))
    assert_that(body, contains_string('"live": true'))


def test_unknown_path_still_returns_404(healthz_server):
    status, _, _ = _get(f"{healthz_server}/nope")

    assert_that(status, equal_to(404))


@pytest.mark.parametrize("runtime", _RUNTIMES)
def test_resource_metrics_report_cgroup_values(runtime, tmp_path):
    status, body = _metrics(runtime, _write_cgroup(tmp_path))

    assert_that(status, equal_to(200))
    assert_that(_resource_samples(body), equal_to(_EXPECTED_SAMPLES))
    assert_that(body, contains_string("# TYPE agent_cpu_usage_seconds_total counter"))
    assert_that(body, contains_string("# TYPE agent_memory_working_set_bytes gauge"))


@pytest.mark.parametrize("runtime", _RUNTIMES)
def test_health_series_stay_first_and_unchanged(runtime, tmp_path):
    _, body = _metrics(runtime, _write_cgroup(tmp_path))

    assert_that(body.startswith("# HELP agent_healthz_ok "), equal_to(True))
    assert_that(_samples(body), has_entries(agent_healthz_ok=0.0, agent_healthz_ever_connected=0.0))


@pytest.mark.parametrize("runtime", _RUNTIMES)
def test_unlimited_limits_are_left_out(runtime, tmp_path):
    root = _write_cgroup(tmp_path, {"memory.max": "max\n", "cpu.max": "max 100000\n"})

    _, body = _metrics(runtime, root)

    expected = {
        name: value
        for name, value in _EXPECTED_SAMPLES.items()
        if name not in ("agent_memory_limit_bytes", "agent_cpu_limit_cores")
    }
    assert_that(_resource_samples(body), equal_to(expected))


@pytest.mark.parametrize("runtime", _RUNTIMES)
def test_unreadable_cgroup_reports_unavailable_and_keeps_serving(runtime, tmp_path):
    status, body = _metrics(runtime, tmp_path)

    assert_that(status, equal_to(200))
    assert_that(_resource_samples(body), equal_to({"agent_cgroup_metrics_available": 0.0}))
    assert_that(_samples(body), has_key("agent_healthz_ok"))


@pytest.mark.parametrize("runtime", _RUNTIMES)
def test_missing_inactive_file_drops_the_working_set(runtime, tmp_path):
    root = _write_cgroup(tmp_path, {"memory.stat": "anon 263245824\nfile 15556608\n"})

    _, body = _metrics(runtime, root)

    samples = _resource_samples(body)
    assert_that(samples["agent_cgroup_metrics_available"], equal_to(0.0))
    assert_that(samples, is_not(has_key("agent_memory_working_set_bytes")))
    assert_that(samples["agent_cpu_usage_seconds_total"], equal_to(73.445876))


@pytest.mark.parametrize("runtime", _RUNTIMES)
def test_malformed_cgroup_lines_are_ignored(runtime, tmp_path):
    root = _write_cgroup(
        tmp_path,
        {"cpu.stat": "garbage\nusage_usec 100\nnr_periods 10 extra\nnr_throttled -1\n"},
    )

    _, body = _metrics(runtime, root)

    samples = _resource_samples(body)
    assert_that(samples["agent_cgroup_metrics_available"], equal_to(1.0))
    assert_that(samples["agent_cpu_usage_seconds_total"], equal_to(0.0001))
    assert_that(samples, is_not(has_key("agent_cpu_periods_total")))
    assert_that(samples, is_not(has_key("agent_cpu_throttled_periods_total")))


def test_both_runtimes_expose_identical_declarations_and_values(tmp_path):
    root = _write_cgroup(tmp_path)

    _, hermes = _metrics("hermes", root)
    _, openclaw = _metrics("openclaw", root)

    assert_that(_declarations(openclaw), equal_to(_declarations(hermes)))
    assert_that(_resource_samples(openclaw), equal_to(_resource_samples(hermes)))

"""The Resource usage queries against a real Prometheus, fed by the real healthz script.

The unit tests pin the PromQL as strings. Only a Prometheus can say that the strings parse,
that `or` keeps every tagged sub-query, and that the labels a scrape adds are the ones the
queries select on. So this runs the shipped Hermes healthz server over a fake cgroup
directory, has a Prometheus scrape it under the same job and labels the monitoring chart's
`agent` job adds (`app`, `org_id`) with basic auth switched on as in a deploy, and reads it
back through PrometheusClient.

Needs Docker, like the rest of the integration suite. The image pin matches
helm/monitoring/tests/run.sh.
"""

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import bcrypt
import pytest
from testcontainers.core.container import DockerContainer

from api.core.config import get_config
from api.domains.resource_usage.models import ResourceUsageRange, UsageWindow
from api.domains.resource_usage.repository import ResourceUsageRepository
from api.infrastructure.prometheus.client import PrometheusClient, PrometheusError

_IMAGE = os.environ.get("TESTCONTAINERS_PROMETHEUS_IMAGE", "prom/prometheus:v3.5.0")
_PASSWORD = "contractPassw0rd123"
_SCRIPT = Path(__file__).resolve().parents[2] / "domains" / "agents" / "scripts" / "hermes" / "healthz-server.py"

_MEMORY_WORKING_SET = 442_335_232 - 83_718_144
_MEMORY_LIMIT = 1_073_741_824
_STATIC_CGROUP = {
    "memory.current": "442335232\n",
    "memory.max": f"{_MEMORY_LIMIT}\n",
    "memory.stat": "anon 263245824\ninactive_file 83718144\n",
    "cpu.max": "50000 100000\n",
}


_GiB = 1024**3
_AGENT_ONE = UUID("01a00000-0000-7000-8000-000000000001")
_AGENT_TWO = UUID("01a00000-0000-7000-8000-000000000002")
_AGENT_GONE = UUID("01a00000-0000-7000-8000-000000000003")
# An Agent's pods are named after its Deployment, then a ReplicaSet and a pod hash. Agent one
# has two, as in a rollout: the old one still Running and the new one Pending.
_POD_ONE = f"agent-{_AGENT_ONE}-6d9c7b8f5-abcde"
_POD_ONE_NEW = f"agent-{_AGENT_ONE}-7f6d5c4b3-fghij"
_POD_TWO = f"agent-{_AGENT_TWO}-5c8b9d7f4-klmno"
_POD_GONE = f"agent-{_AGENT_GONE}-5c8b9d7f4-pqrst"
# A restore job's pod is not an Agent's, whatever it asks for.
_POD_JOB = f"rp-cap-{_AGENT_ONE}-xyz12"
# What kube-state-metrics says about a namespace's pods, in the shape it says it. Worked out
# so the sums below are not a coincidence. A quota charges a pod the larger of its containers
# added up and its biggest init container, so the pods are chosen to show each way it goes:
#   agent-a  init container is bigger for memory limits and for CPU requests, smaller for the others
#   two      two containers that add up, and an init container that is smaller
#   waiting  Pending, so it counts
#   done     Succeeded, so it does not, whatever it asks for
_KSM_METRICS = f"""\
# TYPE kube_pod_container_resource_limits gauge
kube_pod_container_resource_limits{{namespace="ns",pod="agent-a",container="agent",resource="memory",unit="byte"}} {2 * _GiB}
kube_pod_container_resource_limits{{namespace="ns",pod="agent-a",container="agent",resource="cpu",unit="core"}} 0.5
kube_pod_container_resource_limits{{namespace="ns",pod="two",container="main",resource="memory",unit="byte"}} {_GiB}
kube_pod_container_resource_limits{{namespace="ns",pod="two",container="sidecar",resource="memory",unit="byte"}} {_GiB // 2}
kube_pod_container_resource_limits{{namespace="ns",pod="two",container="main",resource="cpu",unit="core"}} 0.25
kube_pod_container_resource_limits{{namespace="ns",pod="two",container="sidecar",resource="cpu",unit="core"}} 0.25
kube_pod_container_resource_limits{{namespace="ns",pod="waiting",container="agent",resource="memory",unit="byte"}} {_GiB}
kube_pod_container_resource_limits{{namespace="ns",pod="done",container="job",resource="memory",unit="byte"}} {4 * _GiB}
kube_pod_container_resource_limits{{namespace="ns",pod="done",container="job",resource="cpu",unit="core"}} 8
kube_pod_container_resource_limits{{namespace="ns",pod="agent-a",container="agent",resource="ephemeral-storage",unit="byte"}} 99
# TYPE kube_pod_init_container_resource_limits gauge
kube_pod_init_container_resource_limits{{namespace="ns",pod="agent-a",container="fix",resource="memory",unit="byte"}} {3 * _GiB}
kube_pod_init_container_resource_limits{{namespace="ns",pod="agent-a",container="fix",resource="cpu",unit="core"}} 0.25
kube_pod_init_container_resource_limits{{namespace="ns",pod="two",container="setup",resource="memory",unit="byte"}} {_GiB}
kube_pod_init_container_resource_limits{{namespace="ns",pod="two",container="setup2",resource="memory",unit="byte"}} {_GiB // 4}
kube_pod_init_container_resource_limits{{namespace="ns",pod="agent-a",container="fix",resource="ephemeral-storage",unit="byte"}} 99999
# TYPE kube_pod_container_resource_requests gauge
kube_pod_container_resource_requests{{namespace="ns",pod="agent-a",container="agent",resource="memory",unit="byte"}} {_GiB // 2}
kube_pod_container_resource_requests{{namespace="ns",pod="agent-a",container="agent",resource="cpu",unit="core"}} 0.1
kube_pod_container_resource_requests{{namespace="ns",pod="two",container="main",resource="memory",unit="byte"}} {_GiB // 4}
kube_pod_container_resource_requests{{namespace="ns",pod="two",container="sidecar",resource="memory",unit="byte"}} {_GiB // 4}
kube_pod_container_resource_requests{{namespace="ns",pod="two",container="main",resource="cpu",unit="core"}} 0.05
kube_pod_container_resource_requests{{namespace="ns",pod="two",container="sidecar",resource="cpu",unit="core"}} 0.05
kube_pod_container_resource_requests{{namespace="ns",pod="waiting",container="agent",resource="memory",unit="byte"}} {_GiB // 8}
kube_pod_container_resource_requests{{namespace="ns",pod="done",container="job",resource="memory",unit="byte"}} {2 * _GiB}
kube_pod_container_resource_requests{{namespace="ns",pod="done",container="job",resource="cpu",unit="core"}} 4
kube_pod_container_resource_requests{{namespace="ns",pod="{_POD_ONE}",container="agent",resource="memory",unit="byte"}} {_GiB // 2}
kube_pod_container_resource_requests{{namespace="ns",pod="{_POD_ONE}",container="agent",resource="cpu",unit="core"}} 0.1
kube_pod_container_resource_requests{{namespace="ns",pod="{_POD_ONE_NEW}",container="agent",resource="memory",unit="byte"}} {_GiB // 2}
kube_pod_container_resource_requests{{namespace="ns",pod="{_POD_ONE_NEW}",container="agent",resource="cpu",unit="core"}} 0.1
kube_pod_container_resource_requests{{namespace="ns",pod="{_POD_TWO}",container="agent",resource="memory",unit="byte"}} {_GiB // 4}
kube_pod_container_resource_requests{{namespace="ns",pod="{_POD_TWO}",container="agent",resource="cpu",unit="core"}} 0.2
kube_pod_container_resource_requests{{namespace="ns",pod="{_POD_GONE}",container="agent",resource="memory",unit="byte"}} {8 * _GiB}
kube_pod_container_resource_requests{{namespace="ns",pod="{_POD_GONE}",container="agent",resource="cpu",unit="core"}} 8
kube_pod_container_resource_requests{{namespace="ns",pod="{_POD_JOB}",container="archive",resource="memory",unit="byte"}} {_GiB}
kube_pod_container_resource_requests{{namespace="ns",pod="{_POD_JOB}",container="archive",resource="cpu",unit="core"}} 0.3
# TYPE kube_pod_init_container_resource_requests gauge
kube_pod_init_container_resource_requests{{namespace="ns",pod="agent-a",container="fix",resource="memory",unit="byte"}} {_GiB // 4}
kube_pod_init_container_resource_requests{{namespace="ns",pod="agent-a",container="fix",resource="cpu",unit="core"}} 0.4
kube_pod_init_container_resource_requests{{namespace="ns",pod="{_POD_ONE}",container="fix",resource="memory",unit="byte"}} {3 * _GiB // 4}
kube_pod_init_container_resource_requests{{namespace="ns",pod="{_POD_ONE}",container="fix",resource="cpu",unit="core"}} 0.05
# TYPE kube_pod_status_phase gauge
kube_pod_status_phase{{namespace="ns",pod="agent-a",phase="Running"}} 1
kube_pod_status_phase{{namespace="ns",pod="agent-a",phase="Pending"}} 0
kube_pod_status_phase{{namespace="ns",pod="two",phase="Running"}} 1
kube_pod_status_phase{{namespace="ns",pod="two",phase="Succeeded"}} 0
kube_pod_status_phase{{namespace="ns",pod="waiting",phase="Pending"}} 1
kube_pod_status_phase{{namespace="ns",pod="waiting",phase="Running"}} 0
kube_pod_status_phase{{namespace="ns",pod="done",phase="Succeeded"}} 1
kube_pod_status_phase{{namespace="ns",pod="done",phase="Running"}} 0
kube_pod_status_phase{{namespace="ns",pod="{_POD_ONE}",phase="Running"}} 1
kube_pod_status_phase{{namespace="ns",pod="{_POD_ONE_NEW}",phase="Pending"}} 1
kube_pod_status_phase{{namespace="ns",pod="{_POD_TWO}",phase="Running"}} 1
kube_pod_status_phase{{namespace="ns",pod="{_POD_GONE}",phase="Succeeded"}} 1
kube_pod_status_phase{{namespace="ns",pod="{_POD_JOB}",phase="Running"}} 1
"""
# Live pods only, each charged the larger of its containers and its init container:
#   limits   agent-a 3 GiB (init) + two 1.5 GiB + waiting 1 GiB;  agent-a 0.5 (containers) + two 0.5 cores
#   requests the earlier pods 1.125 GiB and 0.5 cores, plus the Agent pods and the restore job:
#            agent one's old pod 0.75 GiB (init) and 0.1, its new pod 0.5 GiB and 0.1, agent two 0.25 GiB
#            and 0.2, and the restore job 1 GiB and 0.3. The Succeeded Agent pod is out.
_COMMITTED = {
    "limits": {"memory": float(3 * _GiB + _GiB + _GiB // 2 + _GiB), "cpu": 1.0},
    "requests": {
        "memory": float(_GiB // 2 + _GiB // 2 + _GiB // 8 + 3 * _GiB // 4 + _GiB // 2 + _GiB // 4 + _GiB),
        "cpu": 1.2,
    },
}
# What each Agent's pods request, by the Agent: pods are matched to Agents by name, a rollout's two
# pods count once by the larger, and the job and the finished pod are not Agents' requests.
_AGENT_REQUESTS = {
    _AGENT_ONE: {"memory_request_bytes": float(3 * _GiB // 4), "cpu_request_cores": 0.1},
    _AGENT_TWO: {"memory_request_bytes": float(_GiB // 4), "cpu_request_cores": 0.2},
}


class _KsmHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        body = _KSM_METRICS.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


def _cpu_stat(tick: int) -> str:
    """Half a core busy, and the container held back in 2 of every 5 scheduling periods."""
    return f"usage_usec {1_000_000 + tick * 250_000}\nnr_periods {1000 + tick * 5}\nnr_throttled {250 + tick * 2}\n"


def _replace(path: Path, text: str) -> None:
    """Atomic, so a scrape never reads a half-written file and sees a gap that is not there."""
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)


class _Ticker(threading.Thread):
    """Keeps the counters moving, so a rate has something to measure."""

    def __init__(self, cgroup: Path):
        super().__init__(daemon=True)
        self._cgroup = cgroup
        self._stop_event = threading.Event()
        self._tick = 0

    def run(self) -> None:
        while not self._stop_event.wait(0.5):
            self._tick += 1
            _replace(self._cgroup / "cpu.stat", _cpu_stat(self._tick))

    def stop(self) -> None:
        self._stop_event.set()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _wait_until[T](check: Callable[[], T | None], what: str, timeout: float = 90.0) -> T:
    deadline = time.monotonic() + timeout
    last: Exception | None = None
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (PrometheusError, urllib.error.URLError, ConnectionError) as exc:
            last = exc  # still starting up
        time.sleep(0.5)
    raise AssertionError(f"timed out waiting for {what}" + (f" (last error: {last})" if last else ""))


def _client(url: str, password: str = _PASSWORD) -> PrometheusClient:
    config = get_config().model_copy(
        update={
            "prometheus_url": url,
            "prometheus_username": "monitoring",
            "prometheus_password": password,
            "prometheus_timeout_seconds": 10.0,
        }
    )
    return PrometheusClient(config=config)


@dataclass(frozen=True)
class Scraped:
    url: str
    repository: ResourceUsageRepository
    org_id: UUID
    agent_id: UUID
    other_org_id: UUID
    other_agent_id: UUID


def _now() -> datetime:
    return datetime.now(UTC)


def _current(scraped: Scraped, org: UUID, agents: list[UUID]) -> dict[UUID, dict[str, float]]:
    return scraped.repository.current_fields(org, agents, at=_now(), window_seconds=86400, throttle_window_seconds=3600)


@pytest.fixture(scope="module")
def scraped(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Scraped]:
    work = tmp_path_factory.mktemp("prometheus-contract")
    cgroup = work / "cgroup"
    cgroup.mkdir()
    for name, text in _STATIC_CGROUP.items():
        (cgroup / name).write_text(text, encoding="utf-8")
    _replace(cgroup / "cpu.stat", _cpu_stat(0))

    org_id, agent_id, other_org_id, other_agent_id = uuid4(), uuid4(), uuid4(), uuid4()
    port = _free_port()
    # Stands in for kube-state-metrics, which Prometheus scrapes under its own job.
    ksm_port = _free_port()
    ksm = HTTPServer(("0.0.0.0", ksm_port), _KsmHandler)
    threading.Thread(target=ksm.serve_forever, daemon=True).start()
    healthz = subprocess.Popen(
        [sys.executable, str(_SCRIPT)],
        env={**os.environ, "HEALTHZ_PORT": str(port), "HEALTHZ_CGROUP_ROOT": str(cgroup)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    ticker = _Ticker(cgroup)
    try:
        _wait_until(
            lambda: urllib.request.urlopen(f"http://127.0.0.1:{port}/ready", timeout=1).status == 200, "healthz"
        )

        target = f"host.docker.internal:{port}"
        config = work / "prometheus.yml"
        # The same target under two identities: the second is another organization's agent,
        # to prove a query for the first cannot see it.
        config.write_text(
            f"""\
global:
  scrape_interval: 1s
  scrape_timeout: 1s
scrape_configs:
  - job_name: agent
    static_configs:
      - targets: ["{target}"]
        labels: {{app: "agent-{agent_id}", org_id: "{org_id}", agent_name: mine, org_name: mine}}
      - targets: ["{target}"]
        labels: {{app: "agent-{other_agent_id}", org_id: "{other_org_id}", agent_name: theirs, org_name: theirs}}
  - job_name: kube-state-metrics
    static_configs:
      - targets: ["host.docker.internal:{ksm_port}"]
""",
            encoding="utf-8",
        )
        web = work / "web.yml"
        hashed = bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt(rounds=4)).decode()
        web.write_text(f"basic_auth_users:\n  monitoring: {hashed}\n", encoding="utf-8")
        for path in (config, web):
            path.chmod(0o644)  # the image runs as `nobody`

        container = (
            DockerContainer(_IMAGE)
            .with_exposed_ports(9090)
            .with_volume_mapping(str(config), "/etc/prometheus/prometheus.yml", "ro")
            .with_volume_mapping(str(web), "/etc/prometheus/web.yml", "ro")
            .with_command(
                "--config.file=/etc/prometheus/prometheus.yml --web.config.file=/etc/prometheus/web.yml"
                " --storage.tsdb.path=/prometheus --storage.tsdb.retention.time=1h"
            )
            .with_kwargs(extra_hosts={"host.docker.internal": "host-gateway"})
        )
        with container:
            url = f"http://{container.get_container_host_ip()}:{container.get_exposed_port(9090)}"
            repository = ResourceUsageRepository(prometheus=_client(url))
            result = Scraped(url, repository, org_id, agent_id, other_org_id, other_agent_id)
            ticker.start()
            # Ready once both a gauge and a rate (which needs two scrapes) have arrived.
            _wait_until(
                lambda: (
                    {"cpu_cores", "memory_working_set_bytes", "cpu_throttled_ratio"}
                    <= _current(result, org_id, [agent_id]).get(agent_id, {}).keys()
                ),
                "the first scrapes",
            )
            yield result
    finally:
        ksm.shutdown()
        ticker.stop()
        healthz.terminate()
        healthz.wait(timeout=5)


def test_the_queries_read_back_what_the_agent_exports(scraped: Scraped):
    fields = _current(scraped, scraped.org_id, [scraped.agent_id])[scraped.agent_id]

    assert fields["up"] == 1
    assert fields["cgroup_metrics_available"] == 1
    assert fields["memory_working_set_bytes"] == _MEMORY_WORKING_SET
    assert fields["memory_limit_bytes"] == _MEMORY_LIMIT
    assert fields["cpu_limit_cores"] == 0.5
    # Half a core is busy, but the figure is a five-minute rate over a series that is seconds
    # old: Prometheus divides the increase by the whole window, so it reads low until the
    # window fills. Here it only has to be a real, positive rate below what is busy.
    assert 0 < fields["cpu_cores"] < 0.9
    # Held back in 2 of every 5 periods.
    assert fields["cpu_throttled_ratio"] == pytest.approx(0.4, abs=0.1)


def test_the_client_authenticates_with_the_monitoring_password(scraped: Scraped):
    wrong = _client(scraped.url, password="notThePassword12345")

    with pytest.raises(PrometheusError, match="401"):
        wrong.query("up", _now())


def test_a_query_for_one_organization_cannot_see_another(scraped: Scraped):
    # The same script is scraped under both identities, so this is not an artifact of
    # missing data: each organization sees its own agent, and only its own.
    mine = _current(scraped, scraped.org_id, [scraped.agent_id])
    theirs = _current(scraped, scraped.other_org_id, [scraped.other_agent_id])
    assert set(mine) == {scraped.agent_id}
    assert set(theirs) == {scraped.other_agent_id}

    assert _current(scraped, scraped.org_id, [scraped.other_agent_id]) == {}
    assert _current(scraped, scraped.other_org_id, [scraped.agent_id]) == {}


def test_one_request_answers_for_several_agents_and_ignores_unknown_ones(scraped: Scraped):
    fields = _current(scraped, scraped.org_id, [scraped.agent_id, uuid4()])

    assert set(fields) == {scraped.agent_id}
    assert fields[scraped.agent_id]["memory_working_set_bytes"] == _MEMORY_WORKING_SET


def test_history_comes_back_as_points_along_the_window(scraped: Scraped):
    def history() -> tuple[UsageWindow, dict[str, dict[int, float]]] | None:
        now = _now()
        window = UsageWindow(
            usage_range=ResourceUsageRange.ONE_HOUR,
            start=now - timedelta(seconds=120),
            end=now,
            step_seconds=5,
        )
        series = scraped.repository.series_fields(scraped.org_id, scraped.agent_id, window)
        # The series is only seconds old, so wait until there is something to draw.
        return (window, series) if len(series.get("memory_working_set_bytes", {})) >= 3 else None

    window, series = _wait_until(history, "three points of history", timeout=60)

    memory = series["memory_working_set_bytes"]
    assert set(memory.values()) == {float(_MEMORY_WORKING_SET)}
    assert any(value > 0 for value in series["cpu_cores"].values())
    assert all(0 <= value <= 1.5 for value in series["cpu_throttled_ratio"].values())
    assert all(int(window.start.timestamp()) <= stamp <= int(window.end.timestamp()) for stamp in memory)


def test_the_platform_view_reads_every_agent_without_naming_any(scraped: Scraped):
    fields = scraped.repository.all_current_fields(at=_now(), window_seconds=86400, throttle_window_seconds=3600)

    # Both organizations' agents, from the one query, keyed by the `app` label alone.
    assert {scraped.agent_id, scraped.other_agent_id} <= set(fields)
    assert fields[scraped.agent_id]["memory_working_set_bytes"] == _MEMORY_WORKING_SET
    assert fields[scraped.other_agent_id]["memory_limit_bytes"] == _MEMORY_LIMIT


def test_the_platform_chart_adds_the_agents_up_into_one_series_per_field(scraped: Scraped):
    def history(organization: tuple[UUID, list[UUID]] | None) -> dict[str, dict[int, float]] | None:
        now = _now()
        window = UsageWindow(
            usage_range=ResourceUsageRange.ONE_HOUR,
            start=now - timedelta(seconds=120),
            end=now,
            step_seconds=5,
        )
        series = scraped.repository.combined_series(window, organization)
        return series if len(series.get("memory_working_set_bytes", {})) >= 3 else None

    everyone = _wait_until(lambda: history(None), "three points of platform history", timeout=60)
    one = _wait_until(
        lambda: history((scraped.org_id, [scraped.agent_id])), "three points of one organization's history", timeout=60
    )

    # Two agents in the same state add up to twice one agent, and the `sum` leaves one
    # series per field rather than one per agent. The two targets are first scraped a
    # moment apart, so the earliest points can hold only one of them: judge the latest
    # point, and require that nothing ever exceeds the sum of both.
    def latest(points: dict[int, float]) -> float:
        return points[max(points)]

    assert latest(everyone["memory_working_set_bytes"]) == 2.0 * _MEMORY_WORKING_SET
    assert max(everyone["memory_working_set_bytes"].values()) == 2.0 * _MEMORY_WORKING_SET
    assert set(one["memory_working_set_bytes"].values()) == {float(_MEMORY_WORKING_SET)}
    assert any(value > 0 for value in everyone["cpu_cores"].values())
    assert "cpu_throttled_ratio" not in everyone


def test_the_namespace_commitment_charges_each_live_pod_as_a_quota_does(scraped: Scraped):
    def committed() -> dict[str, dict[str, float]] | None:
        return scraped.repository.committed(at=_now()) or None

    figures = _wait_until(committed, "kube-state-metrics to be scraped")

    # Running and Pending pods are counted, a Succeeded one is not, a pod with two containers
    # adds both up, a bigger init container wins over the containers (and a smaller one does
    # not add to them), and a resource other than memory and CPU is left out.
    assert figures["limits"] == pytest.approx(_COMMITTED["limits"])
    assert figures["requests"] == pytest.approx(_COMMITTED["requests"])


def test_each_agents_requests_are_found_by_its_pod_name_and_counted_once(scraped: Scraped):
    def requests() -> dict[UUID, dict[str, float]] | None:
        return scraped.repository.agent_requests(at=_now()) or None

    found = _wait_until(requests, "kube-state-metrics to be scraped")

    # Both of agent one's pods are live, and it counts once, by the larger of the two. Agent two
    # is there. The Succeeded Agent pod is not, and neither is the restore job's pod.
    assert set(found) == set(_AGENT_REQUESTS)
    for agent_id, expected in _AGENT_REQUESTS.items():
        assert found[agent_id] == pytest.approx(expected)

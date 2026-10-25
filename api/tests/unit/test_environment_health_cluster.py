"""The rules that turn Kubernetes objects and Prometheus samples into the environment health page.

Each test builds the objects by hand, so it states exactly what the cluster said and checks
both what is shown and that nothing outside the allowlist is carried.
"""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from kubernetes.client import (
    CoreV1Event,
    V1ContainerState,
    V1ContainerStateTerminated,
    V1ContainerStateWaiting,
    V1ContainerStatus,
    V1Deployment,
    V1DeploymentSpec,
    V1DeploymentStatus,
    V1LabelSelector,
    V1ObjectMeta,
    V1ObjectReference,
    V1OwnerReference,
    V1PersistentVolumeClaim,
    V1PersistentVolumeClaimSpec,
    V1PersistentVolumeClaimStatus,
    V1Pod,
    V1PodCondition,
    V1PodStatus,
    V1PodTemplateSpec,
    V1ResourceQuota,
    V1ResourceQuotaStatus,
    V1StatefulSet,
    V1StatefulSetSpec,
    V1StatefulSetStatus,
    V1VolumeResourceRequirements,
)

from api.domains.agents.models import AgentStatus, PlatformAgentIdentity, PlatformFailedAgent
from api.domains.environment_health import cluster
from api.domains.environment_health.models import (
    CapacityLevel,
    CapacitySource,
    EnvironmentSource,
    HealthLevel,
    SourceState,
    VolumeAllocationRead,
    VolumeGroup,
    WorkloadKind,
    WorkloadsRead,
)
from api.domains.environment_health.service import overall_level
from api.domains.resource_usage.models import PlatformCapacityRead
from api.infrastructure.prometheus.client import PrometheusSample

_NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
_ACME = UUID("00000000-0000-7000-8000-0000000000aa")
_GiB = 1024**3


def _agent(name: str, status: AgentStatus = AgentStatus.RUNNING) -> PlatformAgentIdentity:
    return PlatformAgentIdentity(uuid4(), name, status, _ACME, "Acme")


def _identities(*agents: PlatformAgentIdentity) -> dict[UUID, PlatformAgentIdentity]:
    return cluster.identities_by_id(agents)


def _agent_labels(agent_id: UUID, *, org_label: str | None = None) -> dict[str, str]:
    return {
        "app": f"agent-{agent_id}",
        "org-id": org_label or str(uuid4()),
        "agentbarn.io/component": "agent",
    }


def _claim(name: str, size: str, labels: dict[str, str] | None = None, phase: str = "Bound") -> V1PersistentVolumeClaim:
    return V1PersistentVolumeClaim(
        metadata=V1ObjectMeta(name=name, labels=labels, creation_timestamp=_NOW - timedelta(days=1)),
        spec=V1PersistentVolumeClaimSpec(resources=V1VolumeResourceRequirements(requests={"storage": size})),
        status=V1PersistentVolumeClaimStatus(phase=phase),
    )


def _pod(
    name: str,
    *,
    labels: dict[str, str] | None = None,
    ready: bool = True,
    phase: str = "Running",
    restarts: int = 0,
    waiting: str | None = None,
    terminated: str | None = None,
    stopped_ago: timedelta = timedelta(minutes=5),
    age: timedelta = timedelta(hours=1),
    owner: V1OwnerReference | None = None,
    conditions: list[V1PodCondition] | None = None,
    reason: str | None = None,
) -> V1Pod:
    state = (
        V1ContainerState(waiting=V1ContainerStateWaiting(reason=waiting, message="secret token=abc"))
        if waiting
        else None
    )
    last_state = (
        V1ContainerState(
            terminated=V1ContainerStateTerminated(
                reason=terminated, exit_code=1, finished_at=_NOW - stopped_ago, message="password=hunter2"
            )
        )
        if terminated
        else None
    )
    return V1Pod(
        metadata=V1ObjectMeta(
            name=name,
            labels=labels,
            creation_timestamp=_NOW - age,
            owner_references=[owner] if owner else None,
        ),
        status=V1PodStatus(
            phase=phase,
            reason=reason,
            conditions=[V1PodCondition(type="Ready", status="True" if ready else "False"), *(conditions or [])],
            container_statuses=[
                V1ContainerStatus(
                    name="agent",
                    image="registry.example/agent:1",
                    image_id="",
                    ready=ready,
                    restart_count=restarts,
                    state=state,
                    last_state=last_state,
                )
            ],
        ),
    )


# --- volumes --------------------------------------------------------------


def test_every_claim_is_placed_by_its_agent_in_the_database():
    running, stopped = _agent("Ada"), _agent("Bob", AgentStatus.STOPPED)
    errored = _agent("Cy", AgentStatus.ERROR)
    gone = uuid4()
    claims = [
        _claim(f"agent-{running.id}", "1Gi", _agent_labels(running.id)),
        _claim(f"agent-{errored.id}", "1Gi", _agent_labels(errored.id)),
        _claim(f"agent-{stopped.id}", "1Gi", _agent_labels(stopped.id)),
        _claim(f"agent-{gone}", "1Gi", _agent_labels(gone)),
        _claim(
            f"restore-point-{uuid4()}",
            "2Gi",
            {"agentbarn.io/component": "restore-point", "agentbarn.io/agent-id": str(running.id)},
        ),
        _claim("data-postgres-app-0", "10Gi"),
    ]

    allocation = cluster.volume_allocation(claims, _identities(running, stopped, errored))

    groups = {group.group: (group.claims, group.requested_bytes) for group in allocation.groups}
    assert groups[VolumeGroup.ACTIVE_AGENTS] == (2, 2 * _GiB)
    assert groups[VolumeGroup.STOPPED_AGENTS] == (1, _GiB)
    assert groups[VolumeGroup.ORPHANED] == (1, _GiB)
    assert groups[VolumeGroup.RESTORE_POINTS] == (1, 2 * _GiB)
    assert groups[VolumeGroup.INFRASTRUCTURE] == (1, 10 * _GiB)
    assert allocation.total_claims == 6
    assert allocation.total_requested_bytes == 16 * _GiB


def test_an_agent_claim_created_before_the_current_component_label_is_still_an_agents():
    running, stopped = _agent("Ada"), _agent("Bob", AgentStatus.STOPPED)
    gone = uuid4()
    claims = [
        _claim(
            f"agent-{running.id}",
            "1Gi",
            {"app": f"agent-{running.id}", "org-id": str(_ACME), "agentfarm.io/component": "agent"},
        ),
        _claim(f"agent-{stopped.id}", "1Gi", {"app": f"agent-{stopped.id}", "org-id": str(_ACME)}),
        _claim(f"agent-{gone}", "1Gi", {"app": f"agent-{gone}"}),
        _claim("data-postgres-app-0", "10Gi", {"app": "postgres"}),
    ]

    allocation = cluster.volume_allocation(claims, _identities(running, stopped))

    groups = {group.group: group.claims for group in allocation.groups}
    assert groups[VolumeGroup.ACTIVE_AGENTS] == 1
    assert groups[VolumeGroup.STOPPED_AGENTS] == 1
    assert groups[VolumeGroup.ORPHANED] == 1
    assert groups[VolumeGroup.INFRASTRUCTURE] == 1
    assert [row.name for row in allocation.attention] == [f"agent-{gone}"]


def test_an_orphaned_or_unbound_claim_needs_a_look_and_names_only_what_is_known():
    running = _agent("Ada")
    gone = uuid4()
    claims = [
        _claim(f"agent-{running.id}", "1Gi", _agent_labels(running.id)),
        _claim(f"agent-{gone}", "1Gi", _agent_labels(gone)),
        _claim("data-redis-0", "1Gi", phase="Pending"),
    ]

    allocation = cluster.volume_allocation(claims, _identities(running))

    assert [row.name for row in allocation.attention] == [f"agent-{gone}", "data-redis-0"]
    orphan = allocation.attention[0]
    assert orphan.group == VolumeGroup.ORPHANED
    assert orphan.agent is not None and orphan.agent.agent_id == gone
    assert orphan.agent.agent_name is None and orphan.agent.organization_id is None
    assert allocation.attention[1].phase == "Pending"


def test_an_agent_is_never_placed_by_its_org_label():
    ada = _agent("Ada")
    claim = _claim(f"agent-{ada.id}", "1Gi", _agent_labels(ada.id, org_label=str(uuid4())))

    allocation = cluster.volume_allocation([_claim("x", "1Gi", phase="Pending"), claim], _identities(ada))

    pending = allocation.attention[0]
    assert pending.agent is None
    assert cluster.agent_ref(ada.id, _identities(ada)).organization_id == _ACME


def test_storage_committed_adds_up_every_claims_request():
    assert cluster.storage_committed([_claim("a", "1Gi"), _claim("b", "512Mi"), _claim("c", "nonsense")]) == 1.5 * _GiB


# --- pods -----------------------------------------------------------------


def test_a_crash_looping_agent_pod_is_named_from_the_database():
    ada = _agent("Ada")
    pods = [
        _pod(
            f"agent-{ada.id}-7d9f-abcde",
            labels={**_agent_labels(ada.id), "pod-template-hash": "7d9f"},
            ready=False,
            restarts=5,
            waiting="CrashLoopBackOff",
            terminated="OOMKilled",
            owner=V1OwnerReference(
                api_version="apps/v1", kind="ReplicaSet", name=f"agent-{ada.id}-7d9f", uid="1", controller=True
            ),
        ),
        _pod("agentbarn-api-5c-xyz"),
    ]

    workloads = cluster.workloads(pods, _identities(ada), _NOW)

    assert (workloads.pods_total, workloads.pods_ready) == (2, 1)
    [issue] = workloads.issues
    assert issue.kind == WorkloadKind.AGENT
    assert issue.workload_name == f"agent-{ada.id}"
    assert issue.agent is not None and issue.agent.agent_name == "Ada"
    assert issue.waiting_reason == "CrashLoopBackOff"
    assert issue.termination_reason == "OOMKilled"
    assert issue.repeatedly_restarting
    assert issue.last_restart_at == _NOW - timedelta(minutes=5)
    assert "hunter2" not in issue.model_dump_json() and "token" not in issue.model_dump_json()


def test_a_pod_still_starting_is_not_an_issue_and_a_finished_job_is_not_counted():
    workloads = cluster.workloads(
        [
            _pod("agentbarn-api-new", ready=False, age=timedelta(seconds=30)),
            _pod("cost-sync-29000-abc", phase="Succeeded", ready=False),
            _pod("agentbarn-ui-old", ready=False, age=timedelta(minutes=10)),
        ],
        {},
        _NOW,
    )

    assert workloads.pods_total == 2
    assert [issue.pod_name for issue in workloads.issues] == ["agentbarn-ui-old"]
    assert workloads.issues[0].kind == WorkloadKind.INFRASTRUCTURE


def test_unknown_reasons_are_dropped_and_known_failures_flag_a_ready_pod():
    workloads = cluster.workloads(
        [
            _pod("redis-1", restarts=3),
            _pod("worker-1", ready=False, waiting="SomethingNew", terminated="MysteryExit"),
            _pod(
                "litellm-1",
                ready=False,
                age=timedelta(seconds=10),
                conditions=[V1PodCondition(type="PodScheduled", status="False", reason="Unschedulable")],
            ),
            _pod("hindsight-1", phase="Failed", ready=False, reason="Evicted"),
        ],
        {},
        _NOW,
    )

    by_name = {issue.pod_name: issue for issue in workloads.issues}
    assert by_name["redis-1"].repeatedly_restarting and by_name["redis-1"].ready
    assert by_name["worker-1"].waiting_reason is None and by_name["worker-1"].termination_reason is None
    assert by_name["litellm-1"].unschedulable
    assert by_name["hindsight-1"].termination_reason == "Evicted"


def test_old_restarts_on_a_ready_pod_are_history_but_recent_ones_are_not():
    workloads = cluster.workloads(
        [
            # Restarted when its node rebooted hours ago, and has run cleanly since.
            _pod("agentbarn-api-1", restarts=28, terminated="Completed", stopped_ago=timedelta(hours=5)),
            _pod("agentbarn-ui-1", restarts=4, terminated="Error", stopped_ago=timedelta(minutes=20)),
        ],
        {},
        _NOW,
    )

    [issue] = workloads.issues
    assert issue.pod_name == "agentbarn-ui-1" and issue.repeatedly_restarting


def test_pods_committed_counts_what_the_pods_quota_counts():
    pods = [_pod("a"), _pod("b", phase="Pending", ready=False), _pod("c", phase="Succeeded"), _pod("d", phase="Failed")]
    assert cluster.pods_committed(pods) == 2


# --- core services --------------------------------------------------------


def test_core_services_leave_out_agents_and_report_replicas():
    ada, bob = _agent("Ada"), _agent("Bob")
    deployments = [
        V1Deployment(
            metadata=V1ObjectMeta(name="agentbarn-api"),
            spec=V1DeploymentSpec(replicas=2, selector=V1LabelSelector(), template=V1PodTemplateSpec()),
            status=V1DeploymentStatus(ready_replicas=1),
        ),
        V1Deployment(
            metadata=V1ObjectMeta(name="litellm"),
            spec=V1DeploymentSpec(replicas=1, selector=V1LabelSelector(), template=V1PodTemplateSpec()),
            status=V1DeploymentStatus(ready_replicas=None),
        ),
        V1Deployment(
            metadata=V1ObjectMeta(name=f"agent-{ada.id}", labels=_agent_labels(ada.id)),
            spec=V1DeploymentSpec(replicas=1, selector=V1LabelSelector(), template=V1PodTemplateSpec()),
            status=V1DeploymentStatus(ready_replicas=0),
        ),
        V1Deployment(
            metadata=V1ObjectMeta(name=f"agent-{bob.id}", labels={"app": f"agent-{bob.id}"}),
            spec=V1DeploymentSpec(replicas=1, selector=V1LabelSelector(), template=V1PodTemplateSpec()),
            status=V1DeploymentStatus(ready_replicas=0),
        ),
    ]
    stateful_sets = [
        V1StatefulSet(
            metadata=V1ObjectMeta(name="postgres-app"),
            spec=V1StatefulSetSpec(
                replicas=1, selector=V1LabelSelector(), template=V1PodTemplateSpec(), service_name="postgres-app"
            ),
            status=V1StatefulSetStatus(replicas=1, ready_replicas=1),
        )
    ]

    services = cluster.core_services(deployments, stateful_sets)

    assert [(service.name, service.level) for service in services] == [
        ("litellm", HealthLevel.CRITICAL),
        ("agentbarn-api", HealthLevel.WARNING),
        ("postgres-app", HealthLevel.OK),
    ]
    assert services[2].kind == "StatefulSet"


# --- capacity -------------------------------------------------------------


def test_quota_lines_keep_the_tightest_quota_and_drop_custom_names():
    quotas = [
        V1ResourceQuota(
            metadata=V1ObjectMeta(name="tenant-quota"),
            status=V1ResourceQuotaStatus(
                hard={
                    "requests.storage": "30Gi",
                    "pods": "50",
                    "fast.storageclass.storage.k8s.io/requests.storage": "5Gi",
                },
                used={
                    "requests.storage": "30Gi",
                    "pods": "20",
                    "fast.storageclass.storage.k8s.io/requests.storage": "1Gi",
                },
            ),
        ),
        V1ResourceQuota(
            metadata=V1ObjectMeta(name="other"),
            status=V1ResourceQuotaStatus(hard={"pods": "25", "limits.cpu": "0"}, used={"pods": "20"}),
        ),
    ]

    lines = cluster.quota_lines(quotas)

    assert [line.resource for line in lines] == ["requests.storage", "pods", "limits.cpu"]
    storage, pods, cpu = lines
    assert storage.source == CapacitySource.QUOTA
    assert (storage.used, storage.hard, storage.level) == (30 * _GiB, 30 * _GiB, CapacityLevel.CRITICAL)
    assert (pods.hard, pods.ratio, pods.level) == (25, 0.8, CapacityLevel.WARNING)
    assert cpu.level == CapacityLevel.CRITICAL
    assert "tenant-quota" not in str([line.model_dump() for line in lines])


def test_entered_lines_compare_ceilings_with_what_the_api_counts():
    capacity = PlatformCapacityRead(
        limits_memory_bytes=40 * _GiB,
        committed_limits_memory_bytes=42 * _GiB,
        requests_cpu_cores=5.0,
        committed_requests_cpu_cores=1.0,
    )

    lines = cluster.entered_lines(
        capacity, storage_requested=28 * _GiB, pods_counted=10, storage_ceiling=30 * _GiB, pods_ceiling=None
    )

    by_resource = {line.resource: line for line in lines}
    assert [line.resource for line in lines][:3] == ["requests.storage", "pods", "limits.memory"]
    assert by_resource["requests.storage"].level == CapacityLevel.CRITICAL
    assert by_resource["pods"].level == CapacityLevel.UNKNOWN and by_resource["pods"].used == 10
    assert by_resource["limits.memory"].level == CapacityLevel.CEILING_OUT_OF_DATE
    assert by_resource["requests.cpu"].level == CapacityLevel.OK
    assert by_resource["limits.cpu"].level == CapacityLevel.UNKNOWN
    assert all(line.source == CapacitySource.ENTERED for line in lines)


def test_an_unknown_figure_is_unknown_not_zero():
    lines = cluster.entered_lines(
        PlatformCapacityRead(), storage_requested=None, pods_counted=None, storage_ceiling=10, pods_ceiling=10
    )
    assert {line.resource: line.used for line in lines}["requests.storage"] is None
    assert {line.resource: line.level for line in lines}["pods"] == CapacityLevel.UNKNOWN


# --- events ---------------------------------------------------------------


def _event(
    reason: str, message: str, *, kind: str = "Pod", name: str = "agentbarn-api-1", age=timedelta(minutes=5), count=1
):
    return CoreV1Event(
        metadata=V1ObjectMeta(name=f"{name}.abc"),
        involved_object=V1ObjectReference(kind=kind, name=name),
        reason=reason,
        message=message,
        type="Warning",
        count=count,
        last_timestamp=_NOW - age,
    )


def test_an_event_message_is_never_carried_but_a_quota_rejection_is_rebuilt():
    ada = _agent("Ada")
    events = [
        _event(
            "FailedCreate",
            f'Error creating: pods "agent-{ada.id}-7d9f-x" is forbidden: exceeded quota: tenant-quota, '
            "requested: requests.storage=1Gi, used: requests.storage=30Gi, limited: requests.storage=30Gi",
            kind="ReplicaSet",
            name=f"agent-{ada.id}-7d9f",
            count=12,
        ),
        _event("FailedMount", 'MountVolume.SetUp failed for volume "creds" : secret "discord-bot-token" not found'),
    ]

    rows = cluster.warning_events(events, _identities(ada), _NOW)

    quota, mount = rows
    assert quota.detail == "requests.storage: requested 1Gi, used 30Gi, limit 30Gi"
    assert "quota is full" in quota.explanation
    assert quota.agent is not None and quota.agent.agent_name == "Ada"
    assert quota.count == 12
    assert mount.detail is None
    assert mount.explanation == "A volume could not be mounted, so the pod cannot start."
    dumped = str([row.model_dump() for row in rows])
    assert "discord-bot-token" not in dumped and "tenant-quota" not in dumped


def test_old_events_are_dropped_and_unlisted_objects_are_not_named():
    rows = cluster.warning_events(
        [
            _event("BackOff", "x", age=timedelta(hours=7)),
            _event("Weird reason!", "x", kind="Secret", name="litellm-api-key"),
        ],
        {},
        _NOW,
    )

    [row] = rows
    assert row.reason == "Unknown"
    assert row.object_kind is None and row.object_name is None
    assert row.explanation == "Kubernetes reported a warning for this object."


def test_events_that_differ_only_in_their_message_read_as_one():
    pull = "report-renderer-1"
    rows = cluster.warning_events(
        [
            _event("Failed", "Failed to pull image: not found", name=pull, count=2, age=timedelta(minutes=3)),
            _event("Failed", "Error: ErrImagePull", name=pull, count=2, age=timedelta(minutes=1)),
            _event("Failed", "Error: ImagePullBackOff", name=pull, count=1, age=timedelta(minutes=2)),
            _event("BackOff", "Back-off pulling image", name=pull),
        ],
        {},
        _NOW,
    )

    by_reason = {row.reason: row for row in rows}
    assert len(rows) == 2
    assert by_reason["Failed"].count == 5
    assert by_reason["Failed"].last_seen == _NOW - timedelta(minutes=1)


def test_events_are_newest_first_and_bounded():
    events = [
        _event("BackOff", "x", name=f"pod-{minute}", age=timedelta(minutes=minute))
        for minute in range(cluster.MAX_EVENTS + 5)
    ]
    rows = cluster.warning_events(events, {}, _NOW)
    assert len(rows) == cluster.MAX_EVENTS
    assert rows[0].last_seen == _NOW


# --- Prometheus -----------------------------------------------------------


def test_firing_alerts_carry_name_severity_and_agent_only():
    ada = _agent("Ada")
    samples = [
        PrometheusSample({"alertname": "APIDown", "severity": "critical", "instance": "10.0.0.1:8000"}, 1.0),
        PrometheusSample(
            {"alertname": "AgentUnhealthy", "severity": "warning", "app": f"agent-{ada.id}", "agent_name": "wrong"}, 1.0
        ),
        PrometheusSample(
            {"alertname": "AgentUnhealthy", "severity": "warning", "app": f"agent-{ada.id}", "pod": "p2"}, 1.0
        ),
        PrometheusSample({"alertname": "Custom", "severity": "page-me"}, 1.0),
        PrometheusSample({"alertname": "bad name {x}"}, 1.0),
    ]

    alerts = cluster.firing_alerts(samples, _identities(ada))

    assert [(alert.name, alert.severity) for alert in alerts] == [
        ("APIDown", "critical"),
        ("AgentUnhealthy", "warning"),
        ("Custom", None),
    ]
    assert alerts[1].agent is not None and alerts[1].agent.agent_name == "Ada"
    assert "10.0.0.1" not in str([alert.model_dump() for alert in alerts])


def test_an_unhealthy_runtime_is_listed_whatever_its_pod_says():
    ready, never, healthy = _agent("Ada"), _agent("Bob"), _agent("Cy")
    stopped = _agent("Di", AgentStatus.STOPPED)

    def gauge(agent, name, value):
        return PrometheusSample({"__name__": name, "app": f"agent-{agent.id}"}, value)

    samples = [
        gauge(ready, "agent_healthz_ok", 0),
        gauge(ready, "agent_healthz_ever_connected", 1),
        gauge(never, "agent_healthz_ok", 0),
        gauge(never, "agent_healthz_ever_connected", 0),
        gauge(healthy, "agent_healthz_ok", 1),
        gauge(stopped, "agent_healthz_ok", 0),
    ]

    rows = cluster.unhealthy_runtimes(samples, _identities(ready, never, healthy, stopped), {ready.id: True})

    assert [(row.agent.agent_name, row.pod_ready, row.ever_connected) for row in rows] == [
        ("Ada", True, True),
        ("Bob", None, False),
    ]


# --- failed Agents --------------------------------------------------------


def test_a_failed_agent_shows_fixed_copy_and_only_a_grammatical_detail():
    rows = [
        PlatformFailedAgent(
            uuid4(),
            "Ada",
            _ACME,
            "Acme",
            "QUOTA_EXHAUSTED",
            "requests.storage: requested 1Gi, used 30Gi, limit 30Gi",
            "x",
            _NOW,
        ),
        PlatformFailedAgent(uuid4(), "Bob", _ACME, "Acme", None, None, "raw kubeconfig text", _NOW),
        PlatformFailedAgent(uuid4(), "Cy", _ACME, "Acme", "QUOTA_EXHAUSTED", "token=abc", "x", _NOW),
    ]

    ada, bob, cy = cluster.failed_agents(rows)

    assert ada.code == "QUOTA_EXHAUSTED" and ada.detail == "requests.storage: requested 1Gi, used 30Gi, limit 30Gi"
    assert ada.summary is not None and "quota" in ada.summary
    assert bob.code == "PROVISIONING_FAILED" and bob.detail is None
    assert "kubeconfig" not in bob.model_dump_json()
    assert cy.detail is None


# --- overall --------------------------------------------------------------


def _level(**overrides) -> HealthLevel:
    arguments = {
        "sources": {EnvironmentSource.PODS: SourceState.AVAILABLE},
        "services": [],
        "capacity": [],
        "workloads": WorkloadsRead(),
        "unhealthy_runtimes": [],
        "failed_agents": [],
        "alerts": [],
        "volumes": VolumeAllocationRead(),
        "events": [],
        **overrides,
    }
    return overall_level(**arguments)


def test_the_overall_level_is_the_worst_part():
    full = cluster.entered_lines(
        PlatformCapacityRead(), storage_requested=30.0, pods_counted=None, storage_ceiling=30, pods_ceiling=None
    )
    nearly = cluster.entered_lines(
        PlatformCapacityRead(), storage_requested=24.0, pods_counted=None, storage_ceiling=30, pods_ceiling=None
    )
    failing = cluster.workloads([_pod("redis-1", restarts=4)], {}, _NOW)

    assert _level() == HealthLevel.OK
    assert _level(capacity=nearly) == HealthLevel.WARNING
    assert _level(workloads=failing) == HealthLevel.WARNING
    assert _level(capacity=full) == HealthLevel.CRITICAL
    assert _level(sources={EnvironmentSource.PODS: SourceState.FORBIDDEN}) == HealthLevel.UNKNOWN


def test_prometheus_being_unavailable_is_never_ok():
    reachable = {EnvironmentSource.PODS: SourceState.AVAILABLE, EnvironmentSource.PROMETHEUS: SourceState.UNAVAILABLE}
    [critical] = cluster.firing_alerts([PrometheusSample({"alertname": "APIDown", "severity": "critical"}, 1.0)], {})

    assert _level(sources=reachable) == HealthLevel.WARNING
    assert _level(sources=reachable, alerts=[critical]) == HealthLevel.CRITICAL
    assert _level(sources={**reachable, EnvironmentSource.PROMETHEUS: SourceState.NOT_CONFIGURED}) == HealthLevel.OK


@pytest.mark.parametrize("zero_first", [True, False])
def test_a_zero_quota_always_wins_over_a_nonzero_quota(zero_first):
    zero = V1ResourceQuota(status=V1ResourceQuotaStatus(hard={"pods": "0"}, used={"pods": "0"}))
    other = V1ResourceQuota(status=V1ResourceQuotaStatus(hard={"pods": "10"}, used={"pods": "1"}))
    quotas = [zero, other] if zero_first else [other, zero]

    [line] = cluster.quota_lines(quotas)

    assert line.hard == 0
    assert line.level == CapacityLevel.CRITICAL


@pytest.mark.parametrize("severities", [("warning", "critical"), ("critical", "warning")])
def test_duplicate_alerts_keep_the_highest_severity(severities):
    samples = [PrometheusSample({"alertname": "HighAPI5xxRate", "severity": severity}, 1.0) for severity in severities]

    [alert] = cluster.firing_alerts(samples, {})

    assert alert.severity == "critical"
    assert _level(alerts=[alert]) == HealthLevel.CRITICAL

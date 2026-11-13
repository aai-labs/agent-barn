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
    V1CronJob,
    V1CronJobSpec,
    V1CronJobStatus,
    V1Deployment,
    V1DeploymentCondition,
    V1DeploymentSpec,
    V1DeploymentStatus,
    V1Job,
    V1JobCondition,
    V1JobStatus,
    V1JobTemplateSpec,
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
    V1Service,
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
    CoreServiceRead,
    DeployedVersionRead,
    EnvironmentSource,
    HealthLevel,
    RolloutState,
    ScheduledBackupsRead,
    SourceState,
    VolumeAllocationRead,
    VolumeGroup,
    WorkloadKind,
    WorkloadsRead,
)
from api.domains.environment_health.service import overall_level
from api.domains.resource_usage.models import PlatformCapacityRead
from api.domains.restore_points.models import (
    OverdueScheduledBackup,
    ScheduledBackupFailures,
    ScheduledBackupHealth,
)
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


def test_a_pod_that_kept_restarting_this_week_is_listed_though_its_last_restart_was_days_ago():
    workloads = cluster.workloads(
        [_pod("rabbitmq-0", restarts=15, terminated="OOMKilled", stopped_ago=timedelta(days=2))],
        {},
        _NOW,
        restarts={"rabbitmq-0": cluster.PodRestarts(restarts=15, oom_killed=True)},
    )

    [issue] = workloads.issues
    assert (issue.restarts_in_window, issue.oom_killed, issue.repeatedly_restarting) == (15, True, True)


def test_one_oom_kill_this_week_is_listed():
    workloads = cluster.workloads(
        [_pod("firecrawl-1", restarts=1, terminated="OOMKilled", stopped_ago=timedelta(days=3))],
        {},
        _NOW,
        restarts={"firecrawl-1": cluster.PodRestarts(restarts=1, oom_killed=True)},
    )

    [issue] = workloads.issues
    assert (issue.oom_killed, issue.repeatedly_restarting) == (True, False)


def test_with_restart_history_lifetime_restarts_from_before_the_window_are_not_flagged():
    workloads = cluster.workloads(
        [
            # 28 restarts since it was created, one of them this week, two hours ago.
            _pod("agentbarn-api-1", restarts=28, terminated="Error", stopped_ago=timedelta(hours=2)),
            # Not scraped yet: judged by the pod alone, as without the history.
            _pod("agentbarn-ui-1", restarts=4, terminated="Error", stopped_ago=timedelta(minutes=20)),
        ],
        {},
        _NOW,
        restarts={"agentbarn-api-1": cluster.PodRestarts(restarts=1, oom_killed=False)},
    )

    [issue] = workloads.issues
    assert issue.pod_name == "agentbarn-ui-1" and issue.restarts_in_window is None


def test_without_restart_history_an_oom_kill_this_week_is_still_listed():
    workloads = cluster.workloads(
        [
            _pod("rabbitmq-0", restarts=1, terminated="OOMKilled", stopped_ago=timedelta(days=2)),
            _pod("redis-0", restarts=1, terminated="OOMKilled", stopped_ago=timedelta(days=9)),
        ],
        {},
        _NOW,
    )

    [issue] = workloads.issues
    assert issue.pod_name == "rabbitmq-0" and issue.oom_killed


def test_restart_history_keeps_only_pod_names_and_whole_counts():
    restarts = cluster.pod_restarts(
        [
            PrometheusSample({"pod": "rabbitmq-0", "signal": "restarts"}, 14.97),
            PrometheusSample({"pod": "rabbitmq-0", "signal": "oom_killed"}, 1.0),
            PrometheusSample({"pod": "firecrawl-1", "signal": "oom_killed"}, 1.0),
            PrometheusSample({"pod": "Not A Pod; rm -rf", "signal": "restarts"}, 3.0),
            PrometheusSample({"pod": "redis-0", "signal": "something-else"}, 9.0),
        ]
    )

    assert restarts == {
        "rabbitmq-0": cluster.PodRestarts(restarts=15, oom_killed=True),
        "firecrawl-1": cluster.PodRestarts(restarts=0, oom_killed=True),
    }


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


_SHA = "7f306e1b4c2d9a8e5f60718293a4b5c6d7e8f901"
_OLD_SHA = "0123456789abcdef0123456789abcdef01234567"


def _released(
    name: str, sha: str | None, *, reason: str = "NewReplicaSetAvailable", rolled_out_ago=timedelta(days=6)
) -> V1Deployment:
    return V1Deployment(
        metadata=V1ObjectMeta(name=name),
        spec=V1DeploymentSpec(
            replicas=1,
            selector=V1LabelSelector(),
            template=V1PodTemplateSpec(
                metadata=V1ObjectMeta(annotations={"build-sha": sha, "note": "secret"} if sha else None)
            ),
        ),
        status=V1DeploymentStatus(
            ready_replicas=1,
            conditions=[
                V1DeploymentCondition(type="Available", status="True", reason="MinimumReplicasAvailable"),
                V1DeploymentCondition(
                    type="Progressing",
                    status="False" if reason == "ProgressDeadlineExceeded" else "True",
                    reason=reason,
                    message="ReplicaSet has timed out progressing: token=abc",
                    last_update_time=_NOW - rolled_out_ago,
                ),
            ],
        ),
    )


def test_a_service_carries_its_build_and_when_its_last_rollout_finished():
    [service] = cluster.core_services([_released("agentbarn-api", _SHA)], [])

    assert (service.build_sha, service.rollout, service.rolled_out_at) == (
        _SHA,
        cluster.RolloutState.COMPLETE,
        _NOW - timedelta(days=6),
    )
    assert "token" not in service.model_dump_json() and "secret" not in service.model_dump_json()


def test_a_stuck_rollout_is_a_warning_and_an_unrecognised_build_is_dropped():
    services = cluster.core_services(
        [
            _released("agentbarn-ui", "not-a-sha; rm -rf"),
            _released("agentbarn-api", _SHA, reason="ProgressDeadlineExceeded", rolled_out_ago=timedelta(hours=2)),
            _released("agentbarn-worker", _SHA, reason="ReplicaSetUpdated", rolled_out_ago=timedelta(minutes=1)),
        ],
        [],
    )

    by_name = {service.name: service for service in services}
    api = by_name["agentbarn-api"]
    assert (api.rollout, api.rolled_out_at, api.level) == (cluster.RolloutState.STUCK, None, HealthLevel.WARNING)
    assert by_name["agentbarn-worker"].rollout == cluster.RolloutState.IN_PROGRESS
    assert by_name["agentbarn-ui"].build_sha is None


def test_the_deployed_version_is_the_newest_build_and_says_when_services_disagree():
    services = cluster.core_services(
        [
            _released("agentbarn-api", _SHA, rolled_out_ago=timedelta(days=6)),
            _released("agentbarn-ui", _SHA, rolled_out_ago=timedelta(days=6, minutes=2)),
            _released("agentbarn-gateway", _OLD_SHA, rolled_out_ago=timedelta(days=20)),
            _released("redis", None),
        ],
        [],
    )

    deployed = cluster.deployed_version(services)

    assert deployed is not None
    assert (deployed.build_sha, deployed.rolled_out_at, deployed.mixed) == (_SHA, _NOW - timedelta(days=6), True)
    assert deployed.behind == ["agentbarn-gateway"]
    assert cluster.deployed_version(cluster.core_services([_released("redis", None)], [])) is None


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
    assert [line.resource for line in lines][:5] == [
        "requests.storage",
        "persistentvolumeclaims",
        "pods",
        "services",
        "limits.memory",
    ]
    assert by_resource["requests.storage"].level == CapacityLevel.CRITICAL
    assert by_resource["pods"].level == CapacityLevel.UNKNOWN and by_resource["pods"].used == 10
    assert by_resource["limits.memory"].level == CapacityLevel.CEILING_OUT_OF_DATE
    assert by_resource["requests.cpu"].level == CapacityLevel.OK
    assert by_resource["limits.cpu"].level == CapacityLevel.UNKNOWN
    assert all(line.source == CapacitySource.ENTERED for line in lines)


def test_entered_lines_count_volume_claims_and_services_against_their_ceilings():
    lines = cluster.entered_lines(
        PlatformCapacityRead(),
        storage_requested=None,
        pods_counted=None,
        storage_ceiling=None,
        pods_ceiling=None,
        claims_counted=60,
        claims_ceiling=60,
        services_counted=12,
        services_ceiling=None,
    )

    by_resource = {line.resource: line for line in lines}
    assert [line.resource for line in lines][:4] == ["requests.storage", "persistentvolumeclaims", "pods", "services"]
    claims = by_resource["persistentvolumeclaims"]
    assert (claims.unit, claims.used, claims.hard, claims.level) == ("count", 60, 60, CapacityLevel.CRITICAL)
    assert (by_resource["services"].used, by_resource["services"].level) == (12, CapacityLevel.UNKNOWN)


def test_services_committed_counts_every_service_in_the_namespace():
    services = [V1Service(metadata=V1ObjectMeta(name=name)) for name in ("agentbarn-api", f"agent-{uuid4()}", "redis")]
    assert cluster.services_committed(services) == 3


def test_an_unknown_figure_is_unknown_not_zero():
    lines = cluster.entered_lines(
        PlatformCapacityRead(), storage_requested=None, pods_counted=None, storage_ceiling=10, pods_ceiling=10
    )
    assert {line.resource: line.used for line in lines}["requests.storage"] is None
    assert {line.resource: line.level for line in lines}["pods"] == CapacityLevel.UNKNOWN


def _cpu_and_pods(cpu_used: float, cpu_hard: float | None, pods_used: int, pods_hard: int | None):
    return cluster.entered_lines(
        PlatformCapacityRead(limits_cpu_cores=cpu_hard, committed_limits_cpu_cores=cpu_used),
        storage_requested=None,
        pods_counted=pods_used,
        storage_ceiling=None,
        pods_ceiling=pods_hard,
    )


def test_a_peak_sits_beside_the_current_figure_with_its_own_ratio():
    lines = cluster.with_peaks(_cpu_and_pods(10.0, 40.0, 30, 60), {"limits.cpu": 20.0, "pods": 33.0})

    by_resource = {line.resource: line for line in lines}
    cpu = by_resource["limits.cpu"]
    assert (cpu.used, cpu.peak, cpu.peak_ratio, cpu.level) == (10.0, 20.0, 0.5, CapacityLevel.OK)
    assert (by_resource["pods"].peak, by_resource["pods"].peak_ratio) == (33.0, 0.55)
    assert by_resource["requests.storage"].peak is None


def test_a_short_spike_near_the_ceiling_turns_a_quiet_line_into_a_warning():
    lines = cluster.with_peaks(_cpu_and_pods(10.0, 40.0, 30, 60), {"limits.cpu": 39.6})

    cpu = {line.resource: line for line in lines}["limits.cpu"]
    # Now at a quarter, but it touched 99% when the cron jobs started together: a pod
    # starting in that minute would have been refused.
    assert (cpu.ratio, cpu.peak_ratio, cpu.level) == (0.25, 0.99, CapacityLevel.WARNING)


def test_a_peak_never_lowers_a_level_or_judges_a_line_without_a_ceiling():
    lines = cluster.with_peaks(_cpu_and_pods(38.0, 40.0, 30, None), {"limits.cpu": 39.0, "pods": 50.0})

    by_resource = {line.resource: line for line in lines}
    assert by_resource["limits.cpu"].level == CapacityLevel.CRITICAL
    pods = by_resource["pods"]
    assert (pods.peak, pods.peak_ratio, pods.level) == (50.0, None, CapacityLevel.UNKNOWN)


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
        "deployed": None,
        "cron_jobs": [],
        "backups": ScheduledBackupsRead(),
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


def test_services_on_another_build_are_a_warning_unless_a_rollout_is_under_way():
    mixed = DeployedVersionRead(build_sha=_SHA, mixed=True, behind=["agentbarn-gateway"])
    rolling = CoreServiceRead(
        name="agentbarn-gateway",
        kind="Deployment",
        desired_replicas=1,
        ready_replicas=1,
        level=HealthLevel.OK,
        rollout=RolloutState.IN_PROGRESS,
    )

    assert _level(deployed=mixed) == HealthLevel.WARNING
    assert _level(deployed=mixed, services=[rolling]) == HealthLevel.OK
    assert _level(deployed=DeployedVersionRead(build_sha=_SHA)) == HealthLevel.OK


# --- cron jobs ------------------------------------------------------------


def _cron(
    name: str,
    *,
    schedule: str = "*/5 * * * *",
    suspend: bool = False,
    scheduled_ago: timedelta | None = timedelta(minutes=3),
    succeeded_ago: timedelta | None = timedelta(minutes=3),
    age: timedelta = timedelta(days=30),
    active: int = 0,
) -> V1CronJob:
    return V1CronJob(
        metadata=V1ObjectMeta(name=name, creation_timestamp=_NOW - age),
        spec=V1CronJobSpec(schedule=schedule, suspend=suspend, job_template=V1JobTemplateSpec()),
        status=V1CronJobStatus(
            last_schedule_time=_NOW - scheduled_ago if scheduled_ago else None,
            last_successful_time=_NOW - succeeded_ago if succeeded_ago else None,
            active=[V1ObjectReference(kind="Job", name=f"{name}-{n}") for n in range(active)] or None,
        ),
    )


def _job(cron_name: str, *, failed: bool, ago: timedelta) -> V1Job:
    condition = V1JobCondition(
        type="Failed" if failed else "Complete",
        status="True",
        reason="BackoffLimitExceeded" if failed else None,
        message="Job has reached the specified backoff limit: password=hunter2",
        last_transition_time=_NOW - ago,
    )
    return V1Job(
        metadata=V1ObjectMeta(
            name=f"{cron_name}-{int(ago.total_seconds())}",
            creation_timestamp=_NOW - ago - timedelta(seconds=30),
            owner_references=[V1OwnerReference(api_version="batch/v1", kind="CronJob", name=cron_name, uid="1")],
        ),
        status=V1JobStatus(conditions=[condition]),
    )


def test_a_cron_job_whose_newest_run_failed_is_failing():
    rows = cluster.cron_jobs(
        [_cron("agentbarn-restore-point-schedule", succeeded_ago=timedelta(hours=3))],
        [
            _job("agentbarn-restore-point-schedule", failed=False, ago=timedelta(hours=3)),
            _job("agentbarn-restore-point-schedule", failed=True, ago=timedelta(minutes=2)),
        ],
        _NOW,
    )

    [row] = rows
    assert (row.name, row.state, row.schedule) == (
        "agentbarn-restore-point-schedule",
        cluster.CronJobState.FAILING,
        "*/5 * * * *",
    )
    assert (row.last_successful_at, row.last_failed_at) == (_NOW - timedelta(hours=3), _NOW - timedelta(minutes=2))
    assert "hunter2" not in row.model_dump_json() and "backoff" not in row.model_dump_json()


def test_a_cron_job_with_no_success_for_a_day_is_stalled_and_a_suspended_one_is_not():
    rows = cluster.cron_jobs(
        [
            _cron("agentbarn-cost-sync", succeeded_ago=timedelta(hours=30)),
            _cron("agentbarn-memory-purge", succeeded_ago=None, scheduled_ago=None),
            _cron("agentbarn-artifact-purge", suspend=True, succeeded_ago=timedelta(days=9)),
            _cron("agentbarn-new", succeeded_ago=None, scheduled_ago=None, age=timedelta(hours=2)),
            _cron("agentbarn-event-reconciler"),
        ],
        [],
        _NOW,
    )

    states = {row.name: row.state for row in rows}
    assert states == {
        "agentbarn-cost-sync": cluster.CronJobState.STALLED,
        "agentbarn-memory-purge": cluster.CronJobState.STALLED,
        "agentbarn-artifact-purge": cluster.CronJobState.SUSPENDED,
        "agentbarn-new": cluster.CronJobState.OK,
        "agentbarn-event-reconciler": cluster.CronJobState.OK,
    }
    # The ones that need a look first.
    assert [row.name for row in rows][:2] == ["agentbarn-cost-sync", "agentbarn-memory-purge"]


def test_a_cron_schedule_outside_the_cron_grammar_is_not_carried():
    [odd, macro] = cluster.cron_jobs(
        [_cron("a-odd", schedule="* * * * * ; curl evil"), _cron("b-macro", schedule="@hourly")], [], _NOW
    )
    assert (odd.schedule, macro.schedule) == (None, "@hourly")


# --- idle agents ----------------------------------------------------------


def _aged(name: str, status: AgentStatus, age: timedelta) -> PlatformAgentIdentity:
    return PlatformAgentIdentity(uuid4(), name, status, _ACME, "Acme", _NOW - age)


def test_agents_no_one_has_written_to_in_two_weeks_are_cleanup_candidates_with_what_they_hold():
    ada = _aged("Ada", AgentStatus.RUNNING, timedelta(days=60))
    bo = _aged("Bo", AgentStatus.STOPPED, timedelta(days=40))
    cy = _aged("Cy", AgentStatus.RUNNING, timedelta(days=60))
    dee = _aged("Dee", AgentStatus.RUNNING, timedelta(days=5))
    eve = _aged("Eve", AgentStatus.ERROR, timedelta(days=60))
    identities = _identities(ada, bo, cy, dee, eve)

    idle = cluster.idle_agents(
        identities,
        last_user_message={ada.id: _NOW - timedelta(days=20), cy.id: _NOW - timedelta(days=2)},
        last_call={ada.id: _NOW - timedelta(hours=3)},
        pods=[_pod(f"agent-{ada.id}-7d9f-abcde", labels=_agent_labels(ada.id))],
        claims=[
            _claim(f"agent-{ada.id}", "2Gi", _agent_labels(ada.id)),
            _claim(f"agent-{bo.id}", "1Gi", _agent_labels(bo.id)),
            _claim("data-postgres-app-0", "10Gi"),
        ],
        restore_points={bo.id: (3, 600_000_000)},
        now=_NOW,
        idle_after=timedelta(days=14),
    )

    # Never written to first, then the longest silence. Cy was written to this week, Dee
    # is too new to judge, and Eve's failure is shown elsewhere.
    assert [row.agent.agent_name for row in idle] == ["Bo", "Ada"]
    bo_row, ada_row = idle
    assert (bo_row.last_user_message_at, bo_row.holds_pod, bo_row.volume_claims, bo_row.requested_bytes) == (
        None,
        False,
        1,
        _GiB,
    )
    assert (bo_row.restore_points, bo_row.restore_point_bytes) == (3, 600_000_000)
    # A model call three hours ago, with no user message, is the platform waking it, not use.
    assert (ada_row.last_call_at, ada_row.holds_pod, ada_row.requested_bytes) == (
        _NOW - timedelta(hours=3),
        True,
        2 * _GiB,
    )


def test_what_an_idle_agent_holds_is_unknown_when_the_cluster_could_not_be_read():
    ada = _aged("Ada", AgentStatus.RUNNING, timedelta(days=60))

    [row] = cluster.idle_agents(
        _identities(ada),
        last_user_message={},
        last_call={},
        pods=None,
        claims=None,
        restore_points={},
        now=_NOW,
        idle_after=timedelta(days=14),
    )

    assert (row.holds_pod, row.volume_claims, row.requested_bytes, row.restore_points) == (None, None, None, 0)


def test_only_finished_runs_of_platform_cron_jobs_are_judged():
    ada = _agent("Ada")
    running = _job("agentbarn-cost-sync", failed=True, ago=timedelta(minutes=1))
    running.status = V1JobStatus(conditions=[V1JobCondition(type="Failed", status="False", last_transition_time=_NOW)])
    restore_job = _job("agentbarn-cost-sync", failed=True, ago=timedelta(minutes=1))
    restore_job.metadata.owner_references = [V1OwnerReference(api_version="v1", kind="Pod", name="rp-cap-abc", uid="2")]
    agents_cron = _cron(f"agent-{ada.id}-nightly")
    agents_cron.metadata.labels = _agent_labels(ada.id)

    rows = cluster.cron_jobs(
        [_cron("agentbarn-cost-sync"), agents_cron, _cron("Not_A_Name")],
        [running, restore_job, V1Job(metadata=V1ObjectMeta(name="no-status"), status=None)],
        _NOW,
    )

    # A run still going, or a Job no CronJob owns, says nothing about the CronJob; an Agent's
    # CronJob is not the platform's, and a name outside the object grammar is not carried.
    assert [(row.name, row.state) for row in rows] == [("agentbarn-cost-sync", cluster.CronJobState.OK)]


def test_a_backup_failure_across_the_platform_is_counted_and_only_the_worst_agents_are_named():
    agents = [_agent(f"Agent {n}") for n in range(8)]
    stopped = _agent("Stopped", AgentStatus.STOPPED)
    failures = [
        ScheduledBackupFailures(agent.id, failures=1 + n % 3, last_failed_at=_NOW - timedelta(minutes=n))
        for n, agent in enumerate(agents)
    ]

    backups = cluster.scheduled_backups(
        ScheduledBackupHealth(interval_minutes=360, failures=failures, overdue=[]),
        _identities(*agents, stopped),
        failure_window_hours=24,
    )

    # Every running Agent is under the schedule; the stopped one is not.
    assert (backups.running_agents, backups.failed_total) == (8, 8)
    # Most failures first, then the latest; the rest are only counted.
    assert [(row.agent.agent_name, row.failures) for row in backups.failed] == [
        ("Agent 2", 3),
        ("Agent 5", 3),
        ("Agent 1", 2),
        ("Agent 4", 2),
        ("Agent 7", 2),
    ]
    assert len(backups.failed) == cluster.BACKUP_LIST_LIMIT


def test_an_agent_whose_backups_fail_is_not_named_again_as_overdue():
    failing, never, stale, older = _agent("Failing"), _agent("Never"), _agent("Stale"), _agent("Older")

    backups = cluster.scheduled_backups(
        ScheduledBackupHealth(
            interval_minutes=360,
            failures=[ScheduledBackupFailures(failing.id, failures=4, last_failed_at=_NOW)],
            overdue=[
                OverdueScheduledBackup(failing.id, last_backup_at=_NOW - timedelta(days=2)),
                OverdueScheduledBackup(stale.id, last_backup_at=_NOW - timedelta(days=1)),
                OverdueScheduledBackup(never.id, last_backup_at=None),
                OverdueScheduledBackup(older.id, last_backup_at=_NOW - timedelta(days=3)),
            ],
        ),
        _identities(failing, never, stale, older),
        failure_window_hours=24,
    )

    # Never backed up first, then the longest without one.
    assert [row.agent.agent_name for row in backups.overdue] == ["Never", "Older", "Stale"]
    assert (backups.failed_total, backups.overdue_total) == (1, 3)

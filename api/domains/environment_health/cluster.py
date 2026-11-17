"""Reading Kubernetes objects and Prometheus samples into the environment health read models.

Pure functions, with no I/O, so every rule here is tested against hand-built objects. Each
one keeps only allowlisted fields: names this platform generates, fixed reason words, numbers
and times. An Agent is found by an id in a label this platform sets, and named from the
database; the `org-id`, `agent_name` and `org_name` labels are never trusted.
"""

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import NamedTuple
from uuid import UUID

from kubernetes.client import (
    CoreV1Event,
    V1CronJob,
    V1Deployment,
    V1Job,
    V1ObjectMeta,
    V1OwnerReference,
    V1PersistentVolumeClaim,
    V1Pod,
    V1ReplicaSet,
    V1ResourceQuota,
    V1Service,
    V1StatefulSet,
)
from kubernetes.utils import parse_quantity

from api.domains.agents.builders.restore_point import (
    AGENT_ID_LABEL_KEY,
    COMPONENT_LABEL_KEY,
)
from api.domains.agents.builders.restore_point import COMPONENT_LABEL as RESTORE_POINT_COMPONENT
from api.domains.agents.models import AgentStatus, PlatformAgentIdentity, PlatformFailedAgent
from api.domains.agents.provisioning_errors import (
    AgentProvisioningErrorCategory,
    cluster_rejection_detail,
    persisted_provisioning_error,
)
from api.domains.environment_health.models import (
    AgentRefRead,
    BackupFailureRead,
    CapacityLevel,
    CapacityLineRead,
    CapacitySource,
    CapacityUnit,
    CoreServiceRead,
    CronJobRead,
    CronJobState,
    DeployedVersionRead,
    FailedAgentRead,
    FiringAlertRead,
    HealthLevel,
    IdleAgentRead,
    OverdueBackupRead,
    PodIssueRead,
    RolloutState,
    ScheduledBackupsRead,
    UnhealthyRuntimeRead,
    VolumeAllocationRead,
    VolumeClaimRead,
    VolumeGroup,
    VolumeGroupRead,
    WarningEventRead,
    WorkloadKind,
    WorkloadsRead,
)
from api.domains.resource_usage.models import PlatformCapacityRead
from api.domains.restore_points.models import ScheduledBackupHealth
from api.infrastructure.prometheus.client import PrometheusSample

AGENT_COMPONENT = "agent"

# The same thresholds as the Platform resource usage meters (METER_WARN_RATIO and
# METER_CRITICAL_RATIO in the UI), so one figure never reads as fine on one page and as a
# warning on the other.
WARN_RATIO = 0.75
CRITICAL_RATIO = 0.9

# A pod that has restarted this often since it was created, the last time within the window,
# is restarting repeatedly. Restart counts never reset, so a pod that restarted many times when
# its node rebooted last week and has run cleanly since is not flagged.
# The pod-template annotation the charts set to the commit each image was built from.
BUILD_SHA_ANNOTATION = "build-sha"
_BUILD_SHA = re.compile(r"[0-9a-f]{7,40}")

# Every platform CronJob runs at least hourly, so a day with no successful run is a stall
# whatever its schedule. A CronJob younger than this has not had its chance yet.
CRON_STALL_AFTER = timedelta(hours=24)
_CRON_FIELD = r"[0-9A-Za-z*/,?\-]{1,32}"
_CRON_SCHEDULE = re.compile(
    rf"{_CRON_FIELD}(?: {_CRON_FIELD}){{4}}|@(?:yearly|annually|monthly|weekly|daily|midnight|hourly)"
)

REPEATED_RESTARTS = 3
RECENT_RESTART_WINDOW = timedelta(hours=1)
# How far back the restart history (kube-state-metrics, via Prometheus) is read. A container
# OOM-killed once a day never restarts three times in an hour, or even in a day, but over a
# week it plainly keeps failing. Prometheus keeps 15 days.
RESTART_HISTORY_WINDOW = timedelta(days=7)
# A pod younger than this that is not ready yet is starting, not failing.
STARTUP_GRACE = timedelta(minutes=2)
# Warning Events older than this are history, not news. Kubernetes keeps them about an hour
# by default, so this is a bound for clusters that keep them longer.
EVENT_WINDOW = timedelta(hours=6)
# The most rows any list on the page carries, worst first. Each list also carries how many
# there are, so a failure across the platform reads as a count and not a page of rows.
LIST_LIMIT = 100

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_AGENT_APP = re.compile(rf"agent-({_UUID})")
# Pods, ReplicaSets and claims of an Agent all start with its Deployment's name.
_AGENT_OBJECT = re.compile(rf"agent-({_UUID})(?:-[a-z0-9]+){{0,2}}")
# DNS-1123 subdomain: the only shape a namespaced object's name can take.
_OBJECT_NAME = re.compile(r"[a-z0-9]([-a-z0-9.]{0,251}[a-z0-9])?")
_REASON = re.compile(r"[A-Z][A-Za-z]{1,63}")
_ALERT_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,99}")
_ALERT_SEVERITIES = frozenset({"critical", "warning", "info"})

_TERMINAL_WAITING = frozenset(
    {
        "CrashLoopBackOff",
        "ImagePullBackOff",
        "ErrImagePull",
        "CreateContainerConfigError",
        "CreateContainerError",
        "InvalidImageName",
        "RunContainerError",
    }
)
_WAITING = _TERMINAL_WAITING | {"ContainerCreating", "PodInitializing"}
_TERMINATION = frozenset(
    {"OOMKilled", "Error", "Completed", "ContainerCannotRun", "DeadlineExceeded", "Evicted", "StartError"}
)
_POD_PHASES = frozenset({"Pending", "Running", "Succeeded", "Failed", "Unknown"})
_CLAIM_PHASES = frozenset({"Bound", "Pending", "Lost"})
_EVENT_OBJECT_KINDS = frozenset(
    {"Pod", "PersistentVolumeClaim", "ReplicaSet", "Deployment", "StatefulSet", "Job", "CronJob", "Service"}
)

# The quota lines that can be named. A line scoped to a storage class, or any other custom
# name, is left out, as provisioning failures leave out quota names.
_QUOTA_RESOURCE = re.compile(
    r"(?:requests|limits)\.(?:cpu|memory|ephemeral-storage)|requests\.storage|cpu|memory|ephemeral-storage"
    r"|pods|persistentvolumeclaims|services(?:\.loadbalancers|\.nodeports)?|configmaps|secrets"
    r"|replicationcontrollers|resourcequotas|count/[a-z0-9.]{1,63}"
)
# The lines that stop an Agent from starting come first.
_QUOTA_ORDER = (
    "requests.storage",
    "persistentvolumeclaims",
    "pods",
    "services",
    "limits.memory",
    "requests.memory",
    "limits.cpu",
    "requests.cpu",
)

_EVENT_EXPLANATIONS: dict[str, str] = {
    "FailedCreate": "A controller could not create a pod or Job for this workload.",
    "FailedScheduling": "No node has room for this pod, or none matches its requirements.",
    "FailedMount": "A volume could not be mounted, so the pod cannot start.",
    "FailedAttachVolume": "A volume could not be attached to the pod's node.",
    "ProvisioningFailed": "The storage provider could not create the volume for this claim.",
    "BackOff": "A container keeps exiting or its image cannot be pulled, and Kubernetes is waiting longer between tries.",
    "Failed": "A container could not be started, often because its image could not be pulled.",
    "Unhealthy": "A liveness or readiness probe failed.",
    "Evicted": "The pod was evicted, usually because its node ran short of memory or disk.",
    "OOMKilling": "A container used more memory than its limit and was killed.",
    "FailedKillPod": "Kubernetes could not stop a pod cleanly.",
    "FailedCreatePodSandBox": "The node could not set up the pod's sandbox or network.",
}
_GENERIC_EXPLANATION = "Kubernetes reported a warning for this object."
_REJECTION_EXPLANATIONS: dict[AgentProvisioningErrorCategory, str] = {
    AgentProvisioningErrorCategory.QUOTA_EXHAUSTED: "Kubernetes refused to create it because the namespace quota is full.",
    AgentProvisioningErrorCategory.LIMIT_EXCEEDED: (
        "Kubernetes refused to create it because it asks for more than the namespace allows for one resource."
    ),
}

_ACTIVE_STATUSES = frozenset(status for status in AgentStatus if status != AgentStatus.STOPPED)


# --- identity -------------------------------------------------------------


def identities_by_id(identities: Iterable[PlatformAgentIdentity]) -> dict[UUID, PlatformAgentIdentity]:
    return {identity.id: identity for identity in identities}


def agent_ref(agent_id: UUID, identities: Mapping[UUID, PlatformAgentIdentity]) -> AgentRefRead:
    identity = identities.get(agent_id)
    if identity is None:
        return AgentRefRead(agent_id=agent_id)
    return AgentRefRead(
        agent_id=agent_id,
        agent_name=identity.name,
        organization_id=identity.organization_id,
        organization_name=identity.organization_name,
        status=identity.status,
    )


def _uuid(raw: str | None) -> UUID | None:
    try:
        return UUID(raw) if raw else None
    except ValueError:
        return None


def agent_id_from_app(app: str | None) -> UUID | None:
    """`agent-<uuid>`, the `app` label of an Agent's resources and its Prometheus series."""
    match = _AGENT_APP.fullmatch(app or "")
    return _uuid(match.group(1)) if match else None


def _agent_id_from_labels(labels: Mapping[str, str]) -> UUID | None:
    return agent_id_from_app(labels.get("app")) or _uuid(labels.get(AGENT_ID_LABEL_KEY))


def _kind(labels: Mapping[str, str]) -> WorkloadKind:
    """What an object belongs to, from the labels this platform sets.

    An Agent's claims are created once and never relabelled, so older ones carry the
    pre-rebrand `agentfarm.io/component` label or no component label at all. Every Agent object
    carries `app=agent-<uuid>`, whichever labels it was created with, so that label is enough on its own.
    """
    component = labels.get(COMPONENT_LABEL_KEY)
    if component == RESTORE_POINT_COMPONENT:
        return WorkloadKind.RESTORE_POINT
    if component == AGENT_COMPONENT or agent_id_from_app(labels.get("app")) is not None:
        return WorkloadKind.AGENT
    return WorkloadKind.INFRASTRUCTURE


def _name(raw: str | None) -> str | None:
    return raw if raw and _OBJECT_NAME.fullmatch(raw) else None


def quantity(raw: object) -> float | None:
    """A Kubernetes quantity ("1Gi", "500m") as a number, or None when it is not one."""
    if raw is None:
        return None
    try:
        value: Decimal = parse_quantity(raw)
    except ValueError, InvalidOperation, TypeError:
        return None
    return float(value)


# --- core services --------------------------------------------------------


def core_services(
    deployments: Sequence[V1Deployment],
    stateful_sets: Sequence[V1StatefulSet],
    replica_sets: Sequence[V1ReplicaSet] | None = None,
) -> list[CoreServiceRead]:
    """The platform's own Deployments and StatefulSets. An Agent's Deployment is not one.

    `replica_sets` date each Deployment's rollout; see `_rollout`.
    """
    revisions = _replica_set_revisions(replica_sets or [])
    services: list[CoreServiceRead] = []
    for kind, workloads in (("Deployment", deployments), ("StatefulSet", stateful_sets)):
        for workload in workloads:
            metadata = workload.metadata
            if _kind(metadata.labels or {}) != WorkloadKind.INFRASTRUCTURE:
                continue
            name = _name(metadata.name)
            if name is None:
                continue
            desired = workload.spec.replicas if workload.spec and workload.spec.replicas is not None else 1
            ready = (workload.status.ready_replicas if workload.status else None) or 0
            level = _replica_level(desired, ready)
            build_sha = rollout = rolled_out_at = None
            if isinstance(workload, V1Deployment):
                build_sha = _build_sha(workload)
                rollout, rolled_out_at = _rollout(workload, revisions)
                if rollout == RolloutState.STUCK and level == HealthLevel.OK:
                    level = HealthLevel.WARNING
            services.append(
                CoreServiceRead(
                    name=name,
                    kind=kind,
                    desired_replicas=desired,
                    ready_replicas=ready,
                    level=level,
                    build_sha=build_sha,
                    rollout=rollout,
                    rolled_out_at=rolled_out_at,
                )
            )
    services.sort(key=lambda service: (_LEVEL_ORDER[service.level], service.name))
    return services


def _build_sha(deployment: V1Deployment) -> str | None:
    template = deployment.spec.template if deployment.spec else None
    annotations = (template.metadata.annotations if template and template.metadata else None) or {}
    sha = annotations.get(BUILD_SHA_ANNOTATION)
    return sha if isinstance(sha, str) and _BUILD_SHA.fullmatch(sha) else None


_REVISION_ANNOTATION = "deployment.kubernetes.io/revision"


def _replica_set_revisions(replica_sets: Sequence[V1ReplicaSet]) -> dict[tuple[str, str], datetime]:
    """When each Deployment's ReplicaSet of each revision was made, by (Deployment, revision)."""
    made: dict[tuple[str, str], datetime] = {}
    for replica_set in replica_sets:
        metadata = replica_set.metadata
        owner = _controller(metadata)
        revision = (metadata.annotations or {}).get(_REVISION_ANNOTATION)
        if owner and owner.kind == "Deployment" and owner.name and revision and metadata.creation_timestamp:
            made[owner.name, revision] = metadata.creation_timestamp
    return made


def _rollout(
    deployment: V1Deployment, revisions: Mapping[tuple[str, str], datetime]
) -> tuple[RolloutState | None, datetime | None]:
    """Where the Deployment's latest rollout stands, and when it started if it is done.

    The state is the `Progressing` condition's reason, never its message. The condition also
    moves when an unchanged pod recovers, so the rollout counts as under way only while pods
    are still being replaced, and its time is when the current ReplicaSet was made, which
    only a new rollout changes. Without the ReplicaSets, the condition's time stands in.
    """
    conditions = (deployment.status.conditions if deployment.status else None) or []
    progressing = next((condition for condition in conditions if condition.type == "Progressing"), None)
    if progressing is None:
        return None, None
    if progressing.reason == "ProgressDeadlineExceeded":
        return RolloutState.STUCK, None
    status = deployment.status
    desired = deployment.spec.replicas if deployment.spec and deployment.spec.replicas is not None else 1
    replacing = (status.observed_generation or 0) < (deployment.metadata.generation or 0) or (
        status.updated_replicas or 0
    ) < desired
    if progressing.reason != "NewReplicaSetAvailable" and replacing:
        return RolloutState.IN_PROGRESS, None
    revision = (deployment.metadata.annotations or {}).get(_REVISION_ANNOTATION)
    made = revisions.get((deployment.metadata.name, revision)) if revision else None
    return RolloutState.COMPLETE, made or progressing.last_update_time


_NEVER = datetime.min.replace(tzinfo=UTC)


def deployed_version(services: Sequence[CoreServiceRead]) -> DeployedVersionRead | None:
    """The build rolled out most recently, and the services that run another one.

    None when no Deployment carries a build. A service still rolling out has no finish time,
    so it never decides the build; it is listed as behind until it finishes.
    """
    built = [service for service in services if service.build_sha]
    if not built:
        return None
    # Rollouts of one deploy can finish in the same second; then the build most services run wins.
    votes = Counter(service.build_sha for service in built)
    newest = max(
        built,
        key=lambda service: (
            service.rolled_out_at is not None,
            service.rolled_out_at or _NEVER,
            votes[service.build_sha],
        ),
    )
    behind = sorted(service.name for service in built if service.build_sha != newest.build_sha)
    assert newest.build_sha is not None
    return DeployedVersionRead(
        build_sha=newest.build_sha, rolled_out_at=newest.rolled_out_at, mixed=bool(behind), behind=behind
    )


def _replica_level(desired: int, ready: int) -> HealthLevel:
    if desired == 0 or ready >= desired:
        return HealthLevel.OK
    return HealthLevel.CRITICAL if ready == 0 else HealthLevel.WARNING


_LEVEL_ORDER = {HealthLevel.CRITICAL: 0, HealthLevel.WARNING: 1, HealthLevel.UNKNOWN: 2, HealthLevel.OK: 3}


# --- volumes --------------------------------------------------------------


def requested_storage(claim: V1PersistentVolumeClaim) -> float | None:
    """What the claim requests, which is what `requests.storage` charges for it."""
    resources = claim.spec.resources if claim.spec else None
    requests = (resources.requests if resources else None) or {}
    return quantity(requests.get("storage"))


def storage_committed(claims: Sequence[V1PersistentVolumeClaim]) -> float:
    """Every claim's request added up. A terminating claim counts until it is gone, as the quota counts it."""
    return sum(requested_storage(claim) or 0.0 for claim in claims)


def volume_allocation(
    claims: Sequence[V1PersistentVolumeClaim], identities: Mapping[UUID, PlatformAgentIdentity]
) -> VolumeAllocationRead:
    """Every claim in the namespace, by what it belongs to.

    An Agent's claim is placed by its Agent's status in the database: stopped, any other live
    status, or orphaned when no live Agent has that id. A claim this platform did not label
    is infrastructure (the databases, Redis, monitoring).
    """
    groups = {group: VolumeGroupRead(group=group) for group in VolumeGroup}
    attention: list[VolumeClaimRead] = []
    total = 0.0
    for claim in claims:
        labels = claim.metadata.labels or {}
        kind = _kind(labels)
        agent_id = _agent_id_from_labels(labels) if kind != WorkloadKind.INFRASTRUCTURE else None
        if kind == WorkloadKind.RESTORE_POINT:
            group = VolumeGroup.RESTORE_POINTS
        elif kind == WorkloadKind.AGENT and agent_id is not None:
            identity = identities.get(agent_id)
            if identity is None:
                group = VolumeGroup.ORPHANED
            elif identity.status == AgentStatus.STOPPED:
                group = VolumeGroup.STOPPED_AGENTS
            else:
                group = VolumeGroup.ACTIVE_AGENTS
        else:
            group = VolumeGroup.INFRASTRUCTURE

        size = requested_storage(claim)
        groups[group].claims += 1
        groups[group].requested_bytes += int(size or 0)
        total += size or 0.0

        phase = "Terminating" if claim.metadata.deletion_timestamp else (claim.status.phase if claim.status else None)
        phase = phase if phase in _CLAIM_PHASES | {"Terminating"} else None
        name = _name(claim.metadata.name)
        if name is not None and (group == VolumeGroup.ORPHANED or phase != "Bound"):
            attention.append(
                VolumeClaimRead(
                    name=name,
                    group=group,
                    phase=phase,
                    requested_bytes=None if size is None else int(size),
                    agent=agent_ref(agent_id, identities) if agent_id else None,
                    created_at=claim.metadata.creation_timestamp,
                )
            )

    attention.sort(key=lambda row: (row.group != VolumeGroup.ORPHANED, row.name))
    return VolumeAllocationRead(
        total_claims=len(claims),
        total_requested_bytes=int(total),
        groups=list(groups.values()),
        attention=attention,
    )


# --- pods -----------------------------------------------------------------


def services_committed(services: Sequence[V1Service]) -> int:
    """What the `services` quota counts: every Service in the namespace, the Agents' included."""
    return len(services)


def pods_committed(pods: Sequence[V1Pod]) -> int:
    """The pods the `pods` quota line counts: every one not yet Succeeded or Failed."""
    return sum(1 for pod in pods if (pod.status.phase if pod.status else None) not in {"Succeeded", "Failed"})


def _ready(pod: V1Pod) -> bool:
    conditions = (pod.status.conditions if pod.status else None) or []
    return any(condition.type == "Ready" and condition.status == "True" for condition in conditions)


def _unschedulable(pod: V1Pod) -> bool:
    conditions = (pod.status.conditions if pod.status else None) or []
    return any(
        condition.type == "PodScheduled" and condition.status == "False" and condition.reason == "Unschedulable"
        for condition in conditions
    )


def _workload_name(pod: V1Pod) -> str | None:
    """The Deployment, StatefulSet or Job a pod belongs to, from its owner."""
    owners = pod.metadata.owner_references or []
    owner = next((owner for owner in owners if owner.controller), owners[0] if owners else None)
    if owner is None:
        return None
    name = owner.name or ""
    template_hash = (pod.metadata.labels or {}).get("pod-template-hash")
    if owner.kind == "ReplicaSet" and template_hash and name.endswith(f"-{template_hash}"):
        name = name[: -len(template_hash) - 1]
    return _name(name)


class PodRestarts(NamedTuple):
    """A pod's restart history over `RESTART_HISTORY_WINDOW`: how often, and whether memory ran out."""

    restarts: int
    oom_killed: bool


def pod_restarts(samples: Iterable[PrometheusSample]) -> dict[str, PodRestarts]:
    """Restart history by pod uid, from the two tagged halves of the restart query.

    Keyed by the pod's uid, or by its name when the sample carries no valid uid (an older
    kube-state-metrics). Only that key and two numbers are kept. A sample whose pod is not a
    valid object name, or whose tag is neither half, is dropped.
    """
    restarts: dict[str, int] = {}
    oom_killed: set[str] = set()
    for sample in samples:
        name = _name(sample.labels.get("pod"))
        signal = sample.labels.get("signal")
        if name is None:
            continue
        uid = _uuid(sample.labels.get("uid"))
        key = str(uid) if uid else name
        if signal == "restarts":
            # `increase()` extrapolates, so a count of 15 can come back as 14.97.
            restarts[key] = restarts.get(key, 0) + round(sample.value)
        elif signal == "oom_killed" and sample.value > 0:
            oom_killed.add(key)
    return {
        key: PodRestarts(restarts=restarts.get(key, 0), oom_killed=key in oom_killed)
        for key in restarts.keys() | oom_killed
    }


def _restart_history(pod: V1Pod, restarts: Mapping[str, PodRestarts]) -> PodRestarts | None:
    """The pod's history by its uid, or by its name when the history is keyed by name."""
    uid = pod.metadata.uid
    return (restarts.get(uid) if uid else None) or restarts.get(pod.metadata.name or "")


def agent_pod_readiness(pods: Sequence[V1Pod]) -> dict[UUID, bool]:
    """Whether each Agent has a ready pod. Two pods of one Agent in a rollout read as ready if either is."""
    ready: dict[UUID, bool] = {}
    for pod in pods:
        labels = pod.metadata.labels or {}
        if _kind(labels) != WorkloadKind.AGENT:
            continue
        agent_id = agent_id_from_app(labels.get("app"))
        if agent_id is not None:
            ready[agent_id] = ready.get(agent_id, False) or _ready(pod)
    return ready


def without_cron_runs(read: WorkloadsRead, finished_runs: set[str]) -> WorkloadsRead:
    """Drop the pods of finished CronJob runs, whose failures the scheduled jobs list already shows.

    `finished_runs` are the Job names from `finished_cron_runs`. A run still under way stays:
    the scheduled jobs list only calls it running, so a run stuck unscheduled or failing to
    pull its image is shown here. Pod counts are left as they are.
    """
    return read.model_copy(
        update={"issues": [issue for issue in read.issues if issue.workload_name not in finished_runs]}
    )


def workloads(
    pods: Sequence[V1Pod],
    identities: Mapping[UUID, PlatformAgentIdentity],
    now: datetime,
    restarts: Mapping[str, PodRestarts] | None = None,
) -> WorkloadsRead:
    """Counts of the namespace's pods, and the ones that need a look.

    A pod needs a look when it has failed, cannot be scheduled, is waiting on a failure
    (a crash loop, an image that will not pull), keeps restarting, was OOM-killed within
    `RESTART_HISTORY_WINDOW`, or is still not ready after its startup grace. A finished Job's
    pod is not counted.

    With `restarts` (the restart history), a pod keeps restarting when it restarted
    `REPEATED_RESTARTS` times within the window, however long ago the last one was. A pod
    the history does not cover, or every pod when it could not be read, is judged by the pod
    alone: that many restarts in its life, the last within `RECENT_RESTART_WINDOW`.
    """
    total = ready_count = 0
    issues: list[PodIssueRead] = []
    for pod in pods:
        status = pod.status
        phase = status.phase if status else None
        if phase == "Succeeded":
            continue
        total += 1
        ready = _ready(pod)
        ready_count += ready

        statuses = [
            *((status.init_container_statuses if status else None) or []),
            *((status.container_statuses if status else None) or []),
        ]
        restart_total = sum(container.restart_count or 0 for container in statuses)
        waiting_reasons = [
            container.state.waiting.reason
            for container in statuses
            if container.state and container.state.waiting and container.state.waiting.reason in _WAITING
        ]
        waiting = next((reason for reason in waiting_reasons if reason in _TERMINAL_WAITING), None) or next(
            iter(waiting_reasons), None
        )
        termination, last_restart_at = _last_termination(statuses)
        if status and status.reason == "Evicted":
            termination = "Evicted"
        unschedulable = _unschedulable(pod)
        created = pod.metadata.creation_timestamp
        starting = created is not None and now - created < STARTUP_GRACE
        # A restart with no recorded time is treated as recent: unknown is not "long ago".
        recently_restarted = last_restart_at is None or now - last_restart_at <= RECENT_RESTART_WINDOW
        history = _restart_history(pod, restarts) if restarts is not None else None
        if history is not None:
            repeatedly_restarting = history.restarts >= REPEATED_RESTARTS
        else:
            repeatedly_restarting = restart_total >= REPEATED_RESTARTS and recently_restarted
        oom_killed = (history is not None and history.oom_killed) or (
            termination == "OOMKilled"
            and last_restart_at is not None
            and now - last_restart_at <= RESTART_HISTORY_WINDOW
        )

        needs_look = (
            phase == "Failed"
            or unschedulable
            or waiting in _TERMINAL_WAITING
            or repeatedly_restarting
            or oom_killed
            or (not ready and not starting)
        )
        name = _name(pod.metadata.name)
        if not needs_look or name is None:
            continue
        labels = pod.metadata.labels or {}
        kind = _kind(labels)
        agent_id = _agent_id_from_labels(labels) if kind != WorkloadKind.INFRASTRUCTURE else None
        issues.append(
            PodIssueRead(
                pod_name=name,
                workload_name=_workload_name(pod),
                kind=kind,
                agent=agent_ref(agent_id, identities) if agent_id else None,
                phase=phase if phase in _POD_PHASES else None,
                ready=ready,
                unschedulable=unschedulable,
                restart_count=restart_total,
                restarts_in_window=history.restarts if history is not None else None,
                repeatedly_restarting=repeatedly_restarting,
                oom_killed=oom_killed,
                waiting_reason=waiting,
                termination_reason=termination,
                last_restart_at=last_restart_at,
                created_at=created,
            )
        )

    # Infrastructure first, since everything else depends on it; then the most restarts.
    issues.sort(
        key=lambda issue: (
            issue.kind != WorkloadKind.INFRASTRUCTURE,
            -(issue.restarts_in_window if issue.restarts_in_window is not None else issue.restart_count),
            issue.pod_name,
        )
    )
    return WorkloadsRead(pods_total=total, pods_ready=ready_count, issues=issues)


def _last_termination(statuses: Sequence) -> tuple[str | None, datetime | None]:
    """Why the most recent container ended, and when, from its current or last state."""
    latest: tuple[str | None, datetime | None] = (None, None)
    for container in statuses:
        for state in (container.state, container.last_state):
            terminated = state.terminated if state else None
            if terminated is None:
                continue
            finished = terminated.finished_at
            if latest[1] is None or (finished is not None and finished > latest[1]):
                reason = terminated.reason if terminated.reason in _TERMINATION else None
                latest = (reason, finished)
    return latest


# --- cron jobs ------------------------------------------------------------


def _job_outcome(job: V1Job) -> tuple[bool, datetime | None] | None:
    """(failed, when) for a finished Job, from its condition types only; None while it runs."""
    for condition in (job.status.conditions if job.status else None) or []:
        if condition.status != "True":
            continue
        if condition.type == "Failed":
            return True, condition.last_transition_time
        if condition.type == "Complete":
            return False, condition.last_transition_time
    return None


def _cron_owner(job: V1Job) -> str | None:
    for owner in job.metadata.owner_references or []:
        if owner.kind == "CronJob":
            return owner.name
    return None


def finished_cron_runs(jobs: Sequence[V1Job]) -> set[str]:
    """The names of the Jobs a CronJob started that have completed or failed."""
    return {
        job.metadata.name
        for job in jobs
        if job.metadata.name and _cron_owner(job) is not None and _job_outcome(job) is not None
    }


_CRON_ORDER = {CronJobState.FAILING: 0, CronJobState.STALLED: 1, CronJobState.OK: 2, CronJobState.SUSPENDED: 3}


def cron_jobs(cron_jobs: Sequence[V1CronJob], jobs: Sequence[V1Job], now: datetime) -> list[CronJobRead]:
    """The platform's CronJobs, failing and stalled ones first.

    Failing when the newest finished run Kubernetes still keeps failed. Stalled when, not
    suspended, nothing succeeded within `CRON_STALL_AFTER`. A Job's reason and message are
    never read, only whether it completed or failed, and when.
    """
    runs: dict[str, list[tuple[datetime | None, bool, datetime | None]]] = {}
    for job in jobs:
        owner = _cron_owner(job)
        outcome = _job_outcome(job)
        if owner is None or outcome is None:
            continue
        failed, finished = outcome
        runs.setdefault(owner, []).append((job.metadata.creation_timestamp, failed, finished))

    rows: list[CronJobRead] = []
    for cron in cron_jobs:
        metadata = cron.metadata
        if _kind(metadata.labels or {}) != WorkloadKind.INFRASTRUCTURE:
            continue
        name = _name(metadata.name)
        if name is None:
            continue
        status = cron.status
        last_success = status.last_successful_time if status else None
        finished = sorted(runs.get(metadata.name, []), key=lambda run: run[0] or _NEVER)
        newest_failed = bool(finished) and finished[-1][1]
        last_failed_at = max((run[2] for run in finished if run[1] and run[2] is not None), default=None)
        created = metadata.creation_timestamp
        old_enough = created is None or now - created > CRON_STALL_AFTER
        if cron.spec and cron.spec.suspend:
            state = CronJobState.SUSPENDED
        elif newest_failed:
            state = CronJobState.FAILING
        elif old_enough and (last_success is None or now - last_success > CRON_STALL_AFTER):
            state = CronJobState.STALLED
        else:
            state = CronJobState.OK
        schedule = cron.spec.schedule if cron.spec else None
        rows.append(
            CronJobRead(
                name=name,
                schedule=schedule if isinstance(schedule, str) and _CRON_SCHEDULE.fullmatch(schedule) else None,
                state=state,
                running=bool(status and status.active),
                last_scheduled_at=status.last_schedule_time if status else None,
                last_successful_at=last_success,
                last_failed_at=last_failed_at,
            )
        )
    rows.sort(key=lambda row: (_CRON_ORDER[row.state], row.name))
    return rows


def scheduled_backups(
    health: ScheduledBackupHealth,
    identities: Mapping[UUID, PlatformAgentIdentity],
    *,
    failure_window_hours: int,
    limit: int = LIST_LIMIT,
) -> ScheduledBackupsRead:
    """Failing and overdue scheduled backups: how many Agents, and the worst `limit` of each by name.

    An Agent whose backups fail is usually overdue too, so it is counted and named once,
    as failing.
    """
    failures = sorted(health.failures, key=lambda row: (-row.failures, -row.last_failed_at.timestamp()))
    failing = {row.agent_id for row in failures}
    overdue = sorted(
        (row for row in health.overdue if row.agent_id not in failing),
        key=lambda row: row.last_backup_at or _NEVER,
    )
    return ScheduledBackupsRead(
        enabled=health.interval_minutes > 0,
        interval_minutes=health.interval_minutes,
        failure_window_hours=failure_window_hours,
        running_agents=sum(1 for identity in identities.values() if identity.status == AgentStatus.RUNNING),
        failed_total=len(failures),
        overdue_total=len(overdue),
        failed=[
            BackupFailureRead(
                agent=agent_ref(row.agent_id, identities), failures=row.failures, last_failed_at=row.last_failed_at
            )
            for row in failures[:limit]
        ],
        overdue=[
            OverdueBackupRead(agent=agent_ref(row.agent_id, identities), last_backup_at=row.last_backup_at)
            for row in overdue[:limit]
        ],
    )


# --- idle agents ----------------------------------------------------------

IDLE_STATUSES = frozenset({AgentStatus.RUNNING, AgentStatus.STOPPED})


def idle_agents(
    identities: Mapping[UUID, PlatformAgentIdentity],
    *,
    last_user_message: Mapping[UUID, datetime],
    last_call: Mapping[UUID, datetime],
    pods: Sequence[V1Pod] | None,
    claims: Sequence[V1PersistentVolumeClaim] | None,
    restore_points: Mapping[UUID, tuple[int, int]],
    now: datetime,
    idle_after: timedelta,
) -> list[IdleAgentRead]:
    """Running or stopped Agents no person has written to within `idle_after`, never-used first.

    Only a person's message counts as use. A model call can be the platform waking the Agent
    (a heartbeat, a schedule, a platform-wide restart), so it is shown but never decides. An
    Agent younger than `idle_after` has not had the chance to be used, and an Agent in ERROR is
    shown with its failure instead. Claims are linked by the Agent id in their labels, the
    Agent's own and its restore points'.
    """
    with_pod = agent_pod_readiness(pods) if pods is not None else None
    held: dict[UUID, list[float]] = {}
    for claim in claims or []:
        agent_id = _agent_id_from_labels(claim.metadata.labels or {})
        if agent_id is not None:
            held.setdefault(agent_id, []).append(requested_storage(claim) or 0.0)

    rows: list[IdleAgentRead] = []
    for agent_id, identity in identities.items():
        if identity.status not in IDLE_STATUSES:
            continue
        if identity.created_at is not None and now - identity.created_at < idle_after:
            continue
        last_message = last_user_message.get(agent_id)
        if last_message is not None and now - last_message < idle_after:
            continue
        sizes = held.get(agent_id, [])
        count, archive_bytes = restore_points.get(agent_id, (0, 0))
        rows.append(
            IdleAgentRead(
                agent=agent_ref(agent_id, identities),
                last_user_message_at=last_message,
                last_call_at=last_call.get(agent_id),
                holds_pod=None if with_pod is None else agent_id in with_pod,
                volume_claims=None if claims is None else len(sizes),
                requested_bytes=None if claims is None else int(sum(sizes)),
                restore_points=count,
                restore_point_bytes=archive_bytes,
            )
        )
    rows.sort(key=lambda row: (row.last_user_message_at or _NEVER, row.agent.agent_name or ""))
    return rows


# --- capacity -------------------------------------------------------------


def capacity_level(
    used: float | None, hard: float | None, source: CapacitySource
) -> tuple[float | None, CapacityLevel]:
    if used is None or hard is None:
        return None, CapacityLevel.UNKNOWN
    if hard <= 0:
        # A quota of zero allows nothing more.
        return None, CapacityLevel.CRITICAL
    ratio = used / hard
    if ratio > 1 and source == CapacitySource.ENTERED:
        return ratio, CapacityLevel.CEILING_OUT_OF_DATE
    if ratio >= CRITICAL_RATIO:
        return ratio, CapacityLevel.CRITICAL
    if ratio >= WARN_RATIO:
        return ratio, CapacityLevel.WARNING
    return ratio, CapacityLevel.OK


def _unit(resource: str) -> CapacityUnit:
    if resource.endswith(("memory", "storage")):
        return CapacityUnit.BYTES
    if resource.endswith("cpu"):
        return CapacityUnit.CORES
    return CapacityUnit.COUNT


def _line(resource: str, used: float | None, hard: float | None, source: CapacitySource) -> CapacityLineRead:
    ratio, level = capacity_level(used, hard, source)
    return CapacityLineRead(
        resource=resource, unit=_unit(resource), source=source, used=used, hard=hard, ratio=ratio, level=level
    )


def _ordered(lines: Iterable[CapacityLineRead]) -> list[CapacityLineRead]:
    def key(line: CapacityLineRead) -> tuple[int, str]:
        position = _QUOTA_ORDER.index(line.resource) if line.resource in _QUOTA_ORDER else len(_QUOTA_ORDER)
        return position, line.resource

    return sorted(lines, key=key)


def quota_lines(quotas: Sequence[V1ResourceQuota]) -> list[CapacityLineRead]:
    """The namespace's own ResourceQuota figures, one line per resource.

    Where two quotas cap the same resource, the one nearer its limit is the one that refuses
    first, so it is kept. Quota names are not carried: they are chosen by the cluster's owners.
    """
    lines: dict[str, CapacityLineRead] = {}
    for quota in quotas:
        status = quota.status
        hard_values = (status.hard if status else None) or {}
        used_values = (status.used if status else None) or {}
        for resource, raw_hard in hard_values.items():
            if not _QUOTA_RESOURCE.fullmatch(resource):
                continue
            line = _line(resource, quantity(used_values.get(resource, "0")), quantity(raw_hard), CapacitySource.QUOTA)
            current = lines.get(resource)
            # A zero quota blocks all creation and has no finite ratio.
            if current is None or (line.hard == 0, line.ratio or 0) > (current.hard == 0, current.ratio or 0):
                lines[resource] = line
    return _ordered(lines.values())


def entered_lines(
    capacity: PlatformCapacityRead,
    *,
    storage_requested: float | None,
    pods_counted: int | None,
    storage_ceiling: int | None,
    pods_ceiling: int | None,
    claims_counted: int | None = None,
    claims_ceiling: int | None = None,
    services_counted: int | None = None,
    services_ceiling: int | None = None,
) -> list[CapacityLineRead]:
    """The ceilings a Platform Administrator entered, beside what the API counts.

    CPU and memory are what kube-state-metrics says the pods commit, as on the Platform
    resource usage page; storage, pods, volume claims and Services are counted from what the
    API lists. A figure that could not be read is None, never zero.
    """
    entered = CapacitySource.ENTERED
    return _ordered(
        [
            _line("requests.storage", storage_requested, as_float(storage_ceiling), entered),
            _line("persistentvolumeclaims", as_float(claims_counted), as_float(claims_ceiling), entered),
            _line("pods", as_float(pods_counted), as_float(pods_ceiling), entered),
            _line("services", as_float(services_counted), as_float(services_ceiling), entered),
            _line(
                "limits.memory",
                as_float(capacity.committed_limits_memory_bytes),
                as_float(capacity.limits_memory_bytes),
                entered,
            ),
            _line(
                "requests.memory",
                as_float(capacity.committed_requests_memory_bytes),
                as_float(capacity.requests_memory_bytes),
                entered,
            ),
            _line("limits.cpu", capacity.committed_limits_cpu_cores, capacity.limits_cpu_cores, entered),
            _line("requests.cpu", capacity.committed_requests_cpu_cores, capacity.requests_cpu_cores, entered),
        ]
    )


def with_peaks(lines: Iterable[CapacityLineRead], peaks: Mapping[str, float | None]) -> list[CapacityLineRead]:
    """Each line with the highest figure it reached over the peak window beside it.

    A line that is quiet now but touched its critical threshold in the window is a warning: a
    pod starting at that moment, such as a scheduled job, would have been refused. A peak never
    lowers a level, and a line with no ceiling keeps its peak without a ratio.

    A peak is never below the current figure. The current figure is read from the cluster now
    and the peak from samples 30 seconds apart, so a pod that started since the last sample is
    in the first and not yet in the second.
    """
    result = []
    for line in lines:
        peak = peaks.get(line.resource)
        if peak is None:
            result.append(line)
            continue
        if line.used is not None:
            peak = max(peak, line.used)
        peak_ratio = peak / line.hard if line.hard else None
        level = line.level
        if level == CapacityLevel.OK and peak_ratio is not None and peak_ratio >= CRITICAL_RATIO:
            level = CapacityLevel.WARNING
        result.append(line.model_copy(update={"peak": peak, "peak_ratio": peak_ratio, "level": level}))
    return result


def as_float(value: int | None) -> float | None:
    return None if value is None else float(value)


# --- events ---------------------------------------------------------------


def _event_time(event: CoreV1Event) -> datetime | None:
    series_time = event.series.last_observed_time if event.series else None
    return event.last_timestamp or series_time or event.event_time or event.metadata.creation_timestamp


# The characters Kubernetes draws a pod's random suffix and a ReplicaSet's template hash from.
_GENERATED = "[bcdfghjklmnpqrstvwxz2456789]"
_POD_SUFFIX = re.compile(f"{_GENERATED}{{5}}")
_TEMPLATE_HASH = re.compile(f"{_GENERATED}{{1,10}}")

Workload = tuple[str, str]


@dataclass(frozen=True)
class WorkloadOwners:
    """Which workload each pod, ReplicaSet and Job in the namespace belongs to.

    `known` comes from the objects' owner references. The name sets are for objects already
    gone, whose Events outlive them: a CronJob deletes its old runs before their Events expire.
    """

    known: dict[Workload, Workload] = field(default_factory=dict)
    deployments: frozenset[str] = frozenset()
    stateful_sets: frozenset[str] = frozenset()
    cron_jobs: frozenset[str] = frozenset()


def _controller(metadata: V1ObjectMeta) -> V1OwnerReference | None:
    owners = metadata.owner_references or []
    return next((owner for owner in owners if owner.controller), owners[0] if owners else None)


def workload_owners(
    *,
    deployments: Sequence[V1Deployment],
    stateful_sets: Sequence[V1StatefulSet],
    cron_jobs: Sequence[V1CronJob],
    replica_sets: Sequence[V1ReplicaSet],
    jobs: Sequence[V1Job],
    pods: Sequence[V1Pod],
) -> WorkloadOwners:
    """The owner of each pod, ReplicaSet and Job, followed up to its Deployment, StatefulSet or CronJob.

    A Job no CronJob started is its own workload, so the chart's one-off Jobs are never read
    as the Deployment whose name they start with.
    """
    known: dict[Workload, Workload] = {}
    for replica_set in replica_sets:
        owner = _controller(replica_set.metadata)
        if replica_set.metadata.name and owner and owner.kind == "Deployment" and owner.name:
            known["ReplicaSet", replica_set.metadata.name] = ("Deployment", owner.name)
    for job in jobs:
        name = job.metadata.name
        if name:
            cron = _cron_owner(job)
            known["Job", name] = ("CronJob", cron) if cron else ("Job", name)
    owners = WorkloadOwners(
        known=known,
        deployments=frozenset(d.metadata.name for d in deployments if d.metadata.name),
        stateful_sets=frozenset(s.metadata.name for s in stateful_sets if s.metadata.name),
        cron_jobs=frozenset(c.metadata.name for c in cron_jobs if c.metadata.name),
    )
    for pod in pods:
        owner = _controller(pod.metadata)
        if not pod.metadata.name or owner is None or not owner.kind or not owner.name:
            continue
        workload = _owning_workload(owner.kind, owner.name, owners) or (owner.kind, owner.name)
        known["Pod", pod.metadata.name] = workload
    return owners


def _cron_run(name: str, owners: WorkloadOwners) -> Workload | None:
    """A CronJob's run is named `<cron job>-<scheduled minute>`."""
    base, _, minute = name.rpartition("-")
    return ("CronJob", base) if base in owners.cron_jobs and minute.isdigit() else None


def _deployment_replica_set(name: str, owners: WorkloadOwners) -> Workload | None:
    """A Deployment's ReplicaSet is named `<deployment>-<template hash>`."""
    base, _, template_hash = name.rpartition("-")
    return ("Deployment", base) if base in owners.deployments and _TEMPLATE_HASH.fullmatch(template_hash) else None


def _owning_workload(kind: str | None, name: str | None, owners: WorkloadOwners) -> Workload | None:
    """The Deployment, StatefulSet, CronJob or Job a pod, ReplicaSet or Job belongs to.

    From its owner references when the object is still there. Otherwise from its name, read
    only in the exact shape its controller gives it, so `api-gateway-…` is not read as `api`.
    """
    if kind not in {"Pod", "ReplicaSet", "Job"} or not name:
        return None
    known = owners.known.get((kind, name))
    if known is not None:
        return known
    if kind == "ReplicaSet":
        return _deployment_replica_set(name, owners)
    if kind == "Job":
        return _cron_run(name, owners)
    base, _, suffix = name.rpartition("-")
    if base in owners.stateful_sets and suffix.isdigit():
        return "StatefulSet", base
    if not _POD_SUFFIX.fullmatch(suffix):
        return None
    return owners.known.get(("Job", base)) or _cron_run(base, owners) or _deployment_replica_set(base, owners)


def warning_events(
    events: Sequence[CoreV1Event],
    identities: Mapping[UUID, PlatformAgentIdentity],
    now: datetime,
    *,
    owners: WorkloadOwners | None = None,
) -> list[WarningEventRead]:
    """The namespace's recent Warning Events, newest first.

    The message is never carried. Each Event gets the fixed explanation for its reason, and a
    quota or LimitRange rejection also gets a detail rebuilt by `cluster_rejection_detail`, held
    to the grammar a provisioning failure's detail is held to.

    Kubernetes keeps one Event per distinct message, so one failing image pull leaves several
    Events that differ only in text this page never shows. Those read as one row: the same
    reason, object and detail, with their counts added up and the latest time kept. Events
    about a workload's pods, ReplicaSets or Jobs (see `workload_owners`) are read as about the
    workload, so a CronJob failing every run is one row, not one per run.
    """
    rows: dict[tuple[str, str | None, str | None, str | None], WarningEventRead] = {}
    for event in events:
        last_seen = _event_time(event)
        if last_seen is None or now - last_seen > EVENT_WINDOW:
            continue
        reason = event.reason if event.reason and _REASON.fullmatch(event.reason) else "Unknown"
        explanation = _EVENT_EXPLANATIONS.get(reason, _GENERIC_EXPLANATION)
        detail = None
        rejection = cluster_rejection_detail(event.message or "")
        if rejection is not None:
            category, detail = rejection
            explanation = _REJECTION_EXPLANATIONS[category]

        involved = event.involved_object
        kind = involved.kind if involved and involved.kind in _EVENT_OBJECT_KINDS else None
        name = _name(involved.name) if kind and involved else None
        owner = _owning_workload(kind, name, owners or WorkloadOwners())
        if owner is not None:
            kind, name = owner
        match = _AGENT_OBJECT.fullmatch(name or "")
        agent_id = _uuid(match.group(1)) if match else None
        count = event.count or (event.series.count if event.series else None) or 1
        key = (reason, kind, name, detail)
        if key in rows:
            merged = rows[key]
            merged.count += count
            merged.last_seen = max(merged.last_seen or last_seen, last_seen)
            continue
        rows[key] = WarningEventRead(
            reason=reason,
            object_kind=kind,
            object_name=name,
            agent=agent_ref(agent_id, identities) if agent_id else None,
            count=count,
            last_seen=last_seen,
            explanation=explanation,
            detail=detail,
        )
    return sorted(rows.values(), key=lambda row: row.last_seen or now, reverse=True)


# --- Prometheus -----------------------------------------------------------


def firing_alerts(
    samples: Sequence[PrometheusSample], identities: Mapping[UUID, PlatformAgentIdentity]
) -> list[FiringAlertRead]:
    """The monitoring chart's firing alerts: the rule's name, its severity and, for an Agent's
    alert, the Agent. The rule's annotations and the series' other labels are not carried."""
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    by_identity: dict[tuple[str, UUID | None], FiringAlertRead] = {}
    for sample in samples:
        name = sample.labels.get("alertname", "")
        if not _ALERT_NAME.fullmatch(name):
            continue
        agent_id = agent_id_from_app(sample.labels.get("app"))
        severity = sample.labels.get("severity")
        severity = severity if severity in _ALERT_SEVERITIES else None
        key = (name, agent_id)
        current = by_identity.get(key)
        # Some chart rules share a name across warning and critical thresholds.
        if current is not None and severity_order.get(current.severity or "", 3) <= severity_order.get(
            severity or "", 3
        ):
            continue
        by_identity[key] = FiringAlertRead(
            name=name,
            severity=severity,
            agent=agent_ref(agent_id, identities) if agent_id else None,
        )
    alerts = list(by_identity.values())
    alerts.sort(key=lambda alert: (severity_order.get(alert.severity or "", 3), alert.name))
    return alerts


def unhealthy_runtimes(
    samples: Sequence[PrometheusSample],
    identities: Mapping[UUID, PlatformAgentIdentity],
    pod_ready: Mapping[UUID, bool],
) -> list[UnhealthyRuntimeRead]:
    """Agents whose healthz reports `agent_healthz_ok` 0, ready pod or not.

    A stopped Agent can leave a reading for a few minutes after it stops; it is left out,
    since it no longer has a runtime to be unhealthy.
    """
    ok: dict[UUID, float] = {}
    ever: dict[UUID, float] = {}
    for sample in samples:
        agent_id = agent_id_from_app(sample.labels.get("app"))
        if agent_id is None:
            continue
        metric = sample.labels.get("__name__")
        if metric == "agent_healthz_ok":
            ok[agent_id] = min(ok.get(agent_id, sample.value), sample.value)
        elif metric == "agent_healthz_ever_connected":
            ever[agent_id] = max(ever.get(agent_id, sample.value), sample.value)

    rows: list[UnhealthyRuntimeRead] = []
    for agent_id, value in ok.items():
        if value != 0:
            continue
        identity = identities.get(agent_id)
        if identity is not None and identity.status not in _ACTIVE_STATUSES:
            continue
        rows.append(
            UnhealthyRuntimeRead(
                agent=agent_ref(agent_id, identities),
                pod_ready=pod_ready.get(agent_id),
                ever_connected=None if agent_id not in ever else ever[agent_id] == 1,
            )
        )
    rows.sort(key=lambda row: (not row.pod_ready, row.agent.agent_name or ""))
    return rows


# --- failed Agents --------------------------------------------------------


def failed_agents(rows: Sequence[PlatformFailedAgent]) -> list[FailedAgentRead]:
    """Agents in ERROR, each with its failure rebuilt from the stored category."""
    failed: list[FailedAgentRead] = []
    for row in rows:
        stored = persisted_provisioning_error(
            code=row.last_error_code, detail=row.last_error_detail, legacy_message=row.last_error
        )
        failed.append(
            FailedAgentRead(
                agent=AgentRefRead(
                    agent_id=row.id,
                    agent_name=row.name,
                    organization_id=row.organization_id,
                    organization_name=row.organization_name,
                    status=AgentStatus.ERROR,
                ),
                code=stored.code if stored else None,
                summary=stored.summary if stored else None,
                detail=stored.detail if stored else None,
                updated_at=row.updated_at,
            )
        )
    return failed

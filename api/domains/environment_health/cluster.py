"""Reading Kubernetes objects and Prometheus samples into the environment health read models.

Pure functions, with no I/O, so every rule here is tested against hand-built objects. Each
one keeps only allowlisted fields: names this platform generates, fixed reason words, numbers
and times. An Agent is found by an id in a label this platform sets, and named from the
database; the `org-id`, `agent_name` and `org_name` labels are never trusted.
"""

import re
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from kubernetes.client import (
    CoreV1Event,
    V1Deployment,
    V1PersistentVolumeClaim,
    V1Pod,
    V1ResourceQuota,
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
    CapacityLevel,
    CapacityLineRead,
    CapacitySource,
    CapacityUnit,
    CoreServiceRead,
    FailedAgentRead,
    FiringAlertRead,
    HealthLevel,
    PodIssueRead,
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
REPEATED_RESTARTS = 3
RECENT_RESTART_WINDOW = timedelta(hours=1)
# A pod younger than this that is not ready yet is starting, not failing.
STARTUP_GRACE = timedelta(minutes=2)
# Warning Events older than this are history, not news. Kubernetes keeps them about an hour
# by default, so this is a bound for clusters that keep them longer.
EVENT_WINDOW = timedelta(hours=6)
MAX_EVENTS = 50

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
    component = labels.get(COMPONENT_LABEL_KEY)
    if component == AGENT_COMPONENT:
        return WorkloadKind.AGENT
    if component == RESTORE_POINT_COMPONENT:
        return WorkloadKind.RESTORE_POINT
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


def core_services(deployments: Sequence[V1Deployment], stateful_sets: Sequence[V1StatefulSet]) -> list[CoreServiceRead]:
    """The platform's own Deployments and StatefulSets. An Agent's Deployment is not one."""
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
            services.append(
                CoreServiceRead(
                    name=name,
                    kind=kind,
                    desired_replicas=desired,
                    ready_replicas=ready,
                    level=_replica_level(desired, ready),
                )
            )
    services.sort(key=lambda service: (_LEVEL_ORDER[service.level], service.name))
    return services


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


def workloads(pods: Sequence[V1Pod], identities: Mapping[UUID, PlatformAgentIdentity], now: datetime) -> WorkloadsRead:
    """Counts of the namespace's pods, and the ones that need a look.

    A pod needs a look when it has failed, cannot be scheduled, is waiting on a failure
    (a crash loop, an image that will not pull), has restarted repeatedly with the last restart
    in the past hour, or is still not ready after its startup grace. A finished Job's pod is not counted.
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
        restarts = sum(container.restart_count or 0 for container in statuses)
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
        repeatedly_restarting = restarts >= REPEATED_RESTARTS and recently_restarted

        needs_look = (
            phase == "Failed"
            or unschedulable
            or waiting in _TERMINAL_WAITING
            or repeatedly_restarting
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
                restart_count=restarts,
                repeatedly_restarting=repeatedly_restarting,
                waiting_reason=waiting,
                termination_reason=termination,
                last_restart_at=last_restart_at,
                created_at=created,
            )
        )

    # Infrastructure first, since everything else depends on it; then the most restarts.
    issues.sort(key=lambda issue: (issue.kind != WorkloadKind.INFRASTRUCTURE, -issue.restart_count, issue.pod_name))
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
            if current is None or (line.ratio or 0) > (current.ratio or 0):
                lines[resource] = line
    return _ordered(lines.values())


def entered_lines(
    capacity: PlatformCapacityRead,
    *,
    storage_requested: float | None,
    pods_counted: int | None,
    storage_ceiling: int | None,
    pods_ceiling: int | None,
) -> list[CapacityLineRead]:
    """The ceilings a Platform Administrator entered, beside what the API counts.

    CPU and memory are what kube-state-metrics says the pods commit, as on the Platform
    resource usage page; storage and pods are counted from the claims and pods the API
    lists. A figure that could not be read is None, never zero.
    """
    entered = CapacitySource.ENTERED
    return _ordered(
        [
            _line("requests.storage", storage_requested, _number(storage_ceiling), entered),
            _line("pods", None if pods_counted is None else float(pods_counted), _number(pods_ceiling), entered),
            _line(
                "limits.memory",
                _number(capacity.committed_limits_memory_bytes),
                _number(capacity.limits_memory_bytes),
                entered,
            ),
            _line(
                "requests.memory",
                _number(capacity.committed_requests_memory_bytes),
                _number(capacity.requests_memory_bytes),
                entered,
            ),
            _line("limits.cpu", capacity.committed_limits_cpu_cores, capacity.limits_cpu_cores, entered),
            _line("requests.cpu", capacity.committed_requests_cpu_cores, capacity.requests_cpu_cores, entered),
        ]
    )


def _number(value: int | None) -> float | None:
    return None if value is None else float(value)


# --- events ---------------------------------------------------------------


def _event_time(event: CoreV1Event) -> datetime | None:
    series_time = event.series.last_observed_time if event.series else None
    return event.last_timestamp or series_time or event.event_time or event.metadata.creation_timestamp


def warning_events(
    events: Sequence[CoreV1Event], identities: Mapping[UUID, PlatformAgentIdentity], now: datetime
) -> list[WarningEventRead]:
    """The namespace's recent Warning Events, newest first.

    The message is never carried. Each Event gets the fixed explanation for its reason, and a
    quota or LimitRange rejection also gets a detail rebuilt by `cluster_rejection_detail`, held
    to the grammar a provisioning failure's detail is held to.

    Kubernetes keeps one Event per distinct message, so one failing image pull leaves several
    Events that differ only in text this page never shows. Those read as one row: the same
    reason, object and detail, with their counts added up and the latest time kept.
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
    ordered = sorted(rows.values(), key=lambda row: row.last_seen or now, reverse=True)
    return ordered[:MAX_EVENTS]


# --- Prometheus -----------------------------------------------------------


def firing_alerts(
    samples: Sequence[PrometheusSample], identities: Mapping[UUID, PlatformAgentIdentity]
) -> list[FiringAlertRead]:
    """The monitoring chart's firing alerts: the rule's name, its severity and, for an Agent's
    alert, the Agent. The rule's annotations and the series' other labels are not carried."""
    seen: set[tuple[str, UUID | None]] = set()
    alerts: list[FiringAlertRead] = []
    for sample in samples:
        name = sample.labels.get("alertname", "")
        if not _ALERT_NAME.fullmatch(name):
            continue
        agent_id = agent_id_from_app(sample.labels.get("app"))
        if (name, agent_id) in seen:
            continue
        seen.add((name, agent_id))
        severity = sample.labels.get("severity")
        alerts.append(
            FiringAlertRead(
                name=name,
                severity=severity if severity in _ALERT_SEVERITIES else None,
                agent=agent_ref(agent_id, identities) if agent_id else None,
            )
        )
    severity_order = {"critical": 0, "warning": 1, "info": 2}
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

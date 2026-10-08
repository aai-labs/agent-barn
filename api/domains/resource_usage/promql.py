"""PromQL for Agent Resource Usage, and the mapping of results back to Agents.

Pure functions. Selectors are built only from Agent and Organization UUIDs that came from
the database, never from a request string, so nothing here can be steered by a caller.

An Agent's series are found by `app="agent-<agent id>"` and `org_id`. The `agent_name`
and `org_name` labels are slugs and not unique, so they are never used to find or match.
"""

from collections.abc import Iterable, Mapping, Sequence
from uuid import UUID

from api.infrastructure.prometheus.client import PrometheusSample, PrometheusSeries

_APP_PREFIX = "agent-"
_FIELD_LABEL = "usage_field"
# The shortest window `rate()` can use: it needs a few scrapes (30s apart) inside it.
_MIN_RATE_WINDOW_SECONDS = 120


def selector(organization_id: UUID, agent_ids: Sequence[UUID]) -> str:
    """Select the Agents' series. `agent_ids` must not be empty."""
    if not agent_ids:
        raise ValueError("selector needs at least one agent id")
    ids = [str(agent_id) for agent_id in dict.fromkeys(agent_ids)]
    app = f'app="{_APP_PREFIX}{ids[0]}"' if len(ids) == 1 else f'app=~"{_APP_PREFIX}({"|".join(ids)})"'
    return f'{{job="agent", org_id="{organization_id}", {app}}}'


def platform_selector() -> str:
    """Select every Agent's series, for the Platform view. Rows are matched to Agents later."""
    return '{job="agent"}'


def _tag(field: str, expression: str) -> str:
    """Name a sub-query so several can be read from one response."""
    return f'label_replace({expression}, "{_FIELD_LABEL}", "{field}", "", "")'


def _join(tagged: Iterable[str]) -> str:
    return " or ".join(tagged)


def instant_query(sel: str, window_seconds: int, throttle_window_seconds: int) -> str:
    """Current figures for the selected Agents, one row per (agent, field).

    `window_seconds` bounds how far back a limit is looked up, so an Agent that stopped
    a moment ago still reports its limits. Throttling is a ratio over its own window.
    """
    w, t = f"{window_seconds}s", f"{throttle_window_seconds}s"
    return _join(
        [
            _tag("up", f"max by (app) (up{sel})"),
            _tag("cgroup_metrics_available", f"max by (app) (agent_cgroup_metrics_available{sel})"),
            _tag("memory_working_set_bytes", f"max by (app) (agent_memory_working_set_bytes{sel})"),
            _tag("cpu_cores", f"sum by (app) (rate(agent_cpu_usage_seconds_total{sel}[5m]))"),
            _tag("memory_limit_bytes", f"max by (app) (last_over_time(agent_memory_limit_bytes{sel}[{w}]))"),
            _tag("cpu_limit_cores", f"max by (app) (last_over_time(agent_cpu_limit_cores{sel}[{w}]))"),
            _tag(
                "cpu_throttled_ratio",
                f"sum by (app) (increase(agent_cpu_throttled_periods_total{sel}[{t}]))"
                f" / clamp_min(sum by (app) (increase(agent_cpu_periods_total{sel}[{t}])), 1)",
            ),
        ]
    )


def range_query(sel: str, step_seconds: int) -> str:
    """Memory, CPU and throttling over time, one point per step."""
    s = f"{step_seconds}s"
    w = f"{max(step_seconds, _MIN_RATE_WINDOW_SECONDS)}s"
    return _join(
        [
            # The highest reading in each step, so a short spike is not averaged away.
            _tag("memory_working_set_bytes", f"max by (app) (max_over_time(agent_memory_working_set_bytes{sel}[{s}]))"),
            _tag("cpu_cores", f"sum by (app) (rate(agent_cpu_usage_seconds_total{sel}[{w}]))"),
            _tag(
                "cpu_throttled_ratio",
                f"sum by (app) (rate(agent_cpu_throttled_periods_total{sel}[{w}]))"
                f" / clamp_min(sum by (app) (rate(agent_cpu_periods_total{sel}[{w}])), 1e-9)",
            ),
        ]
    )


def platform_range_query(sel: str, step_seconds: int) -> str:
    """Memory and CPU of all the selected Agents together, one point per step.

    Memory adds up each Agent's highest reading in the step. Agents rarely peak at the
    same moment, so this can sit a little above the true combined peak, never below it.
    There is no throttling series: a ratio summed across Agents means nothing.
    """
    s = f"{step_seconds}s"
    w = f"{max(step_seconds, _MIN_RATE_WINDOW_SECONDS)}s"
    return _join(
        [
            _tag(
                "memory_working_set_bytes",
                f"sum(max by (app) (max_over_time(agent_memory_working_set_bytes{sel}[{s}])))",
            ),
            _tag("cpu_cores", f"sum(rate(agent_cpu_usage_seconds_total{sel}[{w}]))"),
        ]
    )


_KIND_LABEL = "kind"
_KSM = 'job="kube-state-metrics"'
# What a ResourceQuota can hold a ceiling for, and what the page can draw: both of these.
COMMITMENT_KINDS = ("limits", "requests")


def _effective_pod(kind: str, pod_matcher: str = "") -> str:
    """Per pod and resource, what a ResourceQuota charges the pod for `kind` (limits or requests).

    A pod is charged the larger of its containers added up and its biggest init container
    (https://kubernetes.io/docs/concepts/workloads/pods/init-containers/#resource-sharing-within-containers).
    An init container runs once and exits, but it still reserves its share for the pod's whole life.
    Reading only the containers under-counts any pod whose init container is the bigger one.

    The two halves get a `part` label before they are joined with `or`. Without it, a pod's
    init series and container series carry the same labels and `or` would drop the init one.
    Restartable init containers (sidecars) are charged by adding, not by the larger of; none
    run here, so they are not told apart.
    """
    pick = f'{{{_KSM}, resource=~"memory|cpu"{pod_matcher}}}'
    containers = f"sum by (namespace, pod, resource) (kube_pod_container_resource_{kind}{pick})"
    init = f"max by (namespace, pod, resource) (kube_pod_init_container_resource_{kind}{pick})"
    return (
        "max by (namespace, pod, resource) ("
        f'label_replace({containers}, "part", "containers", "", "")'
        " or "
        f'label_replace({init}, "part", "init", "", "")'
        ")"
    )


def namespace_commitments_query() -> str:
    """What every Pending or Running pod in the namespace commits, by resource and kind.

    This is what a ResourceQuota counts for `limits.memory`, `limits.cpu`, `requests.memory`
    and `requests.cpu`, so it is the figure to hold against the ceilings an administrator
    enters. It comes from kube-state-metrics, which already runs in the namespace under the
    tenant account, so reading it needs no new permission. It covers every pod (API, UI,
    database, Agents), including Agents that do not report through their own healthz server yet.

    Pinned to the `kube-state-metrics` job, as the Agent queries are pinned to `agent`.
    A pod that finished (Succeeded or Failed) no longer counts, as with the quota.
    """
    live = f'(kube_pod_status_phase{{{_KSM}, phase=~"Pending|Running"}} == 1)'
    return " or ".join(
        f"label_replace(sum by (resource) ({_effective_pod(kind)} * on (namespace, pod) group_left () {live}),"
        f' "{_KIND_LABEL}", "{kind}", "", "")'
        for kind in COMMITMENT_KINDS
    )


# A pod of an Agent is named after its Deployment, `agent-<uuid>`, then its ReplicaSet and pod
# hashes. Restore jobs (`rp-cap-`, `rp-res-`) and hooks (`agentbarn-hook-`) never match.
_AGENT_POD = "agent-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_REQUEST_FIELDS = {"memory": "memory_request_bytes", "cpu": "cpu_request_cores"}


def agent_requests_query(agent_ids: Sequence[UUID] | None = None) -> str:
    """What each live Agent's pod is charged in requests, one row per (Agent, resource).

    The healthz script cannot say this: a request is set on the pod, not read from its
    cgroup. It comes from kube-state-metrics, with each pod's init container counted as in
    `namespace_commitments_query`, and is matched to its Agent by the pod's name. The highest
    wins when a rollout leaves two pods of one Agent, so an Agent is never counted twice.

    `agent_ids` names the Agents to ask about; None asks about every Agent, for the Platform
    view. kube-state-metrics series carry no `org_id`, so on an Organization route these ids
    are the boundary: they come from the database, already narrowed to what the caller may
    read, never from a request string. It must not be empty.
    """
    if agent_ids is None:
        pod = f"{_AGENT_POD}-.+"
    else:
        if not agent_ids:
            raise ValueError("agent_requests_query needs at least one agent id, or None for all")
        ids = [str(agent_id) for agent_id in dict.fromkeys(agent_ids)]
        pod = f"{_APP_PREFIX}{ids[0]}-.+" if len(ids) == 1 else f"{_APP_PREFIX}({'|'.join(ids)})-.+"
    live = f'(kube_pod_status_phase{{{_KSM}, phase=~"Pending|Running"}} == 1)'
    pods = _effective_pod("requests", f', pod=~"{pod}"')
    return (
        f"max by (app, resource) (label_replace({pods} * on (namespace, pod) group_left () {live},"
        f' "app", "$1", "pod", "({_AGENT_POD})-.+"))'
    )


def _agent_id_from_app(labels: Mapping[str, str]) -> UUID | None:
    """The Agent a result row belongs to, read from its `app="agent-<uuid>"` label."""
    app = labels.get("app", "")
    if not app.startswith(_APP_PREFIX):
        return None
    try:
        return UUID(app.removeprefix(_APP_PREFIX))
    except ValueError:
        return None


def agent_id_from_labels(labels: Mapping[str, str], permitted: set[UUID]) -> UUID | None:
    """The Agent a result row belongs to, or None if it is not one we asked about."""
    agent_id = _agent_id_from_app(labels)
    return agent_id if agent_id in permitted else None


def group_instant(samples: Iterable[PrometheusSample], permitted: set[UUID]) -> dict[UUID, dict[str, float]]:
    """Instant results as {agent id: {field: value}}."""
    grouped: dict[UUID, dict[str, float]] = {}
    for sample in samples:
        agent_id = agent_id_from_labels(sample.labels, permitted)
        field = sample.labels.get(_FIELD_LABEL)
        if agent_id is not None and field:
            grouped.setdefault(agent_id, {})[field] = sample.value
    return grouped


def group_instant_all(samples: Iterable[PrometheusSample]) -> dict[UUID, dict[str, float]]:
    """Instant results as {agent id: {field: value}}, for every Agent that reported.

    For the Platform view, which asks about every Agent and so keeps rows for Agents the
    database no longer knows. The caller decides what those are.
    """
    grouped: dict[UUID, dict[str, float]] = {}
    for sample in samples:
        agent_id = _agent_id_from_app(sample.labels)
        field = sample.labels.get(_FIELD_LABEL)
        if agent_id is not None and field:
            grouped.setdefault(agent_id, {})[field] = sample.value
    return grouped


def group_namespace_commitments(samples: Iterable[PrometheusSample]) -> dict[str, dict[str, float]]:
    """The namespace's commitments as {"limits": {"memory": bytes, "cpu": cores}, "requests": {...}}.

    A kind or resource the source did not answer for is absent, not zero: no figure is not
    the same as nothing committed.
    """
    grouped: dict[str, dict[str, float]] = {}
    for sample in samples:
        kind = sample.labels.get(_KIND_LABEL)
        resource = sample.labels.get("resource")
        if kind in COMMITMENT_KINDS and resource in ("memory", "cpu"):
            grouped.setdefault(kind, {})[resource] = sample.value
    return grouped


def group_agent_requests(
    samples: Iterable[PrometheusSample], permitted: set[UUID] | None = None
) -> dict[UUID, dict[str, float]]:
    """Request results as {agent id: {"memory_request_bytes": bytes, "cpu_request_cores": cores}}.

    With `permitted`, a row for any other Agent is dropped, as `group_instant` drops one.
    """
    grouped: dict[UUID, dict[str, float]] = {}
    for sample in samples:
        agent_id = _agent_id_from_app(sample.labels)
        if permitted is not None and agent_id not in permitted:
            continue
        field = _REQUEST_FIELDS.get(sample.labels.get("resource", ""))
        if agent_id is not None and field:
            grouped.setdefault(agent_id, {})[field] = sample.value
    return grouped


def group_totals(series: Iterable[PrometheusSeries]) -> dict[str, dict[int, float]]:
    """Range results of `platform_range_query` as {field: {epoch second: value}}."""
    grouped: dict[str, dict[int, float]] = {}
    for item in series:
        field = item.labels.get(_FIELD_LABEL)
        if not field:
            continue
        points = grouped.setdefault(field, {})
        for timestamp, value in item.points:
            points[int(timestamp.timestamp())] = value
    return grouped


def group_range(series: Iterable[PrometheusSeries], permitted: set[UUID]) -> dict[UUID, dict[str, dict[int, float]]]:
    """Range results as {agent id: {field: {epoch second: value}}}."""
    grouped: dict[UUID, dict[str, dict[int, float]]] = {}
    for item in series:
        agent_id = agent_id_from_labels(item.labels, permitted)
        field = item.labels.get(_FIELD_LABEL)
        if agent_id is None or not field:
            continue
        points = grouped.setdefault(agent_id, {}).setdefault(field, {})
        for timestamp, value in item.points:
            points[int(timestamp.timestamp())] = value
    return grouped

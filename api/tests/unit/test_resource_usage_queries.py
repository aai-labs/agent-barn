from datetime import UTC, datetime, timedelta
from itertools import pairwise
from uuid import UUID, uuid4

import pytest

from api.domains.resource_usage.models import ResourceUsageRange, ResourceUsageState, resolve_usage_window
from api.domains.resource_usage.promql import (
    agent_id_from_labels,
    group_agent_requests,
    group_instant,
    group_instant_all,
    group_namespace_commitments,
    group_range,
    group_totals,
    instant_query,
    namespace_commitments_query,
    platform_agent_requests_query,
    platform_range_query,
    platform_selector,
    range_query,
    selector,
)
from api.domains.resource_usage.service import build_snapshot, usage_state
from api.infrastructure.prometheus.client import PrometheusSample, PrometheusSeries

_ORG = UUID("00000000-0000-7000-8000-0000000000aa")
_A = UUID("00000000-0000-7000-8000-000000000001")
_B = UUID("00000000-0000-7000-8000-000000000002")
_SEL = selector(_ORG, [_A])

# --- selectors -------------------------------------------------------------


def test_a_single_agent_is_matched_exactly():
    assert selector(_ORG, [_A]) == f'{{job="agent", org_id="{_ORG}", app="agent-{_A}"}}'


def test_several_agents_are_matched_with_one_alternation():
    # PromQL anchors regex matchers, so this matches these two apps and nothing longer.
    assert selector(_ORG, [_A, _B]) == f'{{job="agent", org_id="{_ORG}", app=~"agent-({_A}|{_B})"}}'


def test_duplicate_ids_are_collapsed():
    assert selector(_ORG, [_A, _A]) == selector(_ORG, [_A])


def test_selecting_no_agents_is_refused():
    with pytest.raises(ValueError):
        selector(_ORG, [])


def test_the_platform_selector_takes_every_agent_and_names_none():
    assert platform_selector() == '{job="agent"}'


# --- queries ---------------------------------------------------------------


def test_the_instant_query_reads_every_field_in_one_request():
    query = instant_query(_SEL, 86400, 86400)
    fields = [
        "up",
        "cgroup_metrics_available",
        "memory_working_set_bytes",
        "cpu_cores",
        "memory_limit_bytes",
        "cpu_limit_cores",
        "cpu_throttled_ratio",
    ]

    for field in fields:
        assert f'"usage_field", "{field}", "", ""' in query
    assert query.count(" or ") == len(fields) - 1


def test_gauges_take_the_max_and_counters_are_summed_as_rates():
    query = instant_query(_SEL, 300, 3600)

    assert f"max by (app) (up{_SEL})" in query
    assert f"max by (app) (agent_cgroup_metrics_available{_SEL})" in query
    assert f"max by (app) (agent_memory_working_set_bytes{_SEL})" in query
    assert f"sum by (app) (rate(agent_cpu_usage_seconds_total{_SEL}[5m]))" in query


def test_limits_and_throttling_use_their_own_windows():
    query = instant_query(_SEL, 300, 3600)

    assert f"last_over_time(agent_memory_limit_bytes{_SEL}[300s])" in query
    assert f"last_over_time(agent_cpu_limit_cores{_SEL}[300s])" in query
    assert f"increase(agent_cpu_throttled_periods_total{_SEL}[3600s])" in query
    assert f"increase(agent_cpu_periods_total{_SEL}[3600s])" in query
    # An agent with no scheduling periods yet must read as zero, not divide by zero.
    assert "clamp_min(" in query


def test_the_range_query_takes_the_peak_memory_and_the_rate_of_cpu():
    query = range_query(_SEL, 300)

    assert f"max_over_time(agent_memory_working_set_bytes{_SEL}[300s])" in query
    assert f"rate(agent_cpu_usage_seconds_total{_SEL}[300s])" in query
    assert f"rate(agent_cpu_throttled_periods_total{_SEL}[300s])" in query
    assert f"rate(agent_cpu_periods_total{_SEL}[300s])" in query
    assert query.count(" or ") == 2


def test_a_short_step_still_uses_a_rate_window_long_enough_for_scrapes():
    query = range_query(_SEL, 60)

    assert f"max_over_time(agent_memory_working_set_bytes{_SEL}[60s])" in query
    # Scrapes are 30s apart, and rate() needs several of them inside its window.
    assert f"rate(agent_cpu_usage_seconds_total{_SEL}[120s])" in query


def test_the_platform_range_query_adds_up_every_agent_peak_and_cpu():
    sel = platform_selector()
    query = platform_range_query(sel, 300)

    assert f"sum(max by (app) (max_over_time(agent_memory_working_set_bytes{sel}[300s])))" in query
    assert f"sum(rate(agent_cpu_usage_seconds_total{sel}[300s]))" in query
    # A ratio added up across agents means nothing, so there is no throttling series.
    assert "throttled" not in query
    assert query.count(" or ") == 1


def test_the_platform_range_query_keeps_a_rate_window_long_enough_for_scrapes():
    assert "[120s]" in platform_range_query(platform_selector(), 60)


def test_the_namespace_query_charges_a_pod_what_a_quota_charges_it():
    query = namespace_commitments_query()

    for kind in ("limits", "requests"):
        containers = f'sum by (namespace, pod, resource) (kube_pod_container_resource_{kind}{{job="kube-state-metrics", resource=~"memory|cpu"}})'
        init = f'max by (namespace, pod, resource) (kube_pod_init_container_resource_{kind}{{job="kube-state-metrics", resource=~"memory|cpu"}})'
        # The containers added up, and the biggest init container, joined by `or` on labels
        # that differ (`part`), then the larger of the two for each pod.
        assert f'label_replace({containers}, "part", "containers", "", "")' in query
        assert f'label_replace({init}, "part", "init", "", "")' in query
        assert f'"kind", "{kind}"' in query
    assert query.count("max by (namespace, pod, resource) (label_replace(") == 2
    # Only pods that are Pending or Running count, as with the quota.
    assert query.count('kube_pod_status_phase{job="kube-state-metrics", phase=~"Pending|Running"} == 1') == 2
    assert query.count("on (namespace, pod) group_left ()") == 2
    # Pinned to its own job, as the Agent queries are pinned to theirs.
    assert query.count('job="kube-state-metrics"') == 2 * (2 + 1)


def test_the_agent_requests_query_reads_only_agent_pods_by_name_and_names_the_agent_in_app():
    query = platform_agent_requests_query()
    agent_pod = "agent-[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

    # Both halves of the pod rule (containers and init container) are limited to agent pods,
    # so a restore job or a hook never reaches the label rewrite.
    assert (
        f'kube_pod_container_resource_requests{{job="kube-state-metrics", resource=~"memory|cpu", pod=~"{agent_pod}-.+"}}'
        in query
    )
    assert (
        f'kube_pod_init_container_resource_requests{{job="kube-state-metrics", resource=~"memory|cpu", pod=~"{agent_pod}-.+"}}'
        in query
    )
    assert "kube_pod_container_resource_limits" not in query
    # The Deployment's name becomes `app`, as the scrape's own label is, so one parser maps both.
    assert f'"app", "$1", "pod", "({agent_pod})-.+"' in query
    # An Agent with a pod being replaced is counted once, by its highest, never added twice.
    assert query.startswith("max by (app, resource) (label_replace(")
    assert 'kube_pod_status_phase{job="kube-state-metrics", phase=~"Pending|Running"} == 1' in query
    assert "on (namespace, pod) group_left ()" in query


def test_the_namespace_query_is_not_limited_to_agent_pods():
    assert "agent-[0-9a-f]" not in namespace_commitments_query()


# --- mapping results back to agents ----------------------------------------


def test_only_agents_that_were_asked_about_are_mapped():
    assert agent_id_from_labels({"app": f"agent-{_A}"}, {_A}) == _A
    assert agent_id_from_labels({"app": f"agent-{_B}"}, {_A}) is None
    assert agent_id_from_labels({"app": str(_A)}, {_A}) is None
    assert agent_id_from_labels({"app": "agent-not-a-uuid"}, {_A}) is None
    assert agent_id_from_labels({}, {_A}) is None


def test_slug_labels_are_never_used_to_find_an_agent():
    assert agent_id_from_labels({"agent_name": str(_A), "org_name": "acme"}, {_A}) is None


def test_instant_rows_are_grouped_by_agent_and_field():
    samples = [
        PrometheusSample({"app": f"agent-{_A}", "usage_field": "cpu_cores"}, 0.1),
        PrometheusSample({"app": f"agent-{_A}", "usage_field": "up"}, 1.0),
        PrometheusSample({"app": f"agent-{_B}", "usage_field": "up"}, 1.0),
        PrometheusSample({"app": f"agent-{uuid4()}", "usage_field": "up"}, 1.0),
        PrometheusSample({"app": f"agent-{_A}"}, 5.0),
    ]

    assert group_instant(samples, {_A, _B}) == {_A: {"cpu_cores": 0.1, "up": 1.0}, _B: {"up": 1.0}}


def test_range_points_are_keyed_by_epoch_second_and_strangers_are_dropped():
    start = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    series = [
        PrometheusSeries(
            {"app": f"agent-{_A}", "usage_field": "cpu_cores"},
            ((start, 0.5), (start + timedelta(minutes=5), 0.6)),
        ),
        PrometheusSeries({"app": f"agent-{uuid4()}", "usage_field": "cpu_cores"}, ((start, 9.0),)),
    ]

    second = int(start.timestamp())
    assert group_range(series, {_A}) == {_A: {"cpu_cores": {second: 0.5, second + 300: 0.6}}}


def test_the_platform_view_keeps_every_agent_that_reported():
    stranger = uuid4()
    samples = [
        PrometheusSample({"app": f"agent-{_A}", "usage_field": "cpu_cores"}, 0.1),
        PrometheusSample({"app": f"agent-{stranger}", "usage_field": "up"}, 1.0),
        PrometheusSample({"app": "litellm", "usage_field": "up"}, 1.0),
        PrometheusSample({"app": "agent-not-a-uuid", "usage_field": "up"}, 1.0),
        PrometheusSample({"agent_name": str(_B), "usage_field": "up"}, 1.0),
        PrometheusSample({"app": f"agent-{_A}"}, 5.0),
    ]

    assert group_instant_all(samples) == {_A: {"cpu_cores": 0.1}, stranger: {"up": 1.0}}


def test_namespace_commitments_are_read_by_kind_and_resource():
    samples = [
        PrometheusSample({"kind": "limits", "resource": "memory"}, 4_294_967_296.0),
        PrometheusSample({"kind": "limits", "resource": "cpu"}, 1.5),
        PrometheusSample({"kind": "requests", "resource": "memory"}, 1_073_741_824.0),
        PrometheusSample({"kind": "requests", "resource": "cpu"}, 0.25),
        PrometheusSample({"kind": "limits", "resource": "ephemeral-storage"}, 9.0),
        PrometheusSample({"kind": "other", "resource": "cpu"}, 3.0),
        PrometheusSample({"resource": "cpu"}, 7.0),
        PrometheusSample({}, 7.0),
    ]

    assert group_namespace_commitments(samples) == {
        "limits": {"memory": 4_294_967_296.0, "cpu": 1.5},
        "requests": {"memory": 1_073_741_824.0, "cpu": 0.25},
    }


def test_a_kind_or_resource_the_source_did_not_answer_for_is_absent_not_zero():
    assert group_namespace_commitments([]) == {}
    assert group_namespace_commitments([PrometheusSample({"kind": "requests", "resource": "cpu"}, 2.0)]) == {
        "requests": {"cpu": 2.0}
    }


def test_combined_points_are_keyed_by_field_and_epoch_second():
    start = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
    series = [
        PrometheusSeries({"usage_field": "cpu_cores"}, ((start, 0.5), (start + timedelta(minutes=5), 0.6))),
        PrometheusSeries({"usage_field": "memory_working_set_bytes"}, ((start, 1024.0),)),
        PrometheusSeries({}, ((start, 9.0),)),
    ]

    second = int(start.timestamp())
    assert group_totals(series) == {
        "cpu_cores": {second: 0.5, second + 300: 0.6},
        "memory_working_set_bytes": {second: 1024.0},
    }


# --- windows ---------------------------------------------------------------


def test_the_window_end_is_aligned_to_the_step():
    window = resolve_usage_window(ResourceUsageRange.ONE_DAY, datetime(2026, 9, 29, 11, 7, 33, tzinfo=UTC))

    assert window.end == datetime(2026, 9, 29, 11, 5, tzinfo=UTC)
    assert window.start == datetime(2026, 9, 28, 11, 5, tzinfo=UTC)
    assert window.step_seconds == 300


def test_polls_within_one_step_ask_for_the_same_window():
    first = resolve_usage_window(ResourceUsageRange.ONE_DAY, datetime(2026, 9, 29, 11, 5, 1, tzinfo=UTC))
    second = resolve_usage_window(ResourceUsageRange.ONE_DAY, datetime(2026, 9, 29, 11, 9, 59, tzinfo=UTC))

    assert first == second


@pytest.mark.parametrize(
    ("usage_range", "step_seconds", "points"),
    [
        (ResourceUsageRange.ONE_HOUR, 60, 61),
        (ResourceUsageRange.SIX_HOURS, 120, 181),
        (ResourceUsageRange.ONE_DAY, 300, 289),
        (ResourceUsageRange.SEVEN_DAYS, 1800, 337),
        (ResourceUsageRange.FOURTEEN_DAYS, 3600, 337),
    ],
)
def test_each_range_draws_a_bounded_evenly_spaced_timeline(usage_range, step_seconds, points):
    window = resolve_usage_window(usage_range, datetime(2026, 9, 29, 11, 7, 33, tzinfo=UTC))
    timeline = window.timeline()

    assert window.step_seconds == step_seconds
    assert len(timeline) == points
    assert timeline[0] == window.start
    assert timeline[-1] == window.end
    assert all((later - earlier).total_seconds() == step_seconds for earlier, later in pairwise(timeline))


def test_no_range_reaches_further_back_than_prometheus_keeps():
    # Retention is 15 days (helm/monitoring/values.yaml), and the newest data is a step old.
    assert max(usage_range.seconds for usage_range in ResourceUsageRange) < 15 * 24 * 3600


# --- what an agent is doing ------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "has_series", "expected"),
    [
        ({"memory_working_set_bytes": 1.0}, False, ResourceUsageState.REPORTING),
        ({"cpu_cores": 0.1}, False, ResourceUsageState.REPORTING),
        ({}, True, ResourceUsageState.REPORTING),
        (
            {"up": 1.0, "cgroup_metrics_available": 1.0, "memory_working_set_bytes": 5.0},
            False,
            ResourceUsageState.REPORTING,
        ),
        ({"up": 1.0, "cgroup_metrics_available": 0.0}, False, ResourceUsageState.UNSUPPORTED),
        ({"up": 1.0}, False, ResourceUsageState.RESTART_REQUIRED),
        ({"up": 0.0}, False, ResourceUsageState.NO_DATA),
        ({"up": 1.0, "cgroup_metrics_available": 1.0}, False, ResourceUsageState.NO_DATA),
        ({}, False, ResourceUsageState.NO_DATA),
    ],
)
def test_usage_state(fields, has_series, expected):
    assert usage_state(fields, has_series) == expected


def test_a_snapshot_keeps_whole_bytes_and_passes_the_rest_through():
    snapshot = build_snapshot(
        {
            "up": 1.0,
            "memory_working_set_bytes": 358_617_088.4,
            "memory_limit_bytes": 1_073_741_824.0,
            "cpu_cores": 0.05,
            "cpu_limit_cores": 0.5,
            "cpu_throttled_ratio": 0.2,
        }
    )

    assert snapshot.state == ResourceUsageState.REPORTING
    assert snapshot.memory_working_set_bytes == 358_617_088
    assert isinstance(snapshot.memory_limit_bytes, int)
    assert snapshot.cpu_cores == 0.05
    assert snapshot.cpu_limit_cores == 0.5
    assert snapshot.cpu_throttled_ratio == 0.2


def test_a_snapshot_of_nothing_is_all_null():
    snapshot = build_snapshot({})

    assert snapshot.state == ResourceUsageState.NO_DATA
    assert snapshot.memory_working_set_bytes is None
    assert snapshot.cpu_cores is None


def test_agent_requests_are_read_by_agent_and_resource():
    other = uuid4()
    samples = [
        PrometheusSample({"app": f"agent-{_A}", "resource": "memory"}, 805_306_368.0),
        PrometheusSample({"app": f"agent-{_A}", "resource": "cpu"}, 0.1),
        PrometheusSample({"app": f"agent-{other}", "resource": "memory"}, 268_435_456.0),
        # Not an Agent, not a resource we show, and a row with no resource at all.
        PrometheusSample({"app": "agentbarn-api", "resource": "cpu"}, 9.0),
        PrometheusSample({"app": f"agent-{_B}", "resource": "ephemeral-storage"}, 9.0),
        PrometheusSample({"app": f"agent-{_B}"}, 9.0),
        PrometheusSample({"resource": "cpu"}, 9.0),
    ]

    assert group_agent_requests(samples) == {
        _A: {"memory_request_bytes": 805_306_368.0, "cpu_request_cores": 0.1},
        other: {"memory_request_bytes": 268_435_456.0},
    }
    assert group_agent_requests([]) == {}

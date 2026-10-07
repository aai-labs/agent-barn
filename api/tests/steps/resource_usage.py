from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID

from injector import Module, provider, singleton

from api.infrastructure.prometheus.client import (
    PrometheusClient,
    PrometheusError,
    PrometheusSample,
    PrometheusSeries,
)


class MockPrometheusModule(Module):
    """A configured Prometheus that reports nothing until a step says otherwise."""

    @provider
    @singleton
    def provide_prometheus(self) -> PrometheusClient:
        mock: Any = MagicMock(spec=PrometheusClient)
        mock.is_configured = True
        mock.query.return_value = []
        mock.query_range.return_value = []
        return mock


def _client(context) -> Any:
    return context.injector.get(PrometheusClient)


def prometheus_reports(fields: Mapping[str, float], *, agent_id: UUID | None = None):
    """Answer instant queries with these {field: value} rows for one Agent.

    Defaults to the scenario's current Agent. The mock answers whatever it is asked, so
    a test can also prove the service drops rows for Agents it did not ask about.
    """

    def step(context):
        target = agent_id or context.agent.id
        _client(context).query.return_value = [
            PrometheusSample(labels={"app": f"agent-{target}", "usage_field": field}, value=value)
            for field, value in fields.items()
        ]

    return step


def prometheus_reports_for_agents(rows: Mapping[UUID, Mapping[str, float]]):
    """Answer instant queries with rows for several Agents at once."""

    def step(context):
        _client(context).query.return_value = [
            PrometheusSample(labels={"app": f"agent-{agent_id}", "usage_field": field}, value=value)
            for agent_id, fields in rows.items()
            for field, value in fields.items()
        ]

    return step


def prometheus_reports_history(by_index: Mapping[str, Mapping[int, float]], *, agent_id: UUID | None = None):
    """Answer range queries with points at chosen positions along the requested timeline.

    Keys are positions counted in steps from the start of the window, so a test does not
    need to know the aligned timestamps the service chose.
    """

    def step(context):
        target = agent_id or context.agent.id

        def answer(promql: str, start: datetime, end: datetime, step_seconds: int):
            return [
                PrometheusSeries(
                    labels={"app": f"agent-{target}", "usage_field": field},
                    points=tuple(
                        (start + timedelta(seconds=step_seconds * index), value) for index, value in points.items()
                    ),
                )
                for field, points in by_index.items()
            ]

        _client(context).query_range.side_effect = answer

    return step


def prometheus_is_down():
    def step(context):
        client = _client(context)
        client.query.side_effect = PrometheusError("Prometheus request failed: ConnectError")
        client.query_range.side_effect = PrometheusError("Prometheus request failed: ConnectError")

    return step


def prometheus_is_not_configured():
    def step(context):
        _client(context).is_configured = False

    return step


def _answer_when(client: Any, matches, rows: list[PrometheusSample] | Exception) -> None:
    """Answer the instant queries `matches` picks with `rows` (or fail them), and every other as before.

    The mock answers every instant query with one list, so a step that has its own rows
    wraps whatever answer is already set. Run it after the step that sets the Agent readings.
    """
    previous = client.query.side_effect
    others = client.query.return_value

    def answer(promql: str, at: datetime):
        if matches(promql):
            if isinstance(rows, Exception):
                raise rows
            return rows
        return previous(promql, at) if previous else others

    client.query.side_effect = answer


def prometheus_reports_namespace_commitments(
    *,
    limits_memory: float | None = None,
    limits_cpu: float | None = None,
    requests_memory: float | None = None,
    requests_cpu: float | None = None,
):
    """Answer the namespace-commitments query with these totals, and leave the rest as they are."""

    def step(context):
        rows = [
            PrometheusSample(labels={"kind": kind, "resource": resource}, value=value)
            for kind, resource, value in (
                ("limits", "memory", limits_memory),
                ("limits", "cpu", limits_cpu),
                ("requests", "memory", requests_memory),
                ("requests", "cpu", requests_cpu),
            )
            if value is not None
        ]
        _answer_when(_client(context), lambda promql: '"kind"' in promql, rows)

    return step


def prometheus_reports_agent_requests(requests: Callable[[Any], Mapping[UUID, tuple[float, float]]]):
    """Answer the per-Agent requests query with (memory bytes, cpu cores) for each Agent.

    `requests` is given the scenario, so a test can name Agents it has just created.
    """

    def step(context):
        rows = [
            PrometheusSample(labels={"app": f"agent-{agent_id}", "resource": resource}, value=value)
            for agent_id, (memory, cpu) in requests(context).items()
            for resource, value in (("memory", memory), ("cpu", cpu))
        ]
        _answer_when(_client(context), _is_agent_requests_query, rows)

    return step


def prometheus_fails_agent_requests():
    """Fail only the per-Agent requests query, so the rest of the page can be seen standing."""

    def step(context):
        _answer_when(_client(context), _is_agent_requests_query, PrometheusError("requests are unavailable"))

    return step


def _is_agent_requests_query(promql: str) -> bool:
    # The only query that rewrites a pod's name into `app`.
    return '"app", "$1", "pod"' in promql

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from injector import inject, singleton

from api.domains.resource_usage.models import UsageWindow
from api.domains.resource_usage.promql import (
    group_instant,
    group_instant_all,
    group_namespace_limits,
    group_range,
    group_totals,
    instant_query,
    namespace_limits_query,
    platform_range_query,
    platform_selector,
    range_query,
    selector,
)
from api.infrastructure.prometheus.client import PrometheusClient


@inject
@singleton
@dataclass
class ResourceUsageRepository:
    """Reads Agent CPU and memory from Prometheus. Nothing is stored here.

    Every method can raise `PrometheusError`; callers turn that into an "unavailable"
    answer rather than a failed request.
    """

    prometheus: PrometheusClient

    @property
    def is_configured(self) -> bool:
        return self.prometheus.is_configured

    def current_fields(
        self,
        organization_id: UUID,
        agent_ids: list[UUID],
        *,
        at: datetime,
        window_seconds: int,
        throttle_window_seconds: int,
    ) -> dict[UUID, dict[str, float]]:
        """{agent id: {field: value}} for the Agents that have any series. One request."""
        if not agent_ids:
            return {}
        query = instant_query(selector(organization_id, agent_ids), window_seconds, throttle_window_seconds)
        return group_instant(self.prometheus.query(query, at), set(agent_ids))

    def series_fields(self, organization_id: UUID, agent_id: UUID, window: UsageWindow) -> dict[str, dict[int, float]]:
        """{field: {epoch second: value}} for one Agent across the window. One request."""
        query = range_query(selector(organization_id, [agent_id]), window.step_seconds)
        series = self.prometheus.query_range(query, window.start, window.end, window.step_seconds)
        return group_range(series, {agent_id}).get(agent_id, {})

    def all_current_fields(
        self, *, at: datetime, window_seconds: int, throttle_window_seconds: int
    ) -> dict[UUID, dict[str, float]]:
        """{agent id: {field: value}} for every Agent on the platform that has any series.

        Platform view only. Rows are keyed by the `app` label alone; the caller maps them
        to Agents and Organizations through the database. One request.
        """
        query = instant_query(platform_selector(), window_seconds, throttle_window_seconds)
        return group_instant_all(self.prometheus.query(query, at))

    def combined_series(
        self, window: UsageWindow, organization: tuple[UUID, list[UUID]] | None = None
    ) -> dict[str, dict[int, float]]:
        """{field: {epoch second: value}} of Agents added together. One request.

        Every Agent on the platform, or with `organization` as (its id, its Agent ids),
        just those Agents, so the chart counts the same ones as the totals beside it.
        """
        sel = selector(*organization) if organization else platform_selector()
        query = platform_range_query(sel, window.step_seconds)
        return group_totals(self.prometheus.query_range(query, window.start, window.end, window.step_seconds))

    def committed_limits(self, *, at: datetime) -> dict[str, float]:
        """{"memory": bytes, "cpu": cores} the namespace's pods commit in limits. One request.

        Empty when kube-state-metrics has no pods to report.
        """
        return group_namespace_limits(self.prometheus.query(namespace_limits_query(), at))

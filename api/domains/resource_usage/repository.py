from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from injector import inject, singleton

from api.domains.resource_usage.models import UsageWindow
from api.domains.resource_usage.promql import group_instant, group_range, instant_query, range_query, selector
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

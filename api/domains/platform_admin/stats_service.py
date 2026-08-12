"""Cross-Organization stats for the Platform View (AF-256).

This composes other domains' services — never their repositories — so the
Organization-scoped reads next to them keep their own authorization paths. The
Platform Privilege check itself lives on the route (`require_platform_admin`),
matching every other platform surface.
"""

from dataclasses import dataclass
from datetime import UTC, datetime

from injector import inject, singleton

from api.domains.agents.service import AgentService
from api.domains.conversations.service import ConversationService
from api.domains.platform_admin.models import (
    PlatformAgentSeriesPoint,
    PlatformAgentStatsRead,
    PlatformMessageSeriesPoint,
    PlatformMessageStatsRead,
    PlatformStatsFilter,
    StatsWindow,
)
from api.domains.tool_calls.service import ToolCallService


@inject
@singleton
@dataclass
class PlatformStatsService:
    conversation_service: ConversationService
    agent_service: AgentService
    tool_call_service: ToolCallService

    def get_message_stats(
        self, window: StatsWindow, stats_filter: PlatformStatsFilter | None = None
    ) -> PlatformMessageStatsRead:
        stats_filter = stats_filter or PlatformStatsFilter()

        rows = self.conversation_service.platform_daily_message_counts(
            window.start,
            window.end,
            unit=window.granularity.value,
            **stats_filter.model_dump(),
        )
        series = [
            PlatformMessageSeriesPoint(bucket=bucket, inbound=inbound, outbound=outbound)
            for bucket, inbound, outbound in rows
        ]
        inbound_total = sum(point.inbound for point in series)
        outbound_total = sum(point.outbound for point in series)

        return PlatformMessageStatsRead(
            observed_at=datetime.now(UTC),
            period=window.period,
            from_date=window.start,
            to_date=window.end,
            granularity=window.granularity,
            inbound=inbound_total,
            outbound=outbound_total,
            total=inbound_total + outbound_total,
            series=series,
        )

    def get_agent_stats(
        self, window: StatsWindow, stats_filter: PlatformStatsFilter | None = None
    ) -> PlatformAgentStatsRead:
        stats_filter = stats_filter or PlatformStatsFilter()
        filters = stats_filter.model_dump()

        total, running, stopped, errored = self.agent_service.count_agents_for_stats(**filters)
        unit = window.granularity.value
        rows = self.agent_service.agent_inventory(window.start, window.end, unit=unit, **filters)

        # Activity is the union of the two telemetry streams, deduplicated per
        # bucket: an Agent that both messaged and ran a tool is one active Agent.
        # Tool calls matter disproportionately here — the runtime plugins gate
        # outbound messages on a user-triggered turn, so scheduled and proactive
        # work is only visible through tools.
        by_bucket_messages = self.conversation_service.platform_daily_active_agent_ids(
            window.start, window.end, unit=unit, **filters
        )
        by_bucket_tools = self.tool_call_service.platform_daily_active_agent_ids(
            window.start, window.end, unit=unit, **filters
        )

        active_by_bucket = {
            bucket: by_bucket_messages.get(bucket, set()) | by_bucket_tools.get(bucket, set())
            for bucket in by_bucket_messages.keys() | by_bucket_tools.keys()
        }
        active_in_period = set().union(*active_by_bucket.values()) if active_by_bucket else set()

        series = [
            PlatformAgentSeriesPoint(
                bucket=bucket,
                existing=existing,
                created=created,
                active=len(active_by_bucket.get(bucket, set())),
            )
            for bucket, existing, created in rows
        ]

        return PlatformAgentStatsRead(
            observed_at=datetime.now(UTC),
            period=window.period,
            from_date=window.start,
            to_date=window.end,
            granularity=window.granularity,
            total=total,
            running=running,
            stopped=stopped,
            errored=errored,
            active=len(active_in_period),
            series=series,
        )

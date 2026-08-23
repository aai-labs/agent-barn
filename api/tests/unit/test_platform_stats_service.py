from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid7

from fastapi import HTTPException
from hamcrest import assert_that, calling, close_to, equal_to, has_entries, has_length, raises

from api.domains.agents.models import AgentPlatform
from api.domains.platform_admin.models import (
    PlatformStatsFilter,
    StatsGranularity,
    StatsPeriod,
    resolve_stats_window,
)
from api.domains.platform_admin.stats_service import PlatformStatsService


def _B(day: int) -> datetime:
    """An August 2026 UTC day bucket — series keys are instants now, not dates."""
    return datetime(2026, 8, day, tzinfo=UTC)


def _service(
    message_rows=None,
    agent_rows=None,
    total=0,
    running=0,
    stopped=0,
    errored=0,
    active_by_messages=None,
    active_by_tools=None,
) -> tuple[PlatformStatsService, MagicMock, MagicMock, MagicMock]:
    conversation_service = MagicMock()
    conversation_service.platform_daily_message_counts.return_value = message_rows or []
    conversation_service.platform_daily_active_agent_ids.return_value = active_by_messages or {}
    agent_service = MagicMock()
    agent_service.count_agents_for_stats.return_value = (total, running, stopped, errored)
    agent_service.agent_inventory.return_value = agent_rows or []
    tool_call_service = MagicMock()
    tool_call_service.platform_daily_active_agent_ids.return_value = active_by_tools or {}
    return (
        PlatformStatsService(conversation_service, agent_service, tool_call_service),
        conversation_service,
        agent_service,
        tool_call_service,
    )


def test_each_period_maps_to_its_own_window():
    for period, days in (
        (StatsPeriod.SEVEN_DAYS, 7),
        (StatsPeriod.THIRTY_DAYS, 30),
        (StatsPeriod.NINETY_DAYS, 90),
    ):
        service, conversation_service, _, _ = _service()

        result = service.get_message_stats(resolve_stats_window(period))

        window_start = conversation_service.platform_daily_message_counts.call_args.args[0]
        elapsed_days = (datetime.now(UTC) - window_start).total_seconds() / 86400
        assert_that(elapsed_days, close_to(days, 0.01))
        assert_that(result.period, equal_to(period))


def test_a_custom_range_overrides_the_preset_and_reports_no_period():
    start = datetime(2026, 3, 1, tzinfo=UTC)
    end = datetime(2026, 3, 15, tzinfo=UTC)
    window = resolve_stats_window(StatsPeriod.NINETY_DAYS, from_date=start, to_date=end)
    service, conversation_service, _, _ = _service()

    result = service.get_message_stats(window)

    args = conversation_service.platform_daily_message_counts.call_args.args
    assert_that(args[0], equal_to(start))
    assert_that(args[1], equal_to(end))
    # A custom range is not one of the presets, so the response says so rather
    # than echoing back a period the caller never got.
    assert_that(result.period, equal_to(None))
    assert_that(result.from_date, equal_to(start))
    assert_that(result.to_date, equal_to(end))


def test_a_lone_from_date_runs_to_now():
    start = datetime(2026, 3, 1, tzinfo=UTC)
    window = resolve_stats_window(StatsPeriod.SEVEN_DAYS, from_date=start)

    assert_that(window.start, equal_to(start))
    assert_that((datetime.now(UTC) - window.end).total_seconds(), close_to(0, 5))
    assert_that(window.period, equal_to(None))


def test_a_lone_to_date_backs_off_by_the_period_length():
    end = datetime(2026, 3, 15, tzinfo=UTC)
    window = resolve_stats_window(StatsPeriod.SEVEN_DAYS, to_date=end)

    assert_that(window.end, equal_to(end))
    assert_that((end - window.start).days, equal_to(7))


def test_a_naive_bound_is_read_as_utc():
    # Deliberately naive — a browser sending `2026-03-01` produces exactly this,
    # and every stored timestamp is timestamptz bucketed by UTC day.
    naive = datetime.fromisoformat("2026-03-01T00:00:00")
    window = resolve_stats_window(StatsPeriod.SEVEN_DAYS, from_date=naive)

    assert_that(window.start, equal_to(datetime(2026, 3, 1, tzinfo=UTC)))


def test_an_inverted_range_is_rejected():
    assert_that(
        calling(resolve_stats_window).with_args(
            StatsPeriod.SEVEN_DAYS,
            from_date=datetime(2026, 3, 15, tzinfo=UTC),
            to_date=datetime(2026, 3, 1, tzinfo=UTC),
        ),
        raises(HTTPException),
    )


def test_totals_are_summed_from_the_daily_series():
    service, _, _, _ = _service(message_rows=[(_B(1), 3, 2), (_B(2), 0, 5), (_B(3), 7, 0)])

    result = service.get_message_stats(resolve_stats_window(StatsPeriod.THIRTY_DAYS))

    assert_that(result.series, has_length(3))
    assert_that(result.inbound, equal_to(10))
    assert_that(result.outbound, equal_to(7))
    assert_that(result.total, equal_to(17))
    assert_that(result.series[1].bucket, equal_to(_B(2)))
    assert_that(result.series[1].outbound, equal_to(5))


def test_an_empty_window_reports_zeroes_rather_than_failing():
    service, _, _, _ = _service(message_rows=[])

    result = service.get_message_stats(resolve_stats_window(StatsPeriod.SEVEN_DAYS))

    assert_that(result.series, has_length(0))
    assert_that(result.total, equal_to(0))


def test_agent_stats_keeps_inventory_and_activity_distinct():
    agent = uuid7()
    service, _, _, _ = _service(
        total=9,
        running=4,
        agent_rows=[(_B(1), 9, 1)],
        active_by_messages={_B(1): {agent}},
    )

    result = service.get_agent_stats(resolve_stats_window(StatsPeriod.THIRTY_DAYS))

    assert_that(result.total, equal_to(9))
    assert_that(result.running, equal_to(4))
    assert_that(result.active, equal_to(1))
    assert_that(result.series[0].existing, equal_to(9))
    assert_that(result.series[0].created, equal_to(1))
    assert_that(result.series[0].active, equal_to(1))


def test_activity_unions_message_and_tool_streams_without_double_counting():
    both = uuid7()
    messaged_only = uuid7()
    tooled_only = uuid7()

    service, _, _, _ = _service(
        agent_rows=[(_B(1), 5, 0)],
        active_by_messages={_B(1): {both, messaged_only}},
        active_by_tools={_B(1): {both, tooled_only}},
    )

    result = service.get_agent_stats(resolve_stats_window(StatsPeriod.THIRTY_DAYS))

    # The Agent doing both is one active Agent, not two.
    assert_that(result.series[0].active, equal_to(3))
    assert_that(result.active, equal_to(3))


def test_an_agent_active_only_via_tools_still_counts():
    """Scheduled work leaves no message trace — the runtime plugins gate
    outbound messages on a user-triggered turn, so tool calls are the only
    evidence proactive work happened at all."""
    cron_agent = uuid7()
    service, _, _, _ = _service(
        agent_rows=[(_B(1), 2, 0)],
        active_by_messages={},
        active_by_tools={_B(1): {cron_agent}},
    )

    result = service.get_agent_stats(resolve_stats_window(StatsPeriod.THIRTY_DAYS))

    assert_that(result.series[0].active, equal_to(1))


def test_period_active_deduplicates_across_days():
    agent = uuid7()
    service, _, _, _ = _service(
        agent_rows=[(_B(1), 3, 0), (_B(2), 3, 0)],
        active_by_messages={_B(1): {agent}, _B(2): {agent}},
    )

    result = service.get_agent_stats(resolve_stats_window(StatsPeriod.THIRTY_DAYS))

    # Active on both days, but one distinct Agent across the period.
    assert_that(result.series[0].active, equal_to(1))
    assert_that(result.series[1].active, equal_to(1))
    assert_that(result.active, equal_to(1))


def test_days_with_no_telemetry_report_zero_active():
    service, _, _, _ = _service(
        agent_rows=[(_B(1), 2, 0), (_B(2), 2, 0)],
    )

    result = service.get_agent_stats(resolve_stats_window(StatsPeriod.SEVEN_DAYS))

    assert_that({point.active for point in result.series}, equal_to({0}))
    assert_that(result.active, equal_to(0))


def test_filters_reach_both_aggregates_unchanged():
    org_id = uuid7()
    creator_id = uuid7()
    stats_filter = PlatformStatsFilter(
        organization_id=org_id,
        created_by_user_id=creator_id,
        platform=AgentPlatform.TELEGRAM,
    )
    service, conversation_service, agent_service, tool_call_service = _service()

    service.get_message_stats(resolve_stats_window(StatsPeriod.THIRTY_DAYS), stats_filter)
    service.get_agent_stats(resolve_stats_window(StatsPeriod.THIRTY_DAYS), stats_filter)

    expected = has_entries(
        organization_id=org_id,
        agent_id=None,
        created_by_user_id=creator_id,
        platform=AgentPlatform.TELEGRAM,
    )
    assert_that(conversation_service.platform_daily_message_counts.call_args.kwargs, expected)
    assert_that(conversation_service.platform_daily_active_agent_ids.call_args.kwargs, expected)
    assert_that(agent_service.count_agents_for_stats.call_args.kwargs, expected)
    assert_that(agent_service.agent_inventory.call_args.kwargs, expected)
    assert_that(tool_call_service.platform_daily_active_agent_ids.call_args.kwargs, expected)


def test_no_filter_still_reaches_the_aggregates_with_empty_dimensions():
    service, conversation_service, _, _ = _service()

    service.get_message_stats(resolve_stats_window(StatsPeriod.SEVEN_DAYS))

    assert_that(
        conversation_service.platform_daily_message_counts.call_args.kwargs,
        has_entries(organization_id=None, agent_id=None, created_by_user_id=None, platform=None),
    )


def test_granularity_follows_the_window_span():
    end = datetime(2026, 3, 20, tzinfo=UTC)

    def span(days: int) -> StatsGranularity:
        return resolve_stats_window(from_date=end - timedelta(days=days), to_date=end).granularity

    # An hour bucketed by hour is one bar, so very short windows go by minute.
    assert_that(
        resolve_stats_window(from_date=end - timedelta(hours=1), to_date=end).granularity,
        equal_to(StatsGranularity.MINUTE),
    )
    assert_that(
        resolve_stats_window(from_date=end - timedelta(hours=2), to_date=end).granularity,
        equal_to(StatsGranularity.MINUTE),
    )
    assert_that(
        resolve_stats_window(from_date=end - timedelta(hours=6), to_date=end).granularity,
        equal_to(StatsGranularity.HOUR),
    )
    assert_that(
        resolve_stats_window(from_date=end - timedelta(hours=12), to_date=end).granularity,
        equal_to(StatsGranularity.HOUR),
    )
    assert_that(span(1), equal_to(StatsGranularity.HOUR))
    assert_that(span(3), equal_to(StatsGranularity.HOUR))
    assert_that(span(4), equal_to(StatsGranularity.DAY))
    assert_that(span(90), equal_to(StatsGranularity.DAY))
    # Two years of day buckets is 730 bars; weekly keeps it readable.
    assert_that(span(365), equal_to(StatsGranularity.WEEK))


def test_granularity_can_be_pinned_against_the_span():
    window = resolve_stats_window(
        from_date=datetime(2026, 1, 1, tzinfo=UTC),
        to_date=datetime(2026, 3, 1, tzinfo=UTC),
        granularity=StatsGranularity.HOUR,
    )

    assert_that(window.granularity, equal_to(StatsGranularity.HOUR))


def test_the_bucket_unit_reaches_every_aggregate():
    service, conversation_service, agent_service, tool_call_service = _service()
    window = resolve_stats_window(
        from_date=datetime(2026, 3, 1, tzinfo=UTC),
        to_date=datetime(2026, 3, 2, tzinfo=UTC),
    )

    service.get_message_stats(window)
    service.get_agent_stats(window)

    assert_that(window.granularity, equal_to(StatsGranularity.HOUR))
    for mock in (
        conversation_service.platform_daily_message_counts,
        conversation_service.platform_daily_active_agent_ids,
        agent_service.agent_inventory,
        tool_call_service.platform_daily_active_agent_ids,
    ):
        assert_that(mock.call_args.kwargs["unit"], equal_to("hour"))


def test_the_status_split_is_carried_through_untouched():
    service, _, _, _ = _service(total=10, running=4, stopped=5, errored=1)

    result = service.get_agent_stats(resolve_stats_window(StatsPeriod.THIRTY_DAYS))

    assert_that(result.running, equal_to(4))
    assert_that(result.stopped, equal_to(5))
    assert_that(result.errored, equal_to(1))
    # AgentStatus has exactly these three values, so they partition the total.
    assert_that(result.running + result.stopped + result.errored, equal_to(result.total))


def test_an_oversized_bucket_count_is_rejected():
    """granularity is caller-supplied and overrides the auto choice, so an
    unbounded span pinned to minutes would ask for tens of millions of buckets."""
    assert_that(
        calling(resolve_stats_window).with_args(
            from_date=datetime(1970, 1, 1, tzinfo=UTC),
            to_date=datetime(2030, 1, 1, tzinfo=UTC),
            granularity=StatsGranularity.MINUTE,
        ),
        raises(HTTPException),
    )


def test_a_large_span_at_a_coarse_granularity_is_fine():
    window = resolve_stats_window(
        from_date=datetime(2020, 1, 1, tzinfo=UTC),
        to_date=datetime(2030, 1, 1, tzinfo=UTC),
        granularity=StatsGranularity.WEEK,
    )
    assert_that(window.granularity, equal_to(StatsGranularity.WEEK))


def test_the_auto_granularity_path_never_trips_the_cap():
    # Auto-selection is bounded by construction; verify the widest auto window.
    window = resolve_stats_window(
        from_date=datetime(2000, 1, 1, tzinfo=UTC),
        to_date=datetime(2030, 1, 1, tzinfo=UTC),
    )
    assert_that(window.granularity, equal_to(StatsGranularity.WEEK))

"""Turning Honcho's CloudEvents telemetry into attributable token usage.

Honcho sends every model call to LiteLLM on one service credential with no
workspace identity, so LiteLLM sees an undifferentiated stream. Its telemetry
does name the workspace and count tokens, and those shares are what divide
LiteLLM's authoritative total for Honcho's key.
"""

from typing import cast
from uuid import UUID

from hamcrest import assert_that, contains_exactly, empty, equal_to

from api.domains.costs.models import HonchoUsageEvent
from api.domains.costs.repository import HonchoUsageRepository
from api.domains.costs.usage_service import HonchoUsageService
from api.infrastructure.litellm.client import LiteLLMClient

WORKSPACE = "af-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


class _FakeRepository:
    def __init__(self) -> None:
        self.recorded: list[HonchoUsageEvent] = []

    def record(self, events: list[HonchoUsageEvent]) -> int:
        self.recorded.extend(events)
        return len(events)


def _service() -> tuple[HonchoUsageService, _FakeRepository]:
    from api.core.config import Config

    repository = _FakeRepository()
    service = HonchoUsageService(
        repository=cast(HonchoUsageRepository, repository),
        litellm=cast("LiteLLMClient", None),
        config=Config(),
    )
    return service, repository


def _llm_event(event_id: str = "evt-1", **data) -> dict:
    return {
        "id": event_id,
        "type": "llm.call.completed",
        "time": "2026-09-03T10:00:00+00:00",
        "data": {
            "workspace_name": WORKSPACE,
            "model": "openrouter/z-ai/glm-5.2",
            "call_purpose": "deriver",
            "provider_input_tokens": 120,
            "provider_output_tokens": 34,
            **data,
        },
    }


def test_records_token_usage_against_the_workspace() -> None:
    service, repository = _service()

    service.record_cloud_events([_llm_event()])

    recorded = repository.recorded[0]
    assert_that(recorded.workspace_name, equal_to(WORKSPACE))
    assert_that(recorded.input_tokens, equal_to(120))
    assert_that(recorded.output_tokens, equal_to(34))
    assert_that(recorded.call_purpose, equal_to("deriver"))


def test_records_embedding_calls_too() -> None:
    """Embeddings run on the same shared key, so leaving them out would under-report
    every workspace's share of it."""
    service, repository = _service()

    service.record_cloud_events([{**_llm_event(), "type": "embedding.call.completed"}])

    assert_that([e.event_type for e in repository.recorded], contains_exactly("embedding.call.completed"))


def test_ignores_event_types_that_carry_no_usage() -> None:
    """Honcho emits many event kinds on one stream. An unrecognised type must be
    skipped rather than fail the batch that carries real usage alongside it."""
    service, repository = _service()

    stored = service.record_cloud_events(
        [
            {"id": "a", "type": "dream.run.completed", "data": {"workspace_name": WORKSPACE}},
            _llm_event("b"),
        ]
    )

    assert_that(stored, equal_to(1))
    assert_that([e.event_id for e in repository.recorded], contains_exactly("b"))


def test_drops_calls_that_belong_to_no_workspace() -> None:
    """System calls carry no workspace and cannot be attributed to anything, so
    they are dropped rather than pooled into a bucket nobody owns."""
    service, repository = _service()

    service.record_cloud_events([_llm_event(workspace_name=None)])

    assert_that(repository.recorded, empty())


def test_accepts_a_single_event_as_well_as_a_batch() -> None:
    """The emitter posts one CloudEvent when a batch holds exactly one."""
    service, repository = _service()

    service.record_cloud_events(_llm_event())

    assert_that(len(repository.recorded), equal_to(1))


def test_missing_token_counts_are_zero_rather_than_an_error() -> None:
    """Streaming calls emit placeholder counts. They must not fail the batch."""
    service, repository = _service()

    service.record_cloud_events([_llm_event(provider_input_tokens=None, provider_output_tokens=None)])

    assert_that(repository.recorded[0].input_tokens, equal_to(0))


class _FakeLiteLLM:
    def __init__(self, spend: float, key_hash: str):
        self._spend = spend
        self._key_hash = key_hash

    def get_global_spend_report(self, start: str, end: str) -> dict:
        return {self._key_hash: {"spend": self._spend}}


class _TotalsRepository(_FakeRepository):
    def __init__(self, totals):
        super().__init__()
        self._totals = totals

    def token_totals_by_workspace(self, start, end):
        return self._totals


def _cost_service(totals, spend: float):
    import hashlib

    from api.core.config import Config
    from api.domains.costs.repository import WorkspaceTokenTotals

    key = "sk-honcho"
    repository = _TotalsRepository(
        [WorkspaceTokenTotals(workspace_name=w, input_tokens=i, output_tokens=o) for w, i, o in totals]
    )
    litellm = _FakeLiteLLM(spend, hashlib.sha256(key.encode()).hexdigest())
    return HonchoUsageService(
        repository=cast(HonchoUsageRepository, repository),
        litellm=cast("LiteLLMClient", litellm),
        config=Config(honcho_litellm_key=key),
    )


def test_memory_cost_splits_the_real_spend_by_measured_token_share() -> None:
    """Honcho holds one credential for the whole fleet, so LiteLLM reports one
    figure. Shares divide that figure, so they always reconcile to it."""
    agent_a = "af-11111111-1111-1111-1111-111111111111"
    agent_b = "af-22222222-2222-2222-2222-222222222222"
    service = _cost_service([(agent_a, 750, 0), (agent_b, 250, 0)], spend=10.0)

    costs = service.memory_cost_by_agent("2026-09-01", "2026-09-30")

    assert_that(round(sum(costs.values()), 6), equal_to(10.0))
    assert_that(round(costs[UUID(agent_a.removeprefix("af-"))], 4), equal_to(7.5))
    assert_that(round(costs[UUID(agent_b.removeprefix("af-"))], 4), equal_to(2.5))


def test_non_agent_workspaces_still_count_toward_the_denominator() -> None:
    """Dropping them from the divisor would inflate every Agent's share of a bill
    they did not incur alone."""
    agent_a = "af-11111111-1111-1111-1111-111111111111"
    service = _cost_service([(agent_a, 500, 0), ("some-other-workspace", 500, 0)], spend=10.0)

    costs = service.memory_cost_by_agent("2026-09-01", "2026-09-30")

    assert_that(round(costs[UUID(agent_a.removeprefix("af-"))], 4), equal_to(5.0))


def test_no_usage_reports_nothing_rather_than_dividing_by_zero() -> None:
    service = _cost_service([], spend=10.0)

    assert_that(service.memory_cost_by_agent("2026-09-01", "2026-09-30"), equal_to({}))


def test_usage_on_the_end_date_itself_is_counted() -> None:
    """The caller's end date is a calendar day, not an instant. Parsing it bare
    gives midnight, which excludes everything that happened during that day —
    on a live system that is all of today's usage, so every share reads zero."""
    from datetime import UTC, datetime

    captured: dict[str, datetime] = {}

    class _WindowRepo(_FakeRepository):
        def token_totals_by_workspace(self, start, end):
            captured["start"], captured["end"] = start, end
            return []

    from api.core.config import Config

    service = HonchoUsageService(
        repository=cast(HonchoUsageRepository, _WindowRepo()),
        litellm=cast("LiteLLMClient", None),
        config=Config(honcho_litellm_key="sk-honcho"),
    )
    service.memory_cost_by_agent("2026-09-01", "2026-09-03")

    # An event at 20:17 on the end date must fall inside the window.
    assert captured["end"] > datetime(2026, 9, 3, 20, 17, tzinfo=UTC)

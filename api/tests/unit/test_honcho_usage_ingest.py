"""Recording Honcho's CloudEvents telemetry, and reporting its total spend.

Honcho sends every model call to LiteLLM on one service credential, so LiteLLM's
figure for that key is the whole memory bill — one pool-level number. The
per-call telemetry is still recorded per workspace for analytics, but memory cost
is the key's total, reported as-is rather than split per Agent.
"""

from typing import cast

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


def test_memory_cost_total_is_the_honcho_keys_full_spend() -> None:
    """Honcho holds one credential for all memory work, so LiteLLM's figure for
    that key is the whole memory bill — one pool-level number, reported as-is
    (Agents share pools, so there is nothing to split per Agent)."""
    service = _cost_service([], spend=12.5)

    assert_that(service.memory_cost_total("2026-09-01", "2026-09-30"), equal_to(12.5))


def test_memory_cost_total_is_zero_without_a_configured_key() -> None:
    """No memory credential configured means no memory bill to report."""
    from api.core.config import Config

    service = HonchoUsageService(
        repository=cast(HonchoUsageRepository, _FakeRepository()),
        litellm=cast("LiteLLMClient", None),
        config=Config(honcho_litellm_key=""),
    )

    assert_that(service.memory_cost_total("2026-09-01", "2026-09-30"), equal_to(0.0))


def test_memory_cost_total_is_zero_when_the_key_has_no_spend() -> None:
    service = _cost_service([], spend=0.0)

    assert_that(service.memory_cost_total("2026-09-01", "2026-09-30"), equal_to(0.0))

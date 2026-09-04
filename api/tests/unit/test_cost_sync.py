from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from api.domains.agents.models import Agent
from api.domains.costs.constants import (
    COST_SYNC_MAX_RUNTIME_SECONDS,
    COST_SYNC_PAGE_SIZE,
    COST_SYNC_WATERMARK_OVERLAP_SECONDS,
)
from api.domains.costs.models import CostRecord, CostRecordSource
from api.domains.costs.sync import BACKFILL_EPOCH, CostSynchronizer
from api.infrastructure.crypto import encrypt_token

ENCRYPTION_KEY = "1D6Y5nQlDrGqVsUqiF3W7lqTfOZhh0EBBMWCkFRoNTA="
ORG_ID = UUID("00000000-0000-0000-0000-0000000000aa")
ORG_NAME = "Acme Inc"


class FakeCostRepository:
    def __init__(self, *, watermark=None, candidates=None, organization_names=None):
        self.watermark = watermark
        self.candidates = candidates or []
        self.organization_names = organization_names or {ORG_ID: ORG_NAME}
        self.upserted: list[list[CostRecord]] = []
        self.healed: list[tuple[str, Decimal]] = []

    def upsert_many(self, records):
        self.upserted.append(records)
        return len(records)

    def latest_occurred_at(self):
        return self.watermark

    def find_heal_candidates(self, limit):
        return self.candidates[:limit]

    def mark_healed(self, request_id, *, spend, prompt_tokens=None, completion_tokens=None):
        self.healed.append((request_id, spend))
        return True

    def count_heal_candidates(self):
        return len(self.candidates)

    def find_organization_names(self):
        return self.organization_names


class FakeAgentRepository:
    def __init__(self, agents=None):
        self.agents = agents or []

    def find_all_with_litellm_keys(self):
        return self.agents


class FakeSpendLogs:
    """Serves pre-canned pages and records the arguments it was called with."""

    def __init__(self, pages=None, error_on_page=None):
        self.pages = pages or [_page([])]
        self.error_on_page = error_on_page
        self.calls: list[dict] = []

    def get_spend_logs_v2(self, start_date, end_date, page=1, page_size=1000):
        self.calls.append({"start_date": start_date, "end_date": end_date, "page": page, "page_size": page_size})
        if page == self.error_on_page:
            raise RuntimeError("litellm unavailable")
        return self.pages[page - 1]


class FakeGenerations:
    def __init__(self, costs=None, missing=(), failing=()):
        self.costs = costs or {}
        self.missing = set(missing)
        self.failing = set(failing)
        self.looked_up: list[str] = []

    def get_generation(self, generation_id):
        self.looked_up.append(generation_id)
        if generation_id in self.failing:
            raise RuntimeError("openrouter unavailable")
        if generation_id in self.missing:
            return None
        return {
            "total_cost": self.costs.get(generation_id, 0.01),
            "native_tokens_prompt": 11,
            "native_tokens_completion": 22,
        }


def _page(rows, *, page=1, total_pages=1):
    return {
        "data": rows,
        "total": len(rows),
        "page": page,
        "page_size": COST_SYNC_PAGE_SIZE,
        "total_pages": total_pages,
        "total_is_capped": False,
    }


def _row(request_id="gen-1", *, api_key="hash-a", spend=0.5, start="2026-09-01T12:00:00+00:00", **overrides):
    row = {
        "request_id": request_id,
        "api_key": api_key,
        "startTime": start,
        "endTime": "2026-09-01T12:00:07+00:00",
        "spend": spend,
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "model": "openrouter/z-ai/glm-5.2",
        "status": "success",
        "call_type": "acompletion",
        "request_duration_ms": 7805,
        # Fields the allowlist must leave behind.
        "metadata": {"user_api_key_alias": "secret"},
        "requester_ip_address": "10.0.0.1",
        "messages": [{"role": "user", "content": "private"}],
        "request_tags": ["tag"],
        "end_user": "someone",
        "session_id": "sess-1",
    }
    row.update(overrides)
    return row


def _candidate(request_id="gen-1") -> CostRecord:
    return CostRecord(
        request_id=request_id,
        litellm_key_hash="hash-a",
        occurred_at=datetime.now(UTC),
        spend=Decimal(0),
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
        model="openrouter/z-ai/glm-5.2",
        status="success",
        source=CostRecordSource.LITELLM_LIVE,
    )


def _agent(key="agent-key", name="Aria") -> Agent:
    return Agent(
        organization_id=ORG_ID,
        name=name,
        litellm_key_encrypted=encrypt_token(key, ENCRYPTION_KEY),
        platform_template_id=uuid4(),
    )


def _synchronizer(repository, *, agents=None, spend_logs=None, generations=None) -> CostSynchronizer:
    # The fakes satisfy the Protocols structurally, which is the point of declaring
    # the job's dependencies as Protocols in the first place.
    return CostSynchronizer(
        repository=repository,
        agent_repository=FakeAgentRepository(agents),
        spend_logs=spend_logs or FakeSpendLogs(),
        generations=generations or FakeGenerations(),
        encryption_key=ENCRYPTION_KEY,
    )


# --- Watermark ---------------------------------------------------------------


def test_empty_table_syncs_from_the_backfill_epoch():
    """The first run has no special case: an empty table means "sync everything"."""
    repository = FakeCostRepository(watermark=None)
    spend_logs = FakeSpendLogs()

    _synchronizer(repository, spend_logs=spend_logs).run_once()

    assert spend_logs.calls[0]["start_date"] == BACKFILL_EPOCH.strftime("%Y-%m-%d %H:%M:%S")


def test_watermark_rewinds_by_the_overlap_window():
    watermark = datetime(2026, 9, 1, 12, 0, 0, tzinfo=UTC)
    repository = FakeCostRepository(watermark=watermark)
    spend_logs = FakeSpendLogs()

    _synchronizer(repository, spend_logs=spend_logs).run_once()

    expected = watermark - timedelta(seconds=COST_SYNC_WATERMARK_OVERLAP_SECONDS)
    assert spend_logs.calls[0]["start_date"] == expected.strftime("%Y-%m-%d %H:%M:%S")


def test_a_naive_watermark_is_treated_as_utc():
    # Deliberately naive: Postgres can hand back a naive value, and the sync has to
    # assume UTC rather than crash comparing it to an aware one.
    repository = FakeCostRepository(watermark=datetime(2026, 9, 1, 12, 0, 0))  # noqa: DTZ001
    spend_logs = FakeSpendLogs()

    _synchronizer(repository, spend_logs=spend_logs).run_once()

    assert spend_logs.calls[0]["start_date"] == "2026-09-01 11:00:00"


# --- Paging ------------------------------------------------------------------


def test_all_pages_are_read():
    pages = [
        _page([_row("gen-1")], page=1, total_pages=3),
        _page([_row("gen-2")], page=2, total_pages=3),
        _page([_row("gen-3")], page=3, total_pages=3),
    ]
    repository = FakeCostRepository()
    spend_logs = FakeSpendLogs(pages)

    result = _synchronizer(repository, spend_logs=spend_logs).run_once()

    assert result.pages_read == 3
    assert result.rows_synced == 3
    assert [call["page"] for call in spend_logs.calls] == [1, 2, 3]


def test_a_failed_page_stops_the_run_instead_of_skipping_it():
    """Skipping ahead would leave a hole no later run ever revisits."""
    pages = [_page([_row("gen-1")], page=1, total_pages=3), _page([_row("gen-2")], page=2, total_pages=3)]
    repository = FakeCostRepository()
    spend_logs = FakeSpendLogs(pages, error_on_page=2)

    result = _synchronizer(repository, spend_logs=spend_logs).run_once()

    assert result.pages_read == 1
    assert result.truncated is True


def test_an_empty_page_ends_the_run():
    repository = FakeCostRepository()
    spend_logs = FakeSpendLogs([_page([], total_pages=5)])

    result = _synchronizer(repository, spend_logs=spend_logs).run_once()

    assert result.pages_read == 0
    assert result.truncated is False


# --- Projection --------------------------------------------------------------


def test_only_allowlisted_fields_are_stored():
    """Message content and caller identity must never reach the cost table."""
    repository = FakeCostRepository()
    spend_logs = FakeSpendLogs([_page([_row()])])

    _synchronizer(repository, spend_logs=spend_logs).run_once()

    record = repository.upserted[0][0]
    stored = record.model_dump()
    for leaked in ("metadata", "requester_ip_address", "messages", "request_tags", "end_user", "session_id"):
        assert leaked not in stored


def test_spend_is_converted_through_str_to_keep_it_exact():
    repository = FakeCostRepository()
    spend_logs = FakeSpendLogs([_page([_row(spend=0.1)])])

    _synchronizer(repository, spend_logs=spend_logs).run_once()

    assert repository.upserted[0][0].spend == Decimal("0.1")


def test_rows_without_an_id_or_timestamp_are_skipped():
    repository = FakeCostRepository()
    rows = [_row("gen-ok"), _row("", api_key="h"), _row("gen-no-time", start=None)]
    spend_logs = FakeSpendLogs([_page(rows)])

    result = _synchronizer(repository, spend_logs=spend_logs).run_once()

    assert result.rows_skipped == 2
    assert [r.request_id for r in repository.upserted[0]] == ["gen-ok"]


# --- Attribution -------------------------------------------------------------


def test_a_known_key_hash_is_attributed_to_its_agent_and_org():
    import hashlib

    agent = _agent(key="agent-key")
    key_hash = hashlib.sha256(b"agent-key").hexdigest()
    repository = FakeCostRepository()
    spend_logs = FakeSpendLogs([_page([_row(api_key=key_hash)])])

    result = _synchronizer(repository, agents=[agent], spend_logs=spend_logs).run_once()

    record = repository.upserted[0][0]
    assert record.agent_id == agent.id
    assert record.agent_name == "Aria"
    assert record.organization_id == ORG_ID
    assert record.organization_name == ORG_NAME
    assert result.attributed == 1
    assert result.unattributed == 0


def test_an_unknown_key_hash_lands_in_the_unattributed_bucket():
    repository = FakeCostRepository()
    spend_logs = FakeSpendLogs([_page([_row(api_key="nobody-owns-this")])])

    result = _synchronizer(repository, agents=[_agent()], spend_logs=spend_logs).run_once()

    record = repository.upserted[0][0]
    assert record.agent_id is None
    assert record.organization_id is None
    assert result.unattributed == 1


def test_an_undecryptable_key_does_not_abort_the_run():
    """A key encrypted under a rotated secret costs attribution, not the whole sync."""
    broken = Agent(
        organization_id=ORG_ID,
        name="Broken",
        litellm_key_encrypted="not-a-fernet-token",
        platform_template_id=uuid4(),
    )
    repository = FakeCostRepository()
    spend_logs = FakeSpendLogs([_page([_row()])])

    result = _synchronizer(repository, agents=[broken, _agent()], spend_logs=spend_logs).run_once()

    assert result.rows_synced == 1


# --- Healing -----------------------------------------------------------------


def test_candidates_are_healed_with_the_cost_openrouter_reports():
    repository = FakeCostRepository(candidates=[_candidate("gen-a"), _candidate("gen-b")])
    generations = FakeGenerations(costs={"gen-a": 0.00265820, "gen-b": 0.5})

    result = _synchronizer(repository, generations=generations).run_once()

    assert result.heal_succeeded == 2
    assert dict(repository.healed) == {"gen-a": Decimal("0.0026582"), "gen-b": Decimal("0.5")}


def test_a_zero_cost_generation_is_still_marked_healed():
    """Otherwise a genuinely free call is re-fetched on every run, for ever."""
    repository = FakeCostRepository(candidates=[_candidate("gen-free")])
    generations = FakeGenerations(costs={"gen-free": 0})

    result = _synchronizer(repository, generations=generations).run_once()

    assert result.heal_succeeded == 1
    assert repository.healed == [("gen-free", Decimal(0))]


def test_a_missing_generation_is_left_alone_rather_than_zeroed():
    """A 404 means "we could not find out", not "this call was free"."""
    repository = FakeCostRepository(candidates=[_candidate("gen-gone")])
    generations = FakeGenerations(missing=["gen-gone"])

    result = _synchronizer(repository, generations=generations).run_once()

    assert result.heal_not_found == 1
    assert result.heal_succeeded == 0
    assert repository.healed == []


def test_one_failed_lookup_does_not_abort_the_others():
    repository = FakeCostRepository(candidates=[_candidate("gen-a"), _candidate("gen-bad"), _candidate("gen-c")])
    generations = FakeGenerations(failing=["gen-bad"])

    result = _synchronizer(repository, generations=generations).run_once()

    assert result.heal_failed == 1
    assert result.heal_succeeded == 2


def test_a_generation_without_a_cost_is_not_marked_healed():
    class NoCost:
        def get_generation(self, generation_id):
            return {"native_tokens_prompt": 1}

    repository = FakeCostRepository(candidates=[_candidate("gen-a")])

    result = _synchronizer(repository, generations=NoCost()).run_once()

    assert result.heal_failed == 1
    assert repository.healed == []


# --- Runtime guard -----------------------------------------------------------


def test_the_deadline_stops_paging_and_marks_the_run_truncated(monkeypatch):
    ticks = iter([0.0, 0.0, 0.0, float(COST_SYNC_MAX_RUNTIME_SECONDS + 1)] + [1e9] * 50)
    monkeypatch.setattr("api.domains.costs.sync.time.monotonic", lambda: next(ticks))

    pages = [_page([_row("gen-1")], page=1, total_pages=9), _page([_row("gen-2")], page=2, total_pages=9)]
    repository = FakeCostRepository()
    spend_logs = FakeSpendLogs(pages)

    result = _synchronizer(repository, spend_logs=spend_logs).run_once()

    assert result.truncated is True
    # Two pages read, then the deadline hit — not zero, which would pass vacuously.
    assert result.pages_read == 2


def test_healing_is_skipped_when_the_deadline_has_already_passed(monkeypatch):
    ticks = iter([0.0, 0.0, float(COST_SYNC_MAX_RUNTIME_SECONDS + 1)] + [1e9] * 50)
    monkeypatch.setattr("api.domains.costs.sync.time.monotonic", lambda: next(ticks))

    repository = FakeCostRepository(candidates=[_candidate("gen-a")])
    generations = FakeGenerations()

    result = _synchronizer(repository, generations=generations).run_once()

    assert generations.looked_up == []
    assert result.truncated is True

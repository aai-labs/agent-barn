from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from hamcrest import assert_that, equal_to, has_entries, has_length, none
from sqlmodel import Session, select

from api.domains.agents.repository import AgentRepository
from api.domains.costs.models import CostRecord, CostRecordSource
from api.domains.costs.repository import CostRepository
from api.domains.costs.sync import CostSynchronizer
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.steps.agent_memory import agent_memory_api_setup
from api.tests.steps.cost import cost_records_are_clean


class MemorySpendLogs:
    def __init__(self, organization_id):
        self.organization_id = organization_id

    def get_spend_logs_v2(self, start_date, end_date, page=1, page_size=1000):
        return {
            "data": [
                {
                    "request_id": "gen-memory-cost-test",
                    "startTime": datetime.now(UTC).isoformat(),
                    "api_key": "memory-hash",
                    "end_user": f"org-{self.organization_id}",
                    "spend": 0,
                    "prompt_tokens": 10,
                    "completion_tokens": 2,
                    "total_tokens": 12,
                    "model": "openrouter/openai/gpt-4.1-mini",
                    "status": "success",
                    "messages": [{"content": "private-content-marker"}],
                    "metadata": {"secret": "private-content-marker"},
                }
            ],
            "total_pages": 1,
        }


class MemoryGeneration:
    def get_generation(self, generation_id):
        return {"total_cost": "0.012345678901"}


def test_memory_sync_replay_and_healing_produce_one_exact_organization_cost():
    with given(agent_memory_api_setup(cost_records_are_clean())) as context:
        repository = context.injector.get(CostRepository)
        synchronizer = CostSynchronizer(
            repository,
            context.injector.get(AgentRepository),
            MemorySpendLogs(context.organization.id),
            MemoryGeneration(),
            "",
            frozenset({"memory-hash"}),
        )
        with when("the same model charge is synced, healed, and replayed"):
            synchronizer.run_once()
            synchronizer.run_once()
        with then("one healed cost remains with its Organization and memory origin"):
            delegate = context.injector.get(PostgresRepositoryDelegate)
            with Session(delegate.engine) as session:
                records = session.exec(select(CostRecord)).all()
            assert_that(records, has_length(1))
            row = records[0]
            assert_that(row.organization_id, equal_to(context.organization.id))
            assert_that(row.agent_id, none())
            assert_that(row.agent_name, equal_to("Agent Memory"))
            assert_that(row.is_memory, equal_to(True))
            assert_that(row.spend, equal_to(Decimal("0.012345678901")))
            assert_that(row.source, equal_to(CostRecordSource.OPENROUTER_BACKFILL))
            assert_that("private-content-marker" in row.model_dump_json(), equal_to(False))
        with then("the Organization cost surface includes the charge"):
            response = context.client.get(
                f"/api/v1/organizations/{context.organization.id}/costs/summary",
                headers={"Authorization": f"Bearer {context.access_token}"},
            )
            assert_that(response.status_code, equal_to(200))
            assert_that(response.json(), has_entries(total_calls=1, active_agents=0))
            assert_that(response.json()["total_spend"], equal_to(0.012345678901))


def test_memory_spend_is_scoped_to_origin_organization_and_half_open_window():
    with given(agent_memory_api_setup(cost_records_are_clean())) as context:
        repository = context.injector.get(CostRepository)
        start = datetime.now(UTC) - timedelta(days=1)
        end = start + timedelta(days=1)
        rows = [
            CostRecord(
                request_id=str(uuid4()),
                litellm_key_hash="retired-key",
                occurred_at=at,
                spend=Decimal("1.25"),
                model="test",
                status="success",
                is_memory=memory,
                organization_id=org,
            )
            for at, memory, org in (
                (start, True, context.organization.id),
                (start - timedelta(microseconds=1), True, context.organization.id),
                (end, True, context.organization.id),
                (start, False, context.organization.id),
                (start, True, uuid4()),
            )
        ]
        repository.upsert_many(rows)
        with when("memory charges in one Organization renewal window are summed"):
            spend = repository.memory_spend(context.organization.id, start, end)
        with then("only that Organization's memory origin inside the window counts"):
            assert_that(spend, equal_to(Decimal("1.25")))


def test_registered_team_memory_key_is_attributed_only_to_its_own_bank():
    with given(agent_memory_api_setup(cost_records_are_clean())) as context:
        repository = context.injector.get(CostRepository)
        logs = MemorySpendLogs(context.organization.id)
        synchronizer = CostSynchronizer(
            repository,
            context.injector.get(AgentRepository),
            logs,
            MemoryGeneration(),
            "",
            memory_key_source=lambda: {"memory-hash": context.organization.id},
        )
        synchronizer.run_once()
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            row = session.exec(select(CostRecord)).one()
        assert_that(row.is_memory, equal_to(True))
        assert_that(row.organization_id, equal_to(context.organization.id))
        forged = logs.get_spend_logs_v2(None, None)["data"][0]
        forged["end_user"] = f"org-{uuid4()}"
        foreign_id = UUID(forged["end_user"][4:])
        parsed = synchronizer._to_record(forged, {}, {foreign_id: "Foreign Organization"})
        assert parsed is not None
        assert_that(parsed.organization_id, none())

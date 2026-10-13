from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlmodel import Session

from api.core.config import get_config
from api.domains.costs.models import CostRecord, CostRecordSource
from api.domains.costs.repository import CostRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import LambdaWith


def cost_records_are_clean():
    """``database_is_clean`` does not touch cost_record, and totals are global."""

    def step(context):
        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        with delegate.engine.begin() as connection:
            connection.execute(text("TRUNCATE cost_record, cost_sync_state"))

    return step


def there_are_cost_records(
    *,
    count: int = 1,
    spend: str = "1.0",
    model: str = "openrouter/z-ai/glm-5.2",
    prompt_tokens: int = 100,
    completion_tokens: int = 50,
    status: str = "success",
    source: CostRecordSource = CostRecordSource.LITELLM_LIVE,
    agent_id: UUID | None = None,
    agent_name: str | None = None,
    organization_id: UUID | None = None,
    organization_name: str | None = None,
    unattributed: bool = False,
    without_agent: bool = False,
    is_memory: bool = False,
    minutes_ago: int = 5,
    occurred_at: datetime | None = None,
    spacing_seconds: int = 1,
):
    """Write cost rows directly.

    Cost rows are written by the sync CronJob, not by anything the API exposes, so
    tests seed the table rather than driving an endpoint to fill it.

    ``agent_id`` and ``organization_id`` default to the Agent and Organization the
    surrounding scenario set up, which is what makes a seeded row visible to the
    org-scoped endpoints under test. Passing None cannot express "no agent", since
    that is also what "not specified" looks like — use ``unattributed=True``, which
    is the state the platform page's unattributed bucket reports on. ``without_agent=True``
    keeps the Organization and drops only the Agent, as memory costs do.

    ``occurred_at`` pins the calls to an exact instant instead of ``minutes_ago``,
    for tests that care which calendar month a row lands in.
    """

    def step(context):
        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        if unattributed:
            resolved_agent_id = resolved_agent_name = resolved_org_id = resolved_org_name = None
        else:
            resolved_agent_id = agent_id if agent_id is not None else getattr(context.agent, "id", None)
            resolved_agent_name = agent_name if agent_name is not None else getattr(context.agent, "name", None)
            resolved_org_id = (
                organization_id if organization_id is not None else getattr(context.organization, "id", None)
            )
            resolved_org_name = (
                organization_name if organization_name is not None else getattr(context.organization, "name", None)
            )
            if without_agent:
                resolved_agent_id = resolved_agent_name = None
        # Rows walk backwards from the base time, so `count` rows land inside one
        # burst at the default spacing and in separate ones at a wide spacing.
        base = occurred_at if occurred_at is not None else datetime.now(UTC) - timedelta(minutes=minutes_ago)

        records = [
            CostRecord(
                request_id=f"gen-test-{uuid4().hex}",
                litellm_key_hash="0" * 64,
                occurred_at=base - timedelta(seconds=index * spacing_seconds),
                spend=Decimal(spend),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=prompt_tokens + completion_tokens,
                model=model,
                status=status,
                call_type="acompletion",
                request_duration_ms=1234,
                agent_id=resolved_agent_id,
                organization_id=resolved_org_id,
                agent_name=resolved_agent_name,
                organization_name=resolved_org_name,
                is_memory=is_memory,
                source=source,
            )
            for index in range(count)
        ]
        with Session(delegate.engine) as session:
            session.add_all(records)
            session.commit()

    return step


def memory_budget_is_present(*, limit=10, runtime_spend=4, memory_spend="0", synced=True, **overrides):
    def step(context):
        now = datetime.now(UTC)
        organization = context.organization
        settings = {
            "llm_budget_usd": limit,
            "llm_budget_duration": "30d",
            "llm_spend_usd": runtime_spend,
            "llm_spend_observed_at": now,
            "llm_budget_renews_at": now + timedelta(days=1),
            **overrides,
        }
        for field, value in settings.items():
            setattr(organization, field, value)
        context.injector.get(PostgresRepositoryDelegate).save(organization)
        costs = context.injector.get(CostRepository)
        if synced:
            costs.record_sync_completion(now)
        if Decimal(memory_spend):
            costs.upsert_many(
                [
                    CostRecord(
                        request_id=str(uuid4()),
                        litellm_key_hash="f" * 64,
                        occurred_at=now - timedelta(minutes=1),
                        spend=Decimal(memory_spend),
                        model="test",
                        status="success",
                        is_memory=True,
                        organization_id=organization.id,
                    )
                ]
            )
        config = get_config()
        previous = config.memory_litellm_key_hashes
        config.memory_litellm_key_hashes = "f" * 64
        return LambdaWith(lambda: None, lambda: setattr(config, "memory_litellm_key_hashes", previous))

    return step

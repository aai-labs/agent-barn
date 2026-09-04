from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlmodel import Session

from api.domains.costs.models import CostRecord, CostRecordSource
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


def cost_records_are_clean():
    """``database_is_clean`` does not touch cost_record, and totals are global."""

    def step(context):
        delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
        with delegate.engine.begin() as connection:
            connection.execute(text("TRUNCATE cost_record"))

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
    minutes_ago: int = 5,
):
    """Write cost rows directly.

    Cost rows are written by the sync CronJob, not by anything the API exposes, so
    tests seed the table rather than driving an endpoint to fill it.

    ``agent_id`` and ``organization_id`` default to the Agent and Organization the
    surrounding scenario set up, which is what makes a seeded row visible to the
    org-scoped endpoints under test. Passing None cannot express "no agent", since
    that is also what "not specified" looks like — use ``unattributed=True``, which
    is the state the platform page's unattributed bucket reports on.
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
        occurred_at = datetime.now(UTC) - timedelta(minutes=minutes_ago)

        records = [
            CostRecord(
                request_id=f"gen-test-{uuid4().hex}",
                litellm_key_hash="0" * 64,
                occurred_at=occurred_at - timedelta(seconds=index),
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
                source=source,
            )
            for index in range(count)
        ]
        with Session(delegate.engine) as session:
            session.add_all(records)
            session.commit()

    return step

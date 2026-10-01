from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlmodel import Session

from api.domains.business_value.classifier import BusinessActionStatus
from api.domains.business_value.models import BusinessAction
from api.domains.tool_calls.models import ToolCall, ToolCallStatus
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

SEEDED_TOOL_NAME = "terminal"
SEEDED_INTEGRATION = "jira"
SEEDED_RESOURCE = "issues"
SEEDED_VERB = "create"
DEFAULT_MINUTES_AGO = 5


def there_are_business_actions(
    *,
    outcome_type: str | None,
    is_write: bool | None,
    status: BusinessActionStatus,
    count: int = 1,
    occurred_at: datetime | None = None,
):
    def step(context):
        agent = context.agent
        at = occurred_at if occurred_at is not None else datetime.now(UTC) - timedelta(minutes=DEFAULT_MINUTES_AGO)
        tool_call = ToolCall(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            session_id="session-1",
            external_id=f"seeded-{uuid4().hex}",
            tool_name=SEEDED_TOOL_NAME,
            arguments={},
            status=ToolCallStatus.SUCCESS,
            occurred_at=at,
            completed_at=at,
        )
        actions = [
            BusinessAction(
                organization_id=agent.organization_id,
                agent_id=agent.id,
                tool_call_id=tool_call.id,
                ordinal=ordinal,
                integration=SEEDED_INTEGRATION,
                resource=SEEDED_RESOURCE,
                verb=SEEDED_VERB,
                outcome_type=outcome_type,
                is_write=is_write,
                status=status,
                occurred_at=at,
                completed_at=at,
            )
            for ordinal in range(count)
        ]
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            session.add(tool_call)
            session.flush()
            session.add_all(actions)
            session.commit()

    return step

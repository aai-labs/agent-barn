from uuid import UUID

import sqlalchemy as sa
from sqlmodel import Session, col

from api.domains.agent_tasks.models import AgentTask


def stage_agent_task_cleanup(session: Session, agent_id: UUID, organization_id: UUID) -> None:
    """Remove a deleted Agent's Tasks in the caller's Agent deletion transaction.

    Agent deletion is a soft delete, so the Agent foreign key never cascades. Deleting
    the Tasks cascades to their Notes, Files and the Postgres store's chunks; a store
    outside Postgres would need its bytes removed here too.
    """
    session.exec(
        sa.delete(AgentTask).where(
            col(AgentTask.agent_id) == agent_id,
            col(AgentTask.organization_id) == organization_id,
        )
    )

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from api.domains.business_value.classifier import SHELL_TOOL_NAMES, ClassifiedAction, classify
from api.domains.business_value.models import TOOL_CALL_ORDINAL_CONSTRAINT, BusinessAction
from api.domains.tool_calls.models import ToolCall
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

logger = logging.getLogger(__name__)

REMAPPED_COLUMNS = ("integration", "resource", "verb", "is_write", "outcome_type", "updated_at")


@inject
@singleton
@dataclass
class BusinessActionRepository:
    delegate: PostgresRepositoryDelegate

    def record_in_session(self, session: Session, tool_call: ToolCall) -> list[BusinessAction]:
        """Insert the Tool Call's Business Actions inside the caller's transaction.

        Returns only the rows this call inserted. A database error rolls back this
        savepoint alone, so the caller's Tool Call batch still commits.
        """
        try:
            actions = classify(tool_call)
        except Exception:
            logger.exception("Could not classify tool call %s", tool_call.id)
            return []
        if not actions:
            return []

        now = datetime.now(UTC)
        statement = (
            pg_insert(BusinessAction)
            .values([self._values(tool_call, action, now) for action in actions])
            .on_conflict_do_nothing(constraint=TOOL_CALL_ORDINAL_CONSTRAINT)
            .returning(BusinessAction)
        )
        savepoint = session.begin_nested()
        try:
            inserted = list(session.scalars(statement).all())
        except SQLAlchemyError:
            savepoint.rollback()
            logger.exception("Could not record business actions for tool call %s", tool_call.id)
            return []
        savepoint.commit()
        return inserted

    def find_backfill_batch(self, after_id: UUID | None, limit: int) -> list[ToolCall]:
        """Completed shell Tool Calls after ``after_id``, in id order.

        Unscoped: only the operator-run backfill calls this, and no router reaches it.
        """
        query = select(ToolCall).where(
            col(ToolCall.tool_name).in_(SHELL_TOOL_NAMES),
            col(ToolCall.completed_at).is_not(None),
        )
        if after_id is not None:
            query = query.where(col(ToolCall.id) > after_id)
        with Session(self.delegate.engine) as session:
            return list(session.exec(query.order_by(col(ToolCall.id)).limit(limit)).all())

    def upsert_classified(self, classified: list[tuple[ToolCall, list[ClassifiedAction]]]) -> int:
        """Insert or re-map Business Actions, leaving the stored status untouched.

        Unscoped: only the operator-run backfill calls this, and no router reaches it.
        """
        now = datetime.now(UTC)
        values = [self._values(tool_call, action, now) for tool_call, actions in classified for action in actions]
        if not values:
            return 0
        statement = pg_insert(BusinessAction).values(values)
        statement = statement.on_conflict_do_update(
            constraint=TOOL_CALL_ORDINAL_CONSTRAINT,
            set_={column: statement.excluded[column] for column in REMAPPED_COLUMNS},
        ).returning(col(BusinessAction.id))
        with Session(self.delegate.engine) as session:
            upserted = len(session.exec(statement).all())  # type: ignore[call-overload]
            session.commit()
        return upserted

    @staticmethod
    def _values(tool_call: ToolCall, action: ClassifiedAction, now: datetime) -> dict[str, Any]:
        return {
            "id": uuid.uuid7(),
            "created_at": now,
            "updated_at": now,
            "organization_id": tool_call.organization_id,
            "agent_id": tool_call.agent_id,
            "tool_call_id": tool_call.id,
            "ordinal": action.ordinal,
            "integration": action.integration,
            "resource": action.resource,
            "verb": action.verb,
            "outcome_type": action.outcome_type.value if action.outcome_type is not None else None,
            "is_write": action.is_write,
            "status": action.status,
            "occurred_at": tool_call.occurred_at,
            "completed_at": tool_call.completed_at,
        }

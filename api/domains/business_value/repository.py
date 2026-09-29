import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, col, select

from api.domains.business_value.classifier import SHELL_TOOL_NAMES, ClassifiedAction, classify
from api.domains.business_value.models import (
    OUTCOME_MINUTES_ORGANIZATION_TYPE_CONSTRAINT,
    TOOL_CALL_ORDINAL_CONSTRAINT,
    BusinessAction,
    OrganizationOutcomeMinutes,
    OrganizationValueSettings,
)
from api.domains.events import ActorIdentity, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import EVENT_REGISTRY, ORGANIZATION_VALUE_SETTINGS_CHANGED
from api.domains.events.repository import OutboxMessageRepository
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


@dataclass(frozen=True)
class ValueSettingsChangeResult:
    delivery_ids: list[UUID]


@inject
@singleton
@dataclass
class ValueSettingsRepository:
    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def get_hourly_rate(self, organization_id: UUID) -> Decimal | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(col(OrganizationValueSettings.hourly_rate_usd)).where(
                    col(OrganizationValueSettings.organization_id) == organization_id
                )
            ).first()

    def get_minute_overrides(self, organization_id: UUID) -> dict[str, int]:
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(OrganizationOutcomeMinutes.outcome_type, OrganizationOutcomeMinutes.minutes_saved).where(
                    col(OrganizationOutcomeMinutes.organization_id) == organization_id
                )
            ).all()
        return {outcome_type: minutes_saved for outcome_type, minutes_saved in rows}

    def save_with_event(
        self,
        organization_id: UUID,
        *,
        hourly_rate: Decimal | None,
        rate_changed: bool,
        minute_changes: dict[str, int | None],
        field_changes: dict[str, dict[str, str | None]],
        actor: ActorIdentity,
        actor_display: str,
        subject_display: str,
    ) -> ValueSettingsChangeResult:
        now = datetime.now(UTC)
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            if rate_changed:
                settings = session.exec(
                    select(OrganizationValueSettings).where(
                        col(OrganizationValueSettings.organization_id) == organization_id
                    )
                ).first()
                if settings is None:
                    settings = OrganizationValueSettings(organization_id=organization_id)
                settings.hourly_rate_usd = hourly_rate
                settings.updated_at = now
                session.add(settings)

            for outcome_type, minutes in minute_changes.items():
                session.exec(self._minute_change_statement(organization_id, outcome_type, minutes, now))  # type: ignore[call-overload]
            session.flush()

            event = EVENT_REGISTRY.build_event(
                event_name=ORGANIZATION_VALUE_SETTINGS_CHANGED,
                schema_version=1,
                occurred_at=now,
                organization_id=organization_id,
                actor=actor,
                subject=SubjectIdentity(
                    type=SubjectIdentityType.ORGANIZATION,
                    id=organization_id,
                    organization_id=organization_id,
                ),
                correlation_id=uuid4(),
                payload={
                    "organization_id": organization_id,
                    "field_changes": field_changes,
                    "actor_display": actor_display,
                    "subject_display": subject_display,
                },
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
        return ValueSettingsChangeResult(delivery_ids=delivery_ids)

    @staticmethod
    def _minute_change_statement(organization_id: UUID, outcome_type: str, minutes: int | None, now: datetime):
        if minutes is None:
            return sa.delete(OrganizationOutcomeMinutes).where(
                col(OrganizationOutcomeMinutes.organization_id) == organization_id,
                col(OrganizationOutcomeMinutes.outcome_type) == outcome_type,
            )
        statement = pg_insert(OrganizationOutcomeMinutes).values(
            id=uuid.uuid7(),
            created_at=now,
            updated_at=now,
            organization_id=organization_id,
            outcome_type=outcome_type,
            minutes_saved=minutes,
        )
        return statement.on_conflict_do_update(
            constraint=OUTCOME_MINUTES_ORGANIZATION_TYPE_CONSTRAINT,
            set_={
                "minutes_saved": statement.excluded.minutes_saved,
                "updated_at": statement.excluded.updated_at,
            },
        )

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy import delete, or_, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, SQLModel, col, select

from api.domains.agent_webhooks.models import WebhookInvocation
from api.domains.agents.models import Agent
from api.domains.agents.repository import agent_scope_predicates
from api.domains.business_value.classifier import SHELL_TOOL_NAMES, BusinessActionStatus, ClassifiedAction, classify
from api.domains.business_value.models import (
    OUTCOME_MINUTES_ORGANIZATION_TYPE_CONSTRAINT,
    TOOL_CALL_ORDINAL_CONSTRAINT,
    VALUE_SETTINGS_ORGANIZATION_CONSTRAINT,
    BusinessAction,
    OrganizationOutcomeMinutes,
    OrganizationValueSettings,
)
from api.domains.communications.models import (
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationDirection,
)
from api.domains.conversations.models import AgentChatMessage, MessageDirection
from api.domains.events import ActorIdentity, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import EVENT_REGISTRY, ORGANIZATION_VALUE_SETTINGS_CHANGED
from api.domains.events.repository import OutboxMessageRepository
from api.domains.platform_admin.models import StatsWindow
from api.domains.rbac.policy import AuthorizationScope
from api.domains.tool_calls.models import ToolCall
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

logger = logging.getLogger(__name__)

MAPPED_COLUMNS = ("integration", "resource", "verb", "is_write", "outcome_type")
BUSINESS_ACTION_TABLE = SQLModel.metadata.tables["business_action"]
RATE_QUANTUM = Decimal("0.01")
HOURLY_RATE_FIELD = "hourly_rate_usd"
OUTCOME_MINUTES_FIELD_PREFIX = "outcome_minutes."
SUCCEEDED = CommunicationDeliveryStatus.SUCCEEDED
DEAD_LETTERED = CommunicationDeliveryStatus.DEAD_LETTERED
UNAVAILABLE = CommunicationDeliveryStatus.UNAVAILABLE
HANDLED_DENOMINATOR_STATUSES = (SUCCEEDED, DEAD_LETTERED, UNAVAILABLE)
FIRST_ATTEMPT = 1
MEDIAN = 0.5


@dataclass(frozen=True)
class AppliedClassification:
    recorded: int
    removed: int


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

    def apply_classified(self, classified: list[tuple[ToolCall, list[ClassifiedAction]]]) -> AppliedClassification:
        """Make each Tool Call's stored Business Actions match its new classification.

        Rows whose ordinal the classification no longer produces are deleted, new rows are
        inserted, and existing rows are updated only when their mapping changed. Status is
        never changed. Unscoped: only the operator-run backfill calls this, and no router
        reaches it.
        """
        if not classified:
            return AppliedClassification(recorded=0, removed=0)
        now = datetime.now(UTC)
        values = [self._values(tool_call, action, now) for tool_call, actions in classified for action in actions]
        kept = [(value["tool_call_id"], value["ordinal"]) for value in values]
        stale = (
            delete(BusinessAction)
            .where(
                col(BusinessAction.tool_call_id).in_([tool_call.id for tool_call, _ in classified]),
                ~tuple_(col(BusinessAction.tool_call_id), col(BusinessAction.ordinal)).in_(kept),
            )
            .returning(col(BusinessAction.id))
        )
        with Session(self.delegate.engine) as session:
            removed = len(session.exec(stale).all())  # type: ignore[call-overload]
            recorded = len(session.exec(self._upsert(values)).all()) if values else 0  # type: ignore[call-overload]
            session.commit()
        return AppliedClassification(recorded=recorded, removed=removed)

    @staticmethod
    def _upsert(values: list[dict[str, Any]]):
        statement = pg_insert(BusinessAction).values(values)
        return statement.on_conflict_do_update(
            constraint=TOOL_CALL_ORDINAL_CONSTRAINT,
            set_={column: statement.excluded[column] for column in (*MAPPED_COLUMNS, "updated_at")},
            where=or_(
                *(
                    BUSINESS_ACTION_TABLE.c[column].is_distinct_from(statement.excluded[column])
                    for column in MAPPED_COLUMNS
                )
            ),
        ).returning(col(BusinessAction.id))

    def category_counts(
        self,
        window: StatsWindow,
        scope: AuthorizationScope,
    ) -> list[tuple[bool | None, str | None, BusinessActionStatus, int]]:
        query = (
            sa.select(
                col(BusinessAction.is_write),
                col(BusinessAction.outcome_type),
                col(BusinessAction.status),
                sa.func.count(),
            )
            .select_from(BusinessAction)
            .join(Agent, col(Agent.id) == col(BusinessAction.agent_id))
            .where(*self._visible(window, scope))
            .group_by(col(BusinessAction.is_write), col(BusinessAction.outcome_type), col(BusinessAction.status))
        )
        with self.delegate.engine.connect() as connection:
            rows = connection.execute(query).all()
        return [(row[0], row[1], row[2], int(row[3])) for row in rows]

    def successful_counts_by_bucket(
        self,
        window: StatsWindow,
        scope: AuthorizationScope,
    ) -> list[tuple[datetime, str, int]]:
        bucket = sa.func.date_trunc(window.granularity.value, sa.func.timezone("UTC", col(BusinessAction.occurred_at)))
        query = (
            sa.select(bucket, col(BusinessAction.outcome_type), sa.func.count())
            .select_from(BusinessAction)
            .join(Agent, col(Agent.id) == col(BusinessAction.agent_id))
            .where(*self._visible(window, scope), *self._successful())
            .group_by(bucket, col(BusinessAction.outcome_type))
            .order_by(bucket, col(BusinessAction.outcome_type))
        )
        with self.delegate.engine.connect() as connection:
            rows = connection.execute(query).all()
        return [(row[0], row[1], int(row[2])) for row in rows]

    def successful_counts_by_agent(
        self,
        window: StatsWindow,
        scope: AuthorizationScope,
    ) -> list[tuple[UUID, str, int]]:
        query = (
            sa.select(col(BusinessAction.agent_id), col(BusinessAction.outcome_type), sa.func.count())
            .select_from(BusinessAction)
            .join(Agent, col(Agent.id) == col(BusinessAction.agent_id))
            .where(*self._visible(window, scope), *self._successful())
            .group_by(col(BusinessAction.agent_id), col(BusinessAction.outcome_type))
        )
        with self.delegate.engine.connect() as connection:
            rows = connection.execute(query).all()
        return [(row[0], row[1], int(row[2])) for row in rows]

    @staticmethod
    def _visible(window: StatsWindow, scope: AuthorizationScope) -> tuple:
        return (
            col(BusinessAction.organization_id) == scope.organization_id,
            col(BusinessAction.occurred_at) >= window.start,
            col(BusinessAction.occurred_at) < window.end,
            *agent_scope_predicates(scope, include_deleted=True),
        )

    @staticmethod
    def _successful() -> tuple:
        return (
            col(BusinessAction.is_write).is_(True),
            col(BusinessAction.outcome_type).is_not(None),
            col(BusinessAction.status) == BusinessActionStatus.SUCCESS,
        )

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
class DeliveryOutcomes:
    succeeded: int = 0
    dead_lettered: int = 0
    unavailable: int = 0
    first_attempt: int = 0
    median_seconds: float | None = None


@inject
@singleton
@dataclass
class ValueActivityRepository:
    delegate: PostgresRepositoryDelegate

    def inbound_messages_by_agent(self, window: StatsWindow, scope: AuthorizationScope) -> list[tuple[UUID, int]]:
        query = (
            sa.select(col(AgentChatMessage.agent_id), sa.func.count())
            .select_from(AgentChatMessage)
            .join(Agent, col(Agent.id) == col(AgentChatMessage.agent_id))
            .where(
                col(AgentChatMessage.direction) == MessageDirection.INBOUND,
                *self._visible(col(AgentChatMessage.occurred_at), window, scope),
            )
            .group_by(col(AgentChatMessage.agent_id))
        )
        return self._counts(query)

    def webhook_invocations_by_bucket(
        self, window: StatsWindow, scope: AuthorizationScope
    ) -> list[tuple[datetime, int]]:
        unit = window.granularity.value
        buckets = sa.select(
            sa.func.generate_series(
                sa.func.date_trunc(unit, sa.func.timezone("UTC", sa.literal(window.start))),
                sa.func.date_trunc(unit, sa.func.timezone("UTC", sa.literal(window.end))),
                sa.text(f"interval '{window.granularity.interval}'"),
            ).label("bucket")
        ).subquery()
        counts = (
            sa.select(
                sa.func.date_trunc(unit, sa.func.timezone("UTC", col(WebhookInvocation.created_at))).label("bucket"),
                sa.func.count().label("invocations"),
            )
            .select_from(WebhookInvocation)
            .join(Agent, col(Agent.id) == col(WebhookInvocation.agent_id))
            .where(
                col(WebhookInvocation.organization_id) == scope.organization_id,
                *self._visible(col(WebhookInvocation.created_at), window, scope),
            )
            .group_by(sa.text("1"))
            .subquery()
        )
        query = (
            sa.select(buckets.c.bucket, sa.func.coalesce(counts.c.invocations, 0))
            .select_from(buckets.outerjoin(counts, buckets.c.bucket == counts.c.bucket))
            .order_by(buckets.c.bucket)
        )
        with self.delegate.engine.connect() as connection:
            rows = connection.execute(query).all()
        return [(row[0], int(row[1])) for row in rows]

    def webhook_invocations_by_agent(self, window: StatsWindow, scope: AuthorizationScope) -> list[tuple[UUID, int]]:
        query = (
            sa.select(col(WebhookInvocation.agent_id), sa.func.count())
            .select_from(WebhookInvocation)
            .join(Agent, col(Agent.id) == col(WebhookInvocation.agent_id))
            .where(
                col(WebhookInvocation.organization_id) == scope.organization_id,
                *self._visible(col(WebhookInvocation.created_at), window, scope),
            )
            .group_by(col(WebhookInvocation.agent_id))
        )
        return self._counts(query)

    def delivery_outcomes_total(self, window: StatsWindow, scope: AuthorizationScope) -> DeliveryOutcomes:
        query = self._delivery_outcomes_query(window, scope)
        with self.delegate.engine.connect() as connection:
            row = connection.execute(query).one()
        return self._outcomes(row)

    def delivery_outcomes_by_agent(
        self, window: StatsWindow, scope: AuthorizationScope
    ) -> list[tuple[UUID, DeliveryOutcomes]]:
        query = self._delivery_outcomes_query(window, scope, col(CommunicationDelivery.agent_id)).group_by(
            col(CommunicationDelivery.agent_id)
        )
        with self.delegate.engine.connect() as connection:
            rows = connection.execute(query).all()
        return [(row[0], self._outcomes(row[1:])) for row in rows]

    def tool_calls_by_agent(self, window: StatsWindow, scope: AuthorizationScope) -> list[tuple[UUID, int]]:
        query = (
            sa.select(col(ToolCall.agent_id), sa.func.count())
            .select_from(ToolCall)
            .join(Agent, col(Agent.id) == col(ToolCall.agent_id))
            .where(
                col(ToolCall.organization_id) == scope.organization_id,
                *self._visible(col(ToolCall.occurred_at), window, scope),
            )
            .group_by(col(ToolCall.agent_id))
        )
        return self._counts(query)

    def _delivery_outcomes_query(self, window: StatsWindow, scope: AuthorizationScope, *group_columns):
        status = col(CommunicationDelivery.status)
        first_attempt = sa.and_(status == SUCCEEDED, col(CommunicationDelivery.attempt_count) == FIRST_ATTEMPT)
        response_seconds = sa.cast(
            sa.func.extract("epoch", col(CommunicationDelivery.completed_at) - col(CommunicationDelivery.created_at)),
            sa.Float,
        )
        return (
            sa.select(
                *group_columns,
                sa.func.count().filter(status == SUCCEEDED),
                sa.func.count().filter(status == DEAD_LETTERED),
                sa.func.count().filter(status == UNAVAILABLE),
                sa.func.count().filter(first_attempt),
                sa.func.percentile_cont(MEDIAN).within_group(response_seconds).filter(first_attempt),
            )
            .select_from(CommunicationDelivery)
            .join(Agent, col(Agent.id) == col(CommunicationDelivery.agent_id))
            .where(
                col(CommunicationDelivery.organization_id) == scope.organization_id,
                col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND,
                status.in_(HANDLED_DENOMINATOR_STATUSES),
                *self._visible(col(CommunicationDelivery.completed_at), window, scope),
            )
        )

    def _counts(self, query) -> list[tuple[UUID, int]]:
        with self.delegate.engine.connect() as connection:
            rows = connection.execute(query).all()
        return [(row[0], int(row[1])) for row in rows]

    @staticmethod
    def _outcomes(row) -> DeliveryOutcomes:
        return DeliveryOutcomes(
            succeeded=int(row[0]),
            dead_lettered=int(row[1]),
            unavailable=int(row[2]),
            first_attempt=int(row[3]),
            median_seconds=None if row[4] is None else float(row[4]),
        )

    @staticmethod
    def _visible(time_column, window: StatsWindow, scope: AuthorizationScope) -> tuple:
        return (
            time_column >= window.start,
            time_column < window.end,
            *agent_scope_predicates(scope, include_deleted=True),
        )


@dataclass(frozen=True)
class ValueSettingsChangeResult:
    delivery_ids: list[UUID]


def _rate_text(rate: Decimal | None) -> str | None:
    return None if rate is None else str(rate.quantize(RATE_QUANTUM))


def _minutes_text(minutes: int | None) -> str | None:
    return None if minutes is None else str(minutes)


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
        rate_addressed: bool,
        outcome_minutes: dict[str, int | None],
        actor: ActorIdentity,
        actor_display: str,
        subject_display: str,
    ) -> ValueSettingsChangeResult:
        now = datetime.now(UTC)
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            session.exec(self._ensure_settings_statement(organization_id, now))  # type: ignore[call-overload]
            settings = session.exec(
                select(OrganizationValueSettings)
                .where(col(OrganizationValueSettings.organization_id) == organization_id)
                .with_for_update()
            ).one()
            overrides = dict(
                session.exec(
                    select(OrganizationOutcomeMinutes.outcome_type, OrganizationOutcomeMinutes.minutes_saved).where(
                        col(OrganizationOutcomeMinutes.organization_id) == organization_id
                    )
                ).all()
            )

            field_changes: dict[str, dict[str, str | None]] = {}
            if rate_addressed and hourly_rate != settings.hourly_rate_usd:
                field_changes[HOURLY_RATE_FIELD] = {
                    "previous": _rate_text(settings.hourly_rate_usd),
                    "current": _rate_text(hourly_rate),
                }
                settings.hourly_rate_usd = hourly_rate
                settings.updated_at = now
                session.add(settings)
            for outcome_type, minutes in outcome_minutes.items():
                previous = overrides.get(outcome_type)
                if minutes == previous:
                    continue
                field_changes[f"{OUTCOME_MINUTES_FIELD_PREFIX}{outcome_type}"] = {
                    "previous": _minutes_text(previous),
                    "current": _minutes_text(minutes),
                }
                session.exec(self._minute_change_statement(organization_id, outcome_type, minutes, now))  # type: ignore[call-overload]

            if not field_changes:
                session.commit()
                return ValueSettingsChangeResult(delivery_ids=[])
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
    def _ensure_settings_statement(organization_id: UUID, now: datetime):
        return (
            pg_insert(OrganizationValueSettings)
            .values(
                id=uuid.uuid7(),
                created_at=now,
                updated_at=now,
                organization_id=organization_id,
                hourly_rate_usd=None,
            )
            .on_conflict_do_nothing(constraint=VALUE_SETTINGS_ORGANIZATION_CONSTRAINT)
        )

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

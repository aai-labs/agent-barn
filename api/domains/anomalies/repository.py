from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, col, select

from api.domains.anomalies.detection import Verdict
from api.domains.anomalies.models import (
    AgentActivitySeen,
    AgentAnomaly,
    AgentAnomalyOverride,
    AgentAnomalyState,
    AnomalySignal,
    OrganizationAnomalySettings,
    SeenKind,
)
from api.domains.events import ActorIdentity, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import (
    AGENT_ANOMALY_OVERRIDE_CHANGED,
    EVENT_REGISTRY,
    ORGANIZATION_ANOMALY_DETECTION_CHANGED,
)
from api.domains.events.repository import OutboxMessageRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@dataclass(frozen=True)
class OverrideValues:
    sensitivity: str
    max_llm_tokens_per_hour: int | None
    max_llm_calls_per_hour: int | None


@dataclass(frozen=True)
class Actor:
    identity: ActorIdentity
    display: str


@inject
@singleton
@dataclass
class AnomalySettingsRepository:
    """The Organization opt-in and per-Agent overrides, each written with its audit Event."""

    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def get_settings(self, organization_id: UUID) -> OrganizationAnomalySettings | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(OrganizationAnomalySettings).where(
                    col(OrganizationAnomalySettings.organization_id) == organization_id
                )
            ).first()

    def set_enabled_with_event(
        self, organization_id: UUID, enabled: bool, *, actor: Actor, subject_display: str
    ) -> tuple[OrganizationAnomalySettings, list[UUID]]:
        """The opt-in and its change Event, atomically. No Event when nothing changed."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            settings = session.exec(
                select(OrganizationAnomalySettings)
                .where(col(OrganizationAnomalySettings.organization_id) == organization_id)
                .with_for_update()
            ).first()
            previous = settings.enabled if settings is not None else False
            if previous == enabled:
                return settings or OrganizationAnomalySettings(organization_id=organization_id), []
            if settings is None:
                settings = OrganizationAnomalySettings(organization_id=organization_id)
            settings.enabled = enabled
            settings.updated_at = datetime.now(UTC)
            session.add(settings)
            if not enabled:
                # The check stops reading while detection is off. Forgetting how far it
                # got makes it learn the gap when turned back on, rather than flag
                # everything the Agents did meanwhile as a first use.
                session.exec(
                    sa.delete(AgentAnomalyState).where(  # type: ignore[call-overload]
                        col(AgentAnomalyState.organization_id) == organization_id
                    )
                )
            session.flush()
            delivery_ids = self._stage(
                session,
                ORGANIZATION_ANOMALY_DETECTION_CHANGED,
                organization_id=organization_id,
                actor=actor,
                subject=SubjectIdentity(
                    type=SubjectIdentityType.ORGANIZATION, id=organization_id, organization_id=organization_id
                ),
                payload={
                    "organization_id": organization_id,
                    "enabled": enabled,
                    "previous_enabled": previous,
                    "actor_display": actor.display,
                    "subject_display": subject_display,
                },
            )
            session.commit()
            return settings, delivery_ids

    def get_override(self, agent_id: UUID) -> AgentAnomalyOverride | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentAnomalyOverride).where(col(AgentAnomalyOverride.agent_id) == agent_id)
            ).first()

    def set_override_with_event(
        self,
        organization_id: UUID,
        agent_id: UUID,
        values: OverrideValues,
        *,
        actor: Actor,
        subject_display: str,
    ) -> tuple[AgentAnomalyOverride, list[UUID]]:
        """An Agent's override and its change Event, atomically. No Event when nothing changed."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            override = session.exec(
                select(AgentAnomalyOverride).where(col(AgentAnomalyOverride.agent_id) == agent_id).with_for_update()
            ).first()
            if override is None:
                override = AgentAnomalyOverride(organization_id=organization_id, agent_id=agent_id)
            previous = OverrideValues(
                sensitivity=override.sensitivity,
                max_llm_tokens_per_hour=override.max_llm_tokens_per_hour,
                max_llm_calls_per_hour=override.max_llm_calls_per_hour,
            )
            if previous == values:
                return override, []
            override.sensitivity = values.sensitivity
            override.max_llm_tokens_per_hour = values.max_llm_tokens_per_hour
            override.max_llm_calls_per_hour = values.max_llm_calls_per_hour
            override.updated_at = datetime.now(UTC)
            session.add(override)
            session.flush()
            delivery_ids = self._stage(
                session,
                AGENT_ANOMALY_OVERRIDE_CHANGED,
                organization_id=organization_id,
                actor=actor,
                subject=SubjectIdentity(type=SubjectIdentityType.AGENT, id=agent_id, organization_id=organization_id),
                payload={
                    "organization_id": organization_id,
                    "agent_id": agent_id,
                    "sensitivity": values.sensitivity,
                    "previous_sensitivity": previous.sensitivity,
                    "max_llm_usage_per_hour": values.max_llm_tokens_per_hour,
                    "previous_max_llm_usage_per_hour": previous.max_llm_tokens_per_hour,
                    "max_llm_calls_per_hour": values.max_llm_calls_per_hour,
                    "previous_max_llm_calls_per_hour": previous.max_llm_calls_per_hour,
                    "actor_display": actor.display,
                    "subject_display": subject_display,
                },
            )
            session.commit()
            return override, delivery_ids

    def _stage(
        self,
        session: Session,
        event_name: str,
        *,
        organization_id: UUID,
        actor: Actor,
        subject: SubjectIdentity,
        payload: dict,
    ) -> list[UUID]:
        event = EVENT_REGISTRY.build_event(
            event_name=event_name,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor=actor.identity,
            subject=subject,
            correlation_id=uuid4(),
            payload=payload,
        )
        self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
        return list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))


@dataclass(frozen=True)
class SeenUse:
    """One tool, integration, action or host an Agent used, and when."""

    kind: SeenKind
    subject: str
    first_at: datetime
    last_at: datetime


@inject
@singleton
@dataclass
class AnomalyRepository:
    """What the scheduled check reads and records.

    Unscoped: the check is background work with no caller, and no router reaches the
    writes. It takes each Organization and Agent from persisted rows, never from input.
    """

    delegate: PostgresRepositoryDelegate

    def enabled_organization_ids(self) -> list[UUID]:
        with Session(self.delegate.engine) as session:
            query = select(col(OrganizationAnomalySettings.organization_id)).where(
                col(OrganizationAnomalySettings.enabled).is_(True)
            )
            return list(session.exec(query).all())

    def get_state(self, agent_id: UUID) -> AgentAnomalyState | None:
        with Session(self.delegate.engine) as session:
            return session.exec(select(AgentAnomalyState).where(col(AgentAnomalyState.agent_id) == agent_id)).first()

    def save_state(
        self,
        organization_id: UUID,
        agent_id: UUID,
        *,
        tool_calls_read_through: datetime,
        business_actions_read_through: datetime,
    ) -> None:
        now = datetime.now(UTC)
        statement = pg_insert(AgentAnomalyState).values(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            organization_id=organization_id,
            agent_id=agent_id,
            tool_calls_read_through=tool_calls_read_through,
            business_actions_read_through=business_actions_read_through,
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_agent_anomaly_state_agent_id",
            set_={
                "tool_calls_read_through": statement.excluded.tool_calls_read_through,
                "business_actions_read_through": statement.excluded.business_actions_read_through,
                "updated_at": now,
            },
        )
        with Session(self.delegate.engine) as session:
            session.exec(statement)  # type: ignore[call-overload]
            session.commit()

    def last_seen(self, agent_id: UUID, kind: SeenKind, subjects: Collection[str]) -> dict[str, datetime]:
        if not subjects:
            return {}
        with Session(self.delegate.engine) as session:
            query = select(col(AgentActivitySeen.subject), col(AgentActivitySeen.last_seen_at)).where(
                col(AgentActivitySeen.agent_id) == agent_id,
                col(AgentActivitySeen.kind) == kind.value,
                col(AgentActivitySeen.subject).in_(list(subjects)),
            )
            return dict(session.exec(query).all())  # type: ignore[arg-type]

    def mark_seen(self, organization_id: UUID, agent_id: UUID, uses: list[SeenUse]) -> None:
        """Record uses, keeping the earliest first use and the latest last use."""
        if not uses:
            return
        now = datetime.now(UTC)
        statement = pg_insert(AgentActivitySeen).values(
            [
                {
                    "id": uuid4(),
                    "created_at": now,
                    "updated_at": now,
                    "organization_id": organization_id,
                    "agent_id": agent_id,
                    "kind": use.kind.value,
                    "subject": use.subject,
                    "first_seen_at": use.first_at,
                    "last_seen_at": use.last_at,
                }
                for use in uses
            ]
        )
        table = AgentActivitySeen.__table__  # type: ignore[attr-defined]
        statement = statement.on_conflict_do_update(
            constraint="uq_agent_activity_seen_agent_kind_subject",
            set_={
                "first_seen_at": sa.func.least(table.c.first_seen_at, statement.excluded.first_seen_at),
                "last_seen_at": sa.func.greatest(table.c.last_seen_at, statement.excluded.last_seen_at),
                "updated_at": now,
            },
        )
        with Session(self.delegate.engine) as session:
            session.exec(statement)  # type: ignore[call-overload]
            session.commit()

    def seen_since(self, agent_id: UUID, since: datetime) -> list[AgentActivitySeen]:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentActivitySeen)
                .where(col(AgentActivitySeen.agent_id) == agent_id, col(AgentActivitySeen.last_seen_at) >= since)
                .order_by(col(AgentActivitySeen.kind), col(AgentActivitySeen.subject))
            )
            return list(session.exec(query).all())

    def open_or_update(
        self, organization_id: UUID, agent_id: UUID, signal: AnomalySignal, verdict: Verdict, at: datetime
    ) -> None:
        """Start an Anomaly for `signal`, or bring the ongoing one up to date.

        The observed value keeps the highest seen, so the record shows how far the
        deviation went; the usual value and threshold follow the latest check.
        """
        with Session(self.delegate.engine) as session:
            ongoing = session.exec(
                select(AgentAnomaly)
                .where(
                    col(AgentAnomaly.agent_id) == agent_id,
                    col(AgentAnomaly.signal) == signal.value,
                    col(AgentAnomaly.subject).is_(None),
                    col(AgentAnomaly.ended_at).is_(None),
                )
                .with_for_update()
            ).first()
            if ongoing is None:
                ongoing = AgentAnomaly(
                    organization_id=organization_id,
                    agent_id=agent_id,
                    signal=signal.value,
                    observed_value=verdict.observed,
                    started_at=at,
                    last_observed_at=at,
                )
            ongoing.observed_value = max(ongoing.observed_value, verdict.observed)
            ongoing.usual_value = verdict.usual
            ongoing.threshold = verdict.threshold
            ongoing.last_observed_at = at
            ongoing.updated_at = datetime.now(UTC)
            session.add(ongoing)
            session.commit()

    def end_ongoing(self, agent_id: UUID, signal: AnomalySignal, at: datetime) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(AgentAnomaly)  # type: ignore[call-overload]
                .where(
                    col(AgentAnomaly.agent_id) == agent_id,
                    col(AgentAnomaly.signal) == signal.value,
                    col(AgentAnomaly.ended_at).is_(None),
                )
                .values(ended_at=at, updated_at=datetime.now(UTC))
            )
            session.commit()

    def record_first_use(
        self, organization_id: UUID, agent_id: UUID, signal: AnomalySignal, subject: str, at: datetime, uses: int
    ) -> None:
        """A first use is a moment, not a stretch of time: it starts and ends at once."""
        with Session(self.delegate.engine) as session:
            session.add(
                AgentAnomaly(
                    organization_id=organization_id,
                    agent_id=agent_id,
                    signal=signal.value,
                    subject=subject,
                    observed_value=uses,
                    started_at=at,
                    last_observed_at=at,
                    ended_at=at,
                )
            )
            session.commit()

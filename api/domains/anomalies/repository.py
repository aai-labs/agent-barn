from collections.abc import Collection, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, SQLModel, col, select

from api.domains.anomalies.detection import Verdict
from api.domains.anomalies.models import (
    AgentActivitySeen,
    AgentAnomaly,
    AgentAnomalyOverride,
    AgentAnomalyState,
    AnomalySignal,
    ClassificationState,
    OrganizationAnomalySettings,
    SeenKind,
)
from api.domains.events import (
    ActorIdentity,
    ActorIdentityType,
    EventDelivery,
    SubjectIdentity,
    SubjectIdentityType,
)
from api.domains.events.catalog import (
    AGENT_ANOMALY_FLAGGED,
    AGENT_ANOMALY_OVERRIDE_CHANGED,
    EVENT_REGISTRY,
    ORGANIZATION_ANOMALY_DETECTION_CHANGED,
)
from api.domains.events.repository import OutboxMessageRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import Pagination


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
            now = datetime.now(UTC)
            settings.enabled = enabled
            settings.updated_at = now
            session.add(settings)
            if not enabled:
                # Nothing watches an ongoing Anomaly once detection is off, so it ends
                # now; a deviation still going when it is back on starts a new one.
                session.exec(
                    sa.update(AgentAnomaly)  # type: ignore[call-overload]
                    .where(
                        col(AgentAnomaly.organization_id) == organization_id,
                        col(AgentAnomaly.ended_at).is_(None),
                    )
                    .values(ended_at=now, updated_at=now)
                )
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
    outbox_repository: OutboxMessageRepository

    def enabled_organization_ids(self) -> list[UUID]:
        with Session(self.delegate.engine) as session:
            query = select(col(OrganizationAnomalySettings.organization_id)).where(
                col(OrganizationAnomalySettings.enabled).is_(True)
            )
            return list(session.exec(query).all())

    def detection_version(self, organization_id: UUID) -> datetime | None:
        """When the Organization's detection setting last changed, while it is on;
        None while it is off. A check records what it found only if this has not
        changed since it started (`check_writes`)."""
        with Session(self.delegate.engine) as session:
            settings = session.exec(
                select(OrganizationAnomalySettings).where(
                    col(OrganizationAnomalySettings.organization_id) == organization_id
                )
            ).first()
        return settings.updated_at if settings is not None and settings.enabled else None

    @contextmanager
    def check_writes(self, organization_id: UUID, agent_id: UUID, version: datetime) -> Iterator[CheckWrites | None]:
        """One transaction for everything a check of one Agent records, or None when
        detection was turned off (or off and on again) since the check started.

        The Organization's settings row stays share-locked until the transaction ends.
        Turning detection off locks it for update, so the two never interleave: a check
        cannot reopen what turning off ended, or bring back the progress it forgot.
        """
        with Session(self.delegate.engine) as session:
            settings = session.exec(
                select(OrganizationAnomalySettings)
                .where(col(OrganizationAnomalySettings.organization_id) == organization_id)
                .with_for_update(read=True)
            ).first()
            if settings is None or not settings.enabled or settings.updated_at != version:
                yield None
                return
            yield CheckWrites(session, organization_id, agent_id, self.outbox_repository)
            session.commit()

    def get_state(self, agent_id: UUID) -> AgentAnomalyState | None:
        with Session(self.delegate.engine) as session:
            return session.exec(select(AgentAnomalyState).where(col(AgentAnomalyState.agent_id) == agent_id)).first()

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

    def list_anomalies(self, agent_id: UUID, pagination: Pagination) -> tuple[list[AgentAnomaly], int]:
        """One Agent's Anomalies, most recently started first. The caller has already
        authorized the Agent."""
        with Session(self.delegate.engine) as session:
            total = session.exec(
                select(sa.func.count()).select_from(AgentAnomaly).where(col(AgentAnomaly.agent_id) == agent_id)
            ).one()
            items = session.exec(
                select(AgentAnomaly)
                .where(col(AgentAnomaly.agent_id) == agent_id)
                .order_by(col(AgentAnomaly.started_at).desc(), col(AgentAnomaly.id).desc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            ).all()
            return list(items), int(total)

    def seen_since(self, agent_id: UUID, since: datetime) -> list[AgentActivitySeen]:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentActivitySeen)
                .where(col(AgentActivitySeen.agent_id) == agent_id, col(AgentActivitySeen.last_seen_at) >= since)
                .order_by(col(AgentActivitySeen.kind), col(AgentActivitySeen.subject))
            )
            return list(session.exec(query).all())

    def end_ongoing_except(self, organization_id: UUID, agent_ids: Collection[UUID], at: datetime) -> None:
        """End the ongoing Anomalies of an Organization's Agents other than `agent_ids`
        (the ones still checked), such as Agents deleted since the last check."""
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(AgentAnomaly)  # type: ignore[call-overload]
                .where(
                    col(AgentAnomaly.organization_id) == organization_id,
                    col(AgentAnomaly.agent_id).not_in(list(agent_ids)),
                    col(AgentAnomaly.ended_at).is_(None),
                )
                .values(ended_at=at, updated_at=datetime.now(UTC))
            )
            session.commit()

    def get_anomalies(self, anomaly_ids: Collection[UUID]) -> list[AgentAnomaly]:
        """The given Anomalies, oldest first."""
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentAnomaly)
                .where(col(AgentAnomaly.id).in_(list(anomaly_ids)))
                .order_by(col(AgentAnomaly.started_at), col(AgentAnomaly.id))
            )
            return list(session.exec(query).all())

    def ongoing_signals(self, agent_id: UUID, *, excluding: Collection[UUID]) -> list[AnomalySignal]:
        """The signals of an Agent's ongoing Anomalies other than `excluding`, each once."""
        with Session(self.delegate.engine) as session:
            signals = session.exec(
                select(AgentAnomaly.signal)
                .where(
                    col(AgentAnomaly.agent_id) == agent_id,
                    col(AgentAnomaly.ended_at).is_(None),
                    col(AgentAnomaly.id).not_in(list(excluding)),
                )
                .distinct()
                .order_by(col(AgentAnomaly.signal))
            ).all()
            return [AnomalySignal(signal) for signal in signals]

    def set_classification(self, anomaly_id: UUID, category: str, severity: float, details: dict[str, Any]) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(AgentAnomaly)  # type: ignore[call-overload]
                .where(col(AgentAnomaly.id) == anomaly_id)
                .values(
                    classification_state=ClassificationState.CLASSIFIED.value,
                    classification_category=category,
                    classification_severity=severity,
                    classification=details,
                    updated_at=datetime.now(UTC),
                )
            )
            session.commit()


@dataclass
class CheckWrites:
    """What one check of one Agent records. Nothing is committed until the check has
    recorded everything (`AnomalyRepository.check_writes`), so a check that fails part
    way leaves no trace and its retry records each Anomaly once."""

    session: Session
    organization_id: UUID
    agent_id: UUID
    outbox_repository: OutboxMessageRepository

    def record_flagged(self, anomaly_ids: list[UUID]) -> list[UUID]:
        """The alert Event for the Anomalies this check started, recorded with them so a
        crash after the commit cannot lose it. Returns its delivery ids, which the check
        enqueues once it has classified them; until then the deliveries wait, and
        reconciliation sends them if the check never gets that far."""
        event = EVENT_REGISTRY.build_event(
            event_name=AGENT_ANOMALY_FLAGGED,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=self.organization_id,
            actor=ActorIdentity(type=ActorIdentityType.SYSTEM, id="anomaly-checks"),
            subject=SubjectIdentity(
                type=SubjectIdentityType.AGENT, id=self.agent_id, organization_id=self.organization_id
            ),
            correlation_id=uuid4(),
            payload={"organization_id": self.organization_id, "agent_id": self.agent_id, "anomaly_ids": anomaly_ids},
        )
        self.outbox_repository.stage(session=self.session, registry=EVENT_REGISTRY, event=event)
        return self.outbox_repository.delivery_ids_for_event(self.session, event.event_id)

    def open_or_update(self, signal: AnomalySignal, verdict: Verdict, at: datetime) -> UUID | None:
        """Start an Anomaly for `signal`, or bring the ongoing one up to date. Returns
        the new Anomaly's id when one started, None when an ongoing one was updated.

        The observed value keeps the highest seen, so the record shows how far the
        deviation went; the usual value and threshold follow the latest check.
        """
        ongoing = self.session.exec(
            select(AgentAnomaly)
            .where(
                col(AgentAnomaly.agent_id) == self.agent_id,
                col(AgentAnomaly.signal) == signal.value,
                col(AgentAnomaly.subject).is_(None),
                col(AgentAnomaly.ended_at).is_(None),
            )
            .with_for_update()
        ).first()
        started = ongoing is None
        if ongoing is None:
            ongoing = AgentAnomaly(
                organization_id=self.organization_id,
                agent_id=self.agent_id,
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
        self.session.add(ongoing)
        self.session.flush()
        return ongoing.id if started else None

    def end_ongoing(self, signal: AnomalySignal, at: datetime) -> None:
        self.session.exec(
            sa.update(AgentAnomaly)  # type: ignore[call-overload]
            .where(
                col(AgentAnomaly.agent_id) == self.agent_id,
                col(AgentAnomaly.signal) == signal.value,
                col(AgentAnomaly.ended_at).is_(None),
            )
            .values(ended_at=at, updated_at=datetime.now(UTC))
        )

    def record_first_use(self, signal: AnomalySignal, subject: str, at: datetime, uses: int) -> UUID:
        """A first use is a moment, not a stretch of time: it starts and ends at once."""
        anomaly = AgentAnomaly(
            organization_id=self.organization_id,
            agent_id=self.agent_id,
            signal=signal.value,
            subject=subject,
            observed_value=uses,
            started_at=at,
            last_observed_at=at,
            ended_at=at,
        )
        self.session.add(anomaly)
        self.session.flush()
        return anomaly.id

    def mark_seen(self, uses: list[SeenUse]) -> None:
        """Record uses (one per kind and subject), keeping the earliest first use and
        the latest last use."""
        if not uses:
            return
        now = datetime.now(UTC)
        statement = pg_insert(AgentActivitySeen).values(
            [
                {
                    "id": uuid4(),
                    "created_at": now,
                    "updated_at": now,
                    "organization_id": self.organization_id,
                    "agent_id": self.agent_id,
                    "kind": use.kind.value,
                    "subject": use.subject,
                    "first_seen_at": use.first_at,
                    "last_seen_at": use.last_at,
                }
                for use in uses
            ]
        )
        table = SQLModel.metadata.tables[AgentActivitySeen.__tablename__]
        statement = statement.on_conflict_do_update(
            constraint="uq_agent_activity_seen_agent_kind_subject",
            set_={
                "first_seen_at": sa.func.least(table.c.first_seen_at, statement.excluded.first_seen_at),
                "last_seen_at": sa.func.greatest(table.c.last_seen_at, statement.excluded.last_seen_at),
                "updated_at": now,
            },
        )
        self.session.exec(statement)  # type: ignore[call-overload]

    def save_state(self, *, tool_calls_read_through: datetime, business_actions_read_through: datetime) -> None:
        now = datetime.now(UTC)
        statement = pg_insert(AgentAnomalyState).values(
            id=uuid4(),
            created_at=now,
            updated_at=now,
            organization_id=self.organization_id,
            agent_id=self.agent_id,
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
        self.session.exec(statement)  # type: ignore[call-overload]

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.anomalies.models import AgentAnomalyOverride, OrganizationAnomalySettings
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

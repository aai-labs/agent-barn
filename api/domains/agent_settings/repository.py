from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.agent_settings.models import (
    DEFAULT_MODEL_SETTING,
    OrganizationAgentSettings,
)
from api.domains.events import ActorIdentity, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import EVENT_REGISTRY, ORGANIZATION_AGENT_SETTINGS_CHANGED
from api.domains.events.repository import OutboxMessageRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@dataclass(frozen=True)
class AgentSettingsChangeResult:
    settings: OrganizationAgentSettings
    delivery_ids: list[UUID]


@inject
@singleton
@dataclass
class AgentSettingsRepository:
    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def get_for_org(self, organization_id: UUID) -> OrganizationAgentSettings | None:
        with Session(self.delegate.engine) as session:
            query = select(OrganizationAgentSettings).where(
                col(OrganizationAgentSettings.organization_id) == organization_id
            )
            return session.exec(query).first()

    def set_default_model_with_event(
        self,
        organization_id: UUID,
        default_model: str | None,
        *,
        previous: str | None,
        inheriting_agent_count: int,
        actor: ActorIdentity,
        actor_display: str,
        subject_display: str,
        correlation_id: UUID | None = None,
    ) -> AgentSettingsChangeResult:
        """Persists the default model and stages its change Event atomically.

        The settings row, the Outbox Message and its Event Deliveries share one
        session and one commit, so a settings change can never be visible without
        its audit record. The row is created here on first write; callers read a
        missing row as "follows the platform default".
        """
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            settings = session.exec(
                select(OrganizationAgentSettings).where(
                    col(OrganizationAgentSettings.organization_id) == organization_id
                )
            ).first()
            if settings is None:
                settings = OrganizationAgentSettings(organization_id=organization_id)
            settings.default_model = default_model
            settings.updated_at = datetime.now(UTC)
            session.add(settings)
            session.flush()

            event = EVENT_REGISTRY.build_event(
                event_name=ORGANIZATION_AGENT_SETTINGS_CHANGED,
                schema_version=1,
                occurred_at=datetime.now(UTC),
                organization_id=organization_id,
                actor=actor,
                subject=SubjectIdentity(
                    type=SubjectIdentityType.ORGANIZATION,
                    id=organization_id,
                    organization_id=organization_id,
                ),
                correlation_id=correlation_id or uuid4(),
                payload={
                    "organization_id": organization_id,
                    "setting": DEFAULT_MODEL_SETTING,
                    "previous": previous,
                    "current": default_model,
                    "inheriting_agent_count": inheriting_agent_count,
                    "actor_display": actor_display,
                    "subject_display": subject_display,
                },
            )
            self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
            delivery_ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            session.refresh(settings)
            return AgentSettingsChangeResult(settings=settings, delivery_ids=delivery_ids)

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, select

from api.domains.decisions.models import PlatformDecisionSettings, PlatformDecisionSettingsRead
from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import EVENT_REGISTRY, PLATFORM_DECISION_MODEL_CHANGED
from api.domains.events.repository import OutboxMessageRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class PlatformDecisionRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def read(self, default_model: str) -> PlatformDecisionSettingsRead:
        with Session(self.delegate.engine) as session:
            row = session.get(PlatformDecisionSettings, 1)
            return (
                PlatformDecisionSettingsRead(model=row.model, updated_at=row.updated_at)
                if row
                else PlatformDecisionSettingsRead(model=default_model)
            )

    def set_model(
        self, model: str, default_model: str, actor_id: UUID, actor_display: str
    ) -> tuple[PlatformDecisionSettingsRead, list[UUID]]:
        """Persist the choice and its audit event; saving the current choice records nothing."""
        with Session(self.delegate.engine) as session:
            # Serializes global changes, including creation of the singleton row.
            session.connection().execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "platform-decision-settings"},
            )
            row = session.get(PlatformDecisionSettings, 1)
            previous = row.model if row else default_model
            if row and previous == model:
                return PlatformDecisionSettingsRead(model=row.model, updated_at=row.updated_at), []
            now = datetime.now(UTC)
            session.merge(PlatformDecisionSettings(id=1, model=model, updated_at=now, updated_by=actor_id))
            event = EVENT_REGISTRY.build_event(
                event_name=PLATFORM_DECISION_MODEL_CHANGED,
                schema_version=1,
                occurred_at=now,
                organization_id=None,
                actor=ActorIdentity(type=ActorIdentityType.USER, id=actor_id),
                subject=SubjectIdentity(type=SubjectIdentityType.SYSTEM, id="platform-decisions"),
                correlation_id=uuid4(),
                payload={
                    "previous": previous,
                    "current": model,
                    "actor_display": actor_display,
                    "subject_display": "Decisions",
                },
            )
            self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
            ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return PlatformDecisionSettingsRead(model=model, updated_at=now), ids

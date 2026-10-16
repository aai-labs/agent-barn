from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, select

from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import EVENT_REGISTRY, PLATFORM_PLAYBOOK_MODEL_CHANGED
from api.domains.events.repository import OutboxMessageRepository
from api.domains.playbooks.platform_models import PlatformPlaybookSettings, PlatformPlaybookSettingsRead
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class PlatformPlaybookRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def read(self, default_model: str) -> PlatformPlaybookSettingsRead:
        with Session(self.delegate.engine) as session:
            row = session.get(PlatformPlaybookSettings, 1)
            return (
                PlatformPlaybookSettingsRead(model=row.model, updated_at=row.updated_at)
                if row
                else PlatformPlaybookSettingsRead(model=default_model)
            )

    def set_model(
        self, model: str, default_model: str, actor_id: UUID, actor_display: str
    ) -> tuple[PlatformPlaybookSettingsRead, list[UUID]]:
        """Persist the choice and its audit event; saving the current choice records nothing."""
        with Session(self.delegate.engine) as session:
            # Serializes global changes, including creation of the singleton row.
            session.connection().execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": "platform-playbook-settings"},
            )
            row = session.get(PlatformPlaybookSettings, 1)
            previous = row.model if row else default_model
            if row and previous == model:
                return PlatformPlaybookSettingsRead(model=row.model, updated_at=row.updated_at), []
            now = datetime.now(UTC)
            session.merge(PlatformPlaybookSettings(id=1, model=model, updated_at=now, updated_by=actor_id))
            event = EVENT_REGISTRY.build_event(
                event_name=PLATFORM_PLAYBOOK_MODEL_CHANGED,
                schema_version=1,
                occurred_at=now,
                organization_id=None,
                actor=ActorIdentity(type=ActorIdentityType.USER, id=actor_id),
                subject=SubjectIdentity(type=SubjectIdentityType.SYSTEM, id="platform-playbooks"),
                correlation_id=uuid4(),
                payload={
                    "previous": previous,
                    "current": model,
                    "actor_display": actor_display,
                    "subject_display": "Playbooks",
                },
            )
            self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
            ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return PlatformPlaybookSettingsRead(model=model, updated_at=now), ids

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, select

from api.domains.agent_memory.platform_models import PlatformMemorySettings, PlatformMemorySettingsRead
from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import EVENT_REGISTRY, PLATFORM_MEMORY_MODEL_CHANGED
from api.domains.events.repository import OutboxMessageRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class PlatformMemoryRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def read(self, default_model: str) -> PlatformMemorySettingsRead:
        with Session(self.delegate.engine) as session:
            row = session.get(PlatformMemorySettings, 1)
            return (
                PlatformMemorySettingsRead(model=row.model, updated_at=row.updated_at)
                if row
                else PlatformMemorySettingsRead(model=default_model)
            )

    def set_model(
        self, model: str, default_model: str, actor_id: UUID, actor_display: str, prepare: Callable[[str], None]
    ) -> tuple[PlatformMemorySettingsRead, list[UUID]]:
        with Session(self.delegate.engine) as session:
            # Serializes global changes, including creation of the singleton row.
            session.connection().execute(sa.text("SELECT pg_advisory_xact_lock(732914105)"))
            row = session.get(PlatformMemorySettings, 1)
            previous = row.model if row else default_model
            # Keep the bounded LiteLLM requests under this lock so concurrent admin
            # saves cannot lose allowlist additions or persist an unusable choice.
            prepare(previous)
            if row and previous == model:
                return PlatformMemorySettingsRead(model=row.model, updated_at=row.updated_at), []
            now = datetime.now(UTC)
            row = PlatformMemorySettings(id=1, model=model, updated_at=now, updated_by=actor_id)
            session.merge(row)
            event = EVENT_REGISTRY.build_event(
                event_name=PLATFORM_MEMORY_MODEL_CHANGED,
                schema_version=1,
                occurred_at=now,
                organization_id=None,
                actor=ActorIdentity(type=ActorIdentityType.USER, id=actor_id),
                subject=SubjectIdentity(type=SubjectIdentityType.SYSTEM, id="platform-memory"),
                correlation_id=uuid4(),
                payload={
                    "previous": previous,
                    "current": model,
                    "actor_display": actor_display,
                    "subject_display": "Agent Memory",
                },
            )
            self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
            ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return PlatformMemorySettingsRead(model=model, updated_at=now), ids

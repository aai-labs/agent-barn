from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, select

from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import EVENT_REGISTRY, PLATFORM_WORKFLOW_AUTHORING_CHANGED
from api.domains.events.repository import OutboxMessageRepository
from api.domains.workflows.platform_models import PlatformWorkflowSettings, PlatformWorkflowSettingsRead
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class PlatformWorkflowRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def read(self, default_enabled: bool) -> PlatformWorkflowSettingsRead:
        with Session(self.delegate.engine) as session:
            row = session.get(PlatformWorkflowSettings, 1)
            return (
                PlatformWorkflowSettingsRead(authoring_enabled=row.authoring_enabled, updated_at=row.updated_at)
                if row
                else PlatformWorkflowSettingsRead(authoring_enabled=default_enabled)
            )

    def set_authoring(
        self, enabled: bool, default_enabled: bool, actor_id: UUID, actor_display: str
    ) -> tuple[PlatformWorkflowSettingsRead, list[UUID]]:
        with Session(self.delegate.engine) as session:
            # Serialize updates even before the singleton row exists.
            session.connection().execute(sa.text("SELECT pg_advisory_xact_lock(732914106)"))
            row = session.get(PlatformWorkflowSettings, 1)
            previous = row.authoring_enabled if row else default_enabled
            if row and previous == enabled:
                return PlatformWorkflowSettingsRead(authoring_enabled=enabled, updated_at=row.updated_at), []
            now = datetime.now(UTC)
            session.merge(
                PlatformWorkflowSettings(id=1, authoring_enabled=enabled, updated_at=now, updated_by=actor_id)
            )
            ids = []
            if previous != enabled:
                event = EVENT_REGISTRY.build_event(
                    event_name=PLATFORM_WORKFLOW_AUTHORING_CHANGED,
                    schema_version=1,
                    occurred_at=now,
                    organization_id=None,
                    actor=ActorIdentity(type=ActorIdentityType.USER, id=actor_id),
                    subject=SubjectIdentity(type=SubjectIdentityType.SYSTEM, id="platform-workflows"),
                    correlation_id=uuid4(),
                    payload={
                        "previous": previous,
                        "current": enabled,
                        "actor_display": actor_display,
                        "subject_display": "Workflow authoring",
                    },
                )
                self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
                ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return PlatformWorkflowSettingsRead(authoring_enabled=enabled, updated_at=now), ids

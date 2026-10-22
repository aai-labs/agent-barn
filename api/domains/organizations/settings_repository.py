from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import EVENT_REGISTRY, PLATFORM_ORGANIZATION_SETTINGS_CHANGED
from api.domains.events.models import EventScope
from api.domains.events.repository import OutboxMessageRepository
from api.domains.organizations.models import (
    ORGANIZATION_SETTINGS_SUBJECT_DISPLAY,
    OrganizationSettingsRead,
    PlatformOrganizationSettings,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

# Serializes Organization settings changes, including creation of the singleton row.
_ORGANIZATION_SETTINGS_LOCK = 732914109


@inject
@singleton
@dataclass
class OrganizationSettingsRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def read(self, default_agent_limit: int) -> OrganizationSettingsRead:
        with Session(self.delegate.engine) as session:
            return self._current(session.get(PlatformOrganizationSettings, 1), default_agent_limit)

    @staticmethod
    def _current(row: PlatformOrganizationSettings | None, default_agent_limit: int) -> OrganizationSettingsRead:
        if row is None:
            return OrganizationSettingsRead(default_agent_limit=default_agent_limit)
        return OrganizationSettingsRead(default_agent_limit=row.default_agent_limit, updated_at=row.updated_at)

    def set_settings(
        self, changes: dict[str, int], default_agent_limit: int, actor_id: UUID, actor_display: str
    ) -> tuple[OrganizationSettingsRead, list[UUID]]:
        """Store the settings and stage one audit Event per setting that moved, in one
        commit. A setting saved at the value already in force writes nothing."""
        with Session(self.delegate.engine) as session:
            session.connection().execute(sa.text(f"SELECT pg_advisory_xact_lock({_ORGANIZATION_SETTINGS_LOCK})"))
            row = session.get(PlatformOrganizationSettings, 1)
            current = self._current(row, default_agent_limit)
            moved = [
                (setting, getattr(current, setting), value)
                for setting, value in changes.items()
                if getattr(current, setting) != value
            ]
            if row and not moved:
                return current, []
            now = datetime.now(UTC)
            stored = current.model_copy(update={**changes, "updated_at": now})
            session.merge(
                PlatformOrganizationSettings(
                    id=1, default_agent_limit=stored.default_agent_limit, updated_at=now, updated_by=actor_id
                )
            )
            correlation_id = uuid4()
            event_ids = []
            for setting, previous, value in moved:
                event = EVENT_REGISTRY.build_event(
                    event_name=PLATFORM_ORGANIZATION_SETTINGS_CHANGED,
                    schema_version=1,
                    occurred_at=now,
                    event_scope=EventScope.PLATFORM,
                    organization_id=None,
                    actor=ActorIdentity(type=ActorIdentityType.USER, id=actor_id),
                    subject=SubjectIdentity(type=SubjectIdentityType.SYSTEM, id="platform-organization-settings"),
                    correlation_id=correlation_id,
                    payload={
                        "actor_user_id": actor_id,
                        "actor_display": actor_display,
                        "subject_display": ORGANIZATION_SETTINGS_SUBJECT_DISPLAY,
                        "setting": setting,
                        "previous": float(previous),
                        "current": float(value),
                    },
                )
                self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
                event_ids.append(event.event_id)
            ids = list(session.exec(select(EventDelivery.id).where(col(EventDelivery.event_id).in_(event_ids))))
            session.commit()
            return stored, ids

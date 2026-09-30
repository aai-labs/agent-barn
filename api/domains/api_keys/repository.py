from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.api_keys.models import ApiKey
from api.domains.events.catalog import API_KEY_CREATED, API_KEY_REVOKED, EVENT_REGISTRY
from api.domains.events.models import (
    ActorIdentity,
    ActorIdentityType,
    EventDelivery,
    EventScope,
    SubjectIdentity,
    SubjectIdentityType,
)
from api.domains.events.repository import OutboxMessageRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class ApiKeyRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def _stage_event(
        self, session: Session, key: ApiKey, actor_user_id: UUID, actor_display: str, event_name: str
    ) -> list[UUID]:
        event = EVENT_REGISTRY.build_event(
            event_name=event_name,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=None,
            event_scope=EventScope.PLATFORM,
            actor=ActorIdentity(type=ActorIdentityType.USER, id=actor_user_id),
            subject=SubjectIdentity(type=SubjectIdentityType.USER, id=key.user_id),
            correlation_id=uuid4(),
            payload={
                "user_id": key.user_id,
                "key_record_id": key.id,
                "access_mode": key.access_mode.value,
                "actor_display": actor_display,
                "subject_display": actor_display,
            },
        )
        self.outbox.stage(session=session, event=event, registry=EVENT_REGISTRY)
        return list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))

    def get_by_hash(self, token_hash: str) -> ApiKey | None:
        return self.delegate.find_one(ApiKey, token_hash=token_hash)

    def list_by_user(self, user_id: UUID) -> list[ApiKey]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(select(ApiKey).where(ApiKey.user_id == user_id).order_by(col(ApiKey.created_at).desc()))
            )

    def create(self, key: ApiKey, actor_user_id: UUID, actor_display: str) -> list[UUID]:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            session.add(key)
            session.flush()
            delivery_ids = self._stage_event(session, key, actor_user_id, actor_display, API_KEY_CREATED)
            session.commit()
            return delivery_ids

    def revoke_owned(
        self, user_id: UUID, key_id: UUID, now: datetime, actor_display: str
    ) -> tuple[ApiKey | None, list[UUID]]:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            key = session.exec(
                select(ApiKey).where(ApiKey.id == key_id, ApiKey.user_id == user_id).with_for_update()
            ).one_or_none()
            if key is None:
                return None, []
            delivery_ids = []
            if key.revoked_at is None:
                key.revoked_at = now
                session.add(key)
                delivery_ids = self._stage_event(session, key, user_id, actor_display, API_KEY_REVOKED)
                session.commit()
            return key, delivery_ids

    def touch_last_used(self, key_id: UUID, now: datetime) -> None:
        with Session(self.delegate.engine) as session:
            key = session.get(ApiKey, key_id)
            if key is not None and key.revoked_at is None:
                key.last_used_at = now
                session.add(key)
                session.commit()

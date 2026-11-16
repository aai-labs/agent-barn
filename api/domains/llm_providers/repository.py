from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import EVENT_REGISTRY, PLATFORM_LLM_PROVIDER_CHANGED
from api.domains.events.repository import OutboxMessageRepository
from api.domains.llm_providers.models import LlmProviderConnection
from api.domains.users.models import User
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class ConnectionNotFound(LookupError):
    pass


@inject
@singleton
@dataclass
class LlmProviderRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def find_active(self, slug: str) -> tuple[LlmProviderConnection, str | None] | None:
        """The connection, and the name of whoever last changed it."""
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(LlmProviderConnection, User.full_name, User.email)
                .outerjoin(User, col(User.id) == col(LlmProviderConnection.updated_by))
                .where(LlmProviderConnection.slug == slug, col(LlmProviderConnection.deleted_at).is_(None))
            ).first()
        if row is None:
            return None
        connection, full_name, email = row
        return connection, full_name or email

    def replace_key(
        self,
        slug: str,
        api_key_encrypted: str,
        api_key_last4: str,
        actor_id: UUID,
        actor_display: str,
        apply: Callable[[], None],
    ) -> list[UUID]:
        """Store a new key, calling `apply` first under the connection's lock.

        `apply` pushes the key to LiteLLM; if it raises, nothing is stored.
        """
        with Session(self.delegate.engine) as session:
            session.connection().execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"llm_provider_connection:{slug}"},
            )
            connection = session.exec(
                select(LlmProviderConnection).where(
                    LlmProviderConnection.slug == slug, col(LlmProviderConnection.deleted_at).is_(None)
                )
            ).one_or_none()
            if connection is None:
                raise ConnectionNotFound(slug)
            replaced_existing = connection.api_key_encrypted is not None
            apply()
            now = datetime.now(UTC)
            connection.api_key_encrypted = api_key_encrypted
            connection.api_key_last4 = api_key_last4
            connection.updated_by = actor_id
            connection.updated_at = now
            session.add(connection)
            event = EVENT_REGISTRY.build_event(
                event_name=PLATFORM_LLM_PROVIDER_CHANGED,
                schema_version=1,
                occurred_at=now,
                organization_id=None,
                actor=ActorIdentity(type=ActorIdentityType.USER, id=actor_id),
                subject=SubjectIdentity(type=SubjectIdentityType.SYSTEM, id=str(connection.id)),
                correlation_id=uuid4(),
                payload={
                    "connection_id": connection.id,
                    "slug": connection.slug,
                    "replaced_existing": replaced_existing,
                    "actor_display": actor_display,
                    "subject_display": connection.name,
                },
            )
            self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
            ids = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
            session.commit()
            return ids

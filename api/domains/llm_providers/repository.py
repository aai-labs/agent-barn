from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import (
    EVENT_REGISTRY,
    PLATFORM_LLM_PROVIDER_CHANGED,
    PLATFORM_LLM_PROVIDER_CREATED,
    PLATFORM_LLM_PROVIDER_DELETED,
)
from api.domains.events.repository import OutboxMessageRepository
from api.domains.llm_providers.models import (
    BASE_URL_PROVIDER_TYPES,
    OPENROUTER_SLUG,
    LlmProviderConnection,
    LlmProviderModel,
    ProviderType,
)
from api.domains.users.models import User
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class ConnectionNotFound(LookupError):
    pass


class ConnectionAlreadyExists(Exception):
    pass


class ConnectionChanged(Exception):
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

    def list_active(self) -> list[tuple[LlmProviderConnection, str | None]]:
        """Every connection not deleted, OpenRouter first and then by name, each with the name of
        whoever last changed it."""
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(LlmProviderConnection, User.full_name, User.email)
                .outerjoin(User, col(User.id) == col(LlmProviderConnection.updated_by))
                .where(col(LlmProviderConnection.deleted_at).is_(None))
                .order_by(
                    sa.case((col(LlmProviderConnection.slug) == OPENROUTER_SLUG, 0), else_=1),
                    col(LlmProviderConnection.name),
                    col(LlmProviderConnection.slug),
                )
            ).all()
        return [(connection, full_name or email) for connection, full_name, email in rows]

    def slug_used(self, slug: str) -> bool:
        """Whether any connection, deleted or not, has this slug."""
        with Session(self.delegate.engine) as session:
            return (
                session.exec(select(LlmProviderConnection.id).where(LlmProviderConnection.slug == slug)).first()
                is not None
            )

    def replace_key(
        self,
        slug: str,
        api_key_encrypted: str,
        api_key_last4: str,
        actor_id: UUID,
        actor_display: str,
        *,
        seen_base_url: str | None,
        base_url: str | None,
        apply: Callable[[LlmProviderConnection, list[LlmProviderModel]], None],
    ) -> list[UUID]:
        """Store a new key and the base URL it was checked at, calling `apply` first under the
        connection's lock.

        `apply` gets the connection, already carrying the new base URL, and its models, and pushes
        the key to LiteLLM; if it raises, nothing is stored. Raises ConnectionChanged when the stored
        base URL is no longer `seen_base_url`, the one read before the key was checked.
        """
        with Session(self.delegate.engine) as session:
            self._lock(session, slug)
            connection = session.exec(
                select(LlmProviderConnection).where(
                    LlmProviderConnection.slug == slug, col(LlmProviderConnection.deleted_at).is_(None)
                )
            ).one_or_none()
            if connection is None:
                raise ConnectionNotFound(slug)
            previous_base_url = connection.base_url
            if previous_base_url != seen_base_url:
                raise ConnectionChanged(slug)
            replaced_existing = connection.api_key_encrypted is not None
            connection.base_url = base_url
            apply(connection, self._models(session, connection))
            now = datetime.now(UTC)
            connection.api_key_encrypted = api_key_encrypted
            connection.api_key_last4 = api_key_last4
            connection.updated_by = actor_id
            connection.updated_at = now
            session.add(connection)
            ids = self._stage(
                session,
                PLATFORM_LLM_PROVIDER_CHANGED,
                connection,
                actor_id,
                now,
                {
                    "replaced_existing": replaced_existing,
                    "provider_type": connection.provider_type.value,
                    "previous_base_url": previous_base_url,
                    "base_url": base_url,
                    "actor_display": actor_display,
                },
            )
            session.commit()
            return ids

    def add(
        self,
        slug: str,
        name: str,
        provider_type: ProviderType,
        base_url: str | None,
        api_key_encrypted: str,
        api_key_last4: str,
        actor_id: UUID,
        actor_display: str,
    ) -> list[UUID]:
        """Store a new connection with its key, or bring a deleted known provider's connection back.

        Raises ConnectionAlreadyExists when a connection with this slug is not deleted, or when an
        Azure or Custom slug was used before, deleted or not.
        """
        with Session(self.delegate.engine) as session:
            self._lock(session, slug)
            existing = session.exec(
                select(LlmProviderConnection).where(LlmProviderConnection.slug == slug)
            ).one_or_none()
            if existing is not None and (existing.deleted_at is None or provider_type in BASE_URL_PROVIDER_TYPES):
                raise ConnectionAlreadyExists(slug)
            now = datetime.now(UTC)
            connection = existing or LlmProviderConnection(
                slug=slug, name=name, provider_type=provider_type, base_url=base_url
            )
            connection.name = name
            connection.api_key_encrypted = api_key_encrypted
            connection.api_key_last4 = api_key_last4
            connection.updated_by = actor_id
            connection.updated_at = now
            connection.deleted_at = None
            session.add(connection)
            session.flush()
            ids = self._stage(
                session,
                PLATFORM_LLM_PROVIDER_CREATED,
                connection,
                actor_id,
                now,
                {
                    "provider_type": connection.provider_type.value,
                    "base_url": connection.base_url,
                    "revived": existing is not None,
                    "actor_display": actor_display,
                },
            )
            session.commit()
            return ids

    def delete(
        self,
        slug: str,
        actor_id: UUID,
        actor_display: str,
        *,
        apply: Callable[[LlmProviderConnection], None],
    ) -> list[UUID]:
        """Delete the connection's models, soft-delete the connection and purge its key, calling
        `apply` first under the connection's lock.

        `apply` removes the connection's routes from LiteLLM; if it raises, nothing is deleted.
        Raises ConnectionNotFound when no connection with this slug is live.
        """
        with Session(self.delegate.engine) as session:
            self._lock(session, slug)
            connection = session.exec(
                select(LlmProviderConnection).where(
                    LlmProviderConnection.slug == slug, col(LlmProviderConnection.deleted_at).is_(None)
                )
            ).one_or_none()
            if connection is None:
                raise ConnectionNotFound(slug)
            apply(connection)
            session.exec(sa.delete(LlmProviderModel).where(col(LlmProviderModel.connection_id) == connection.id))
            key_purged = connection.api_key_encrypted is not None
            now = datetime.now(UTC)
            connection.api_key_encrypted = None
            connection.api_key_last4 = None
            connection.deleted_at = now
            session.add(connection)
            ids = self._stage(
                session,
                PLATFORM_LLM_PROVIDER_DELETED,
                connection,
                actor_id,
                now,
                {
                    "provider_type": connection.provider_type.value,
                    "base_url": connection.base_url,
                    "key_purged": key_purged,
                    "actor_display": actor_display,
                },
            )
            session.commit()
            return ids

    @staticmethod
    def _models(session: Session, connection: LlmProviderConnection) -> list[LlmProviderModel]:
        return list(
            session.exec(
                select(LlmProviderModel)
                .where(LlmProviderModel.connection_id == connection.id)
                .order_by(col(LlmProviderModel.model_id))
            )
        )

    @staticmethod
    def _lock(session: Session, slug: str) -> None:
        session.connection().execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"llm_provider_connection:{slug}"},
        )

    def _stage(
        self,
        session: Session,
        event_name: str,
        connection: LlmProviderConnection,
        actor_id: UUID,
        occurred_at: datetime,
        payload: dict[str, object],
    ) -> list[UUID]:
        event = EVENT_REGISTRY.build_event(
            event_name=event_name,
            schema_version=1,
            occurred_at=occurred_at,
            organization_id=None,
            actor=ActorIdentity(type=ActorIdentityType.USER, id=actor_id),
            subject=SubjectIdentity(type=SubjectIdentityType.SYSTEM, id=str(connection.id)),
            correlation_id=uuid4(),
            payload={
                "connection_id": connection.id,
                "slug": connection.slug,
                **payload,
                "subject_display": connection.name,
            },
        )
        self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
        return list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))

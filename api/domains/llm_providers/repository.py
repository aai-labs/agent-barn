from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4, uuid5

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.agent_settings.models import OrganizationAgentSettings
from api.domains.agents.models import Agent
from api.domains.events import ActorIdentity, ActorIdentityType, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import (
    EVENT_REGISTRY,
    MAX_LISTED_MODEL_IDS,
    MAX_LISTED_ORGANIZATION_IDS,
    PLATFORM_LLM_PROVIDER_CHANGED,
    PLATFORM_LLM_PROVIDER_CREATED,
    PLATFORM_LLM_PROVIDER_DELETED,
    PLATFORM_LLM_PROVIDER_MODELS_CHANGED,
    PLATFORM_LLM_PROVIDER_ORGANIZATIONS_CHANGED,
)
from api.domains.events.repository import OutboxMessageRepository
from api.domains.llm_providers.access import can_use
from api.domains.llm_providers.models import (
    BASE_URL_PROVIDER_TYPES,
    OPENROUTER_SLUG,
    LlmProviderConnection,
    LlmProviderConnectionOrganization,
    LlmProviderModel,
    LlmProviderModelPrices,
    OrganizationAccess,
    ProviderType,
)
from api.domains.organizations.models import Organization
from api.domains.users.models import User
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class ConnectionNotFound(LookupError):
    pass


class ConnectionAlreadyExists(Exception):
    pass


class ConnectionChanged(Exception):
    pass


class UnknownOrganization(LookupError):
    pass


@dataclass(frozen=True)
class OrganizationUse:
    """What an Organization still uses a connection through."""

    organization_id: UUID
    name: str
    allowlist: bool
    own_default: bool
    agents: int


class ConnectionInUse(Exception):
    def __init__(self, name: str, users: list[OrganizationUse]) -> None:
        super().__init__(name)
        self.name = name
        self.users = users


ListedOrganizations = tuple[OrganizationAccess, list[tuple[UUID, str]]]


def _reprice(model: LlmProviderModel, prices: LlmProviderModelPrices) -> None:
    model.input_cost_per_token = prices.input_cost_per_token
    model.output_cost_per_token = prices.output_cost_per_token
    model.cache_read_input_token_cost = prices.cache_read_input_token_cost
    model.cache_creation_input_token_cost = prices.cache_creation_input_token_cost
    model.price_source = prices.price_source
    model.litellm_price_key = prices.litellm_price_key


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

    def list_models(self, connection_id: UUID) -> list[LlmProviderModel]:
        """The connection's models, by model id."""
        with Session(self.delegate.engine) as session:
            return self._models(session, connection_id)

    def slug_used(self, slug: str) -> bool:
        """Whether any connection, deleted or not, has this slug."""
        with Session(self.delegate.engine) as session:
            return (
                session.exec(select(LlmProviderConnection.id).where(LlmProviderConnection.slug == slug)).first()
                is not None
            )

    def organizations_known(self, organization_ids: frozenset[UUID]) -> bool:
        """Whether every id names an Organization."""
        with Session(self.delegate.engine) as session:
            return self._organizations_known(session, organization_ids)

    def organization_counts(self, connection_ids: list[UUID]) -> dict[UUID, int]:
        """How many Organizations each connection lists, for connections that list any."""
        with Session(self.delegate.engine) as session:
            rows = (
                session.connection()
                .execute(
                    sa.select(col(LlmProviderConnectionOrganization.connection_id), sa.func.count())
                    .where(col(LlmProviderConnectionOrganization.connection_id).in_(connection_ids))
                    .group_by(col(LlmProviderConnectionOrganization.connection_id))
                )
                .all()
            )
        return {connection_id: count for connection_id, count in rows}

    def access(self, slug: str, organization_id: UUID | None) -> tuple[OrganizationAccess, frozenset[UUID]] | None:
        """The live connection's Organization access and, of its listed Organizations, only this one
        if listed."""
        with Session(self.delegate.engine) as session:
            return self._access(session, slug, organization_id)

    def access_held(
        self, session: Session, slug: str, organization_id: UUID | None
    ) -> tuple[OrganizationAccess, frozenset[UUID]] | None:
        """As `access`, read in the caller's transaction after taking the connection's lock shared,
        so no withdrawal can commit until that transaction ends."""
        self._lock(session, slug, shared=True)
        return self._access(session, slug, organization_id)

    def open_models(self, organization_id: UUID) -> list[tuple[LlmProviderConnection, list[LlmProviderModel]]]:
        """The live connections the Organization may use, OpenRouter first and then by name, each with
        its stored models by model id."""
        with Session(self.delegate.engine) as session:
            connections = session.exec(
                select(LlmProviderConnection)
                .where(col(LlmProviderConnection.deleted_at).is_(None))
                .order_by(
                    sa.case((col(LlmProviderConnection.slug) == OPENROUTER_SLUG, 0), else_=1),
                    col(LlmProviderConnection.name),
                    col(LlmProviderConnection.slug),
                )
            ).all()
            listed = frozenset(
                session.exec(
                    select(LlmProviderConnectionOrganization.connection_id).where(
                        LlmProviderConnectionOrganization.organization_id == organization_id
                    )
                ).all()
            )
            open_connections = [
                connection
                for connection in connections
                if can_use(
                    connection.organization_access,
                    {organization_id} if connection.id in listed else set(),
                    organization_id,
                )
            ]
            models = session.exec(
                select(LlmProviderModel)
                .where(col(LlmProviderModel.connection_id).in_([connection.id for connection in open_connections]))
                .order_by(col(LlmProviderModel.model_id))
            ).all()
        return [
            (connection, [model for model in models if model.connection_id == connection.id])
            for connection in open_connections
        ]

    def organizations(self, slug: str) -> ListedOrganizations | None:
        """The live connection's Provider Access and its listed Organizations, by name."""
        with Session(self.delegate.engine) as session:
            connection = self._live(session, slug)
            if connection is None:
                return None
            return connection.organization_access, self._listed_organizations(session, connection.id)

    def replace_organizations(
        self,
        slug: str,
        organization_access: OrganizationAccess,
        organization_ids: frozenset[UUID],
        actor_id: UUID,
        actor_display: str,
    ) -> tuple[ListedOrganizations, list[UUID]]:
        """Store the connection's Provider Access and listed Organizations with the event, under its
        lock, unless nothing changes.

        Raises ConnectionNotFound when no connection with this slug is live, UnknownOrganization when
        an id names no Organization, and ConnectionInUse when an Organization losing access still
        uses OpenRouter. The key's save time is left as it was.
        """
        with Session(self.delegate.engine) as session:
            self._lock(session, slug)
            connection = self._live(session, slug)
            if connection is None:
                raise ConnectionNotFound(slug)
            if not self._organizations_known(session, organization_ids):
                raise UnknownOrganization
            previous_access = connection.organization_access
            previous = frozenset(
                session.exec(
                    select(LlmProviderConnectionOrganization.organization_id).where(
                        LlmProviderConnectionOrganization.connection_id == connection.id
                    )
                ).all()
            )
            if connection.slug == OPENROUTER_SLUG:
                losing = [
                    use
                    for use in self._openrouter_uses(session)
                    if can_use(previous_access, previous, use.organization_id)
                    and not can_use(organization_access, organization_ids, use.organization_id)
                ]
                if losing:
                    raise ConnectionInUse(connection.name, losing)
            if organization_access == previous_access and organization_ids == previous:
                return (previous_access, self._listed_organizations(session, connection.id)), []
            added = sorted(organization_ids - previous, key=str)
            removed = sorted(previous - organization_ids, key=str)
            if removed:
                session.exec(
                    sa.delete(LlmProviderConnectionOrganization).where(
                        col(LlmProviderConnectionOrganization.connection_id) == connection.id,
                        col(LlmProviderConnectionOrganization.organization_id).in_(removed),
                    )
                )
            session.add_all(
                LlmProviderConnectionOrganization(connection_id=connection.id, organization_id=organization_id)
                for organization_id in added
            )
            session.exec(
                sa.update(LlmProviderConnection)
                .where(col(LlmProviderConnection.id) == connection.id)
                .values(organization_access=organization_access, updated_at=LlmProviderConnection.updated_at)
            )
            ids = self._stage(
                session,
                PLATFORM_LLM_PROVIDER_ORGANIZATIONS_CHANGED,
                connection,
                actor_id,
                datetime.now(UTC),
                {
                    "previous_organization_access": previous_access.value,
                    "organization_access": organization_access.value,
                    "added_count": len(added),
                    "removed_count": len(removed),
                    "added_organization_ids": added[:MAX_LISTED_ORGANIZATION_IDS],
                    "removed_organization_ids": removed[:MAX_LISTED_ORGANIZATION_IDS],
                    "organization_ids_truncated": max(len(added), len(removed)) > MAX_LISTED_ORGANIZATION_IDS,
                    "actor_display": actor_display,
                },
            )
            listed = self._listed_organizations(session, connection.id)
            session.commit()
            return (organization_access, listed), ids

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
            apply(connection, self._models(session, connection.id))
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

    def replace_models(
        self,
        slug: str,
        actor_id: UUID,
        actor_display: str,
        *,
        seen_api_key_encrypted: str,
        seen_base_url: str | None,
        wanted: list[tuple[str, LlmProviderModelPrices | None]],
        apply: Callable[[LlmProviderConnection, list[LlmProviderModel]], None],
    ) -> list[UUID]:
        """Make the connection's models exactly `wanted`, calling `apply` first under its lock.

        Each wanted model carries its prices, or None to keep its stored ones. A new model's row id
        is derived from the connection and the model id, so a retried save writes the same route.
        `apply` gets the connection and the models it will have, and writes their LiteLLM routes;
        if it raises, nothing is stored. When no model is added, removed or repriced, nothing is
        stored and no event is staged. Raises ConnectionNotFound when no connection with this slug is
        live, and ConnectionChanged when its key or base URL is no longer the one read before the
        provider's list was, or a model to keep is no longer stored.
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
            if connection.api_key_encrypted != seen_api_key_encrypted or connection.base_url != seen_base_url:
                raise ConnectionChanged(slug)
            stored = {model.model_id: model for model in self._models(session, connection.id)}
            models: list[LlmProviderModel] = []
            repriced: list[str] = []
            for model_id, prices in wanted:
                model = stored.get(model_id)
                if prices is None:
                    if model is None:
                        raise ConnectionChanged(slug)
                elif model is None:
                    model = LlmProviderModel(
                        id=uuid5(connection.id, model_id),
                        connection_id=connection.id,
                        model_id=model_id,
                        input_cost_per_token=prices.input_cost_per_token,
                        output_cost_per_token=prices.output_cost_per_token,
                        cache_read_input_token_cost=prices.cache_read_input_token_cost,
                        cache_creation_input_token_cost=prices.cache_creation_input_token_cost,
                        price_source=prices.price_source,
                        litellm_price_key=prices.litellm_price_key,
                    )
                elif LlmProviderModelPrices.of(model) != prices:
                    repriced.append(model_id)
                    _reprice(model, prices)
                models.append(model)
            models.sort(key=lambda model: model.model_id)
            apply(connection, models)
            added = sorted(model.model_id for model in models if model.model_id not in stored)
            removed = sorted(stored.keys() - {model.model_id for model in models})
            repriced.sort()
            if not (added or removed or repriced):
                return []
            for model_id in removed:
                session.delete(stored[model_id])
            session.add_all(models)
            ids = self._stage(
                session,
                PLATFORM_LLM_PROVIDER_MODELS_CHANGED,
                connection,
                actor_id,
                datetime.now(UTC),
                {
                    "provider_type": connection.provider_type.value,
                    "added_count": len(added),
                    "removed_count": len(removed),
                    "repriced_count": len(repriced),
                    "added_model_ids": added[:MAX_LISTED_MODEL_IDS],
                    "removed_model_ids": removed[:MAX_LISTED_MODEL_IDS],
                    "repriced_model_ids": repriced[:MAX_LISTED_MODEL_IDS],
                    "model_ids_truncated": max(len(added), len(removed), len(repriced)) > MAX_LISTED_MODEL_IDS,
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
        organization_access: OrganizationAccess,
        organization_ids: frozenset[UUID],
        actor_id: UUID,
        actor_display: str,
    ) -> list[UUID]:
        """Store a new connection with its key and Provider Access, or bring a deleted known
        provider's connection back with them. Access other than "all" is recorded as a change from
        "all" after the creation.

        Raises ConnectionAlreadyExists when a connection with this slug is not deleted, or when an
        Azure or Custom slug was used before, deleted or not, and UnknownOrganization when an id
        names no Organization.
        """
        with Session(self.delegate.engine) as session:
            self._lock(session, slug)
            existing = session.exec(
                select(LlmProviderConnection).where(LlmProviderConnection.slug == slug)
            ).one_or_none()
            if existing is not None and (existing.deleted_at is None or provider_type in BASE_URL_PROVIDER_TYPES):
                raise ConnectionAlreadyExists(slug)
            if not self._organizations_known(session, organization_ids):
                raise UnknownOrganization
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
            connection.organization_access = organization_access
            session.add(connection)
            session.flush()
            session.exec(
                sa.delete(LlmProviderConnectionOrganization).where(
                    col(LlmProviderConnectionOrganization.connection_id) == connection.id
                )
            )
            added = sorted(organization_ids, key=str)
            session.add_all(
                LlmProviderConnectionOrganization(connection_id=connection.id, organization_id=organization_id)
                for organization_id in added
            )
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
            if organization_access != OrganizationAccess.ALL:
                ids += self._stage(
                    session,
                    PLATFORM_LLM_PROVIDER_ORGANIZATIONS_CHANGED,
                    connection,
                    actor_id,
                    now,
                    {
                        "previous_organization_access": OrganizationAccess.ALL.value,
                        "organization_access": organization_access.value,
                        "added_count": len(added),
                        "removed_count": 0,
                        "added_organization_ids": added[:MAX_LISTED_ORGANIZATION_IDS],
                        "removed_organization_ids": [],
                        "organization_ids_truncated": len(added) > MAX_LISTED_ORGANIZATION_IDS,
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
        """Delete the connection's models and listed Organizations, soft-delete the connection and
        purge its key, calling `apply` first under the connection's lock.

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
            session.exec(
                sa.delete(LlmProviderConnectionOrganization).where(
                    col(LlmProviderConnectionOrganization.connection_id) == connection.id
                )
            )
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
    def _live(session: Session, slug: str) -> LlmProviderConnection | None:
        return session.exec(
            select(LlmProviderConnection).where(
                LlmProviderConnection.slug == slug, col(LlmProviderConnection.deleted_at).is_(None)
            )
        ).first()

    @staticmethod
    def _organizations_known(session: Session, organization_ids: frozenset[UUID]) -> bool:
        if not organization_ids:
            return True
        known = session.exec(select(Organization.id).where(col(Organization.id).in_(organization_ids))).all()
        return set(known) == organization_ids

    @staticmethod
    def _listed_organizations(session: Session, connection_id: UUID) -> list[tuple[UUID, str]]:
        rows = session.exec(
            select(Organization.id, Organization.name)
            .join(
                LlmProviderConnectionOrganization,
                col(LlmProviderConnectionOrganization.organization_id) == col(Organization.id),
            )
            .where(LlmProviderConnectionOrganization.connection_id == connection_id)
            .order_by(col(Organization.name), col(Organization.id))
        ).all()
        return [(organization_id, name) for organization_id, name in rows]

    @staticmethod
    def _openrouter_uses(session: Session) -> list[OrganizationUse]:
        live_agents = (
            select(col(Agent.organization_id), sa.func.count().label("agents"))
            .where(col(Agent.deleted_at).is_(None))
            .group_by(col(Agent.organization_id))
            .subquery()
        )
        allowlist = sa.func.coalesce(sa.func.jsonb_array_length(col(Organization.allowed_models)), 0) > 0
        own_default = col(OrganizationAgentSettings.default_model).is_not(None)
        agents = sa.func.coalesce(live_agents.c.agents, 0)
        rows = (
            session.connection()
            .execute(
                sa.select(col(Organization.id), col(Organization.name), allowlist, own_default, agents)
                .outerjoin(
                    OrganizationAgentSettings,
                    col(OrganizationAgentSettings.organization_id) == col(Organization.id),
                )
                .outerjoin(live_agents, live_agents.c.organization_id == col(Organization.id))
                .where(sa.or_(allowlist, own_default, agents > 0))
                .order_by(col(Organization.name), col(Organization.id))
            )
            .all()
        )
        return [OrganizationUse(*row) for row in rows]

    @staticmethod
    def _models(session: Session, connection_id: UUID) -> list[LlmProviderModel]:
        return list(
            session.exec(
                select(LlmProviderModel)
                .where(LlmProviderModel.connection_id == connection_id)
                .order_by(col(LlmProviderModel.model_id))
            )
        )

    @staticmethod
    def _lock(session: Session, slug: str, *, shared: bool = False) -> None:
        function = "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
        session.connection().execute(
            sa.text(f"SELECT {function}(hashtextextended(:key, 0))"),
            {"key": f"llm_provider_connection:{slug}"},
        )

    @staticmethod
    def _access(
        session: Session, slug: str, organization_id: UUID | None
    ) -> tuple[OrganizationAccess, frozenset[UUID]] | None:
        connection = session.exec(
            select(LlmProviderConnection).where(
                LlmProviderConnection.slug == slug, col(LlmProviderConnection.deleted_at).is_(None)
            )
        ).first()
        if connection is None:
            return None
        listed = session.exec(
            select(LlmProviderConnectionOrganization.organization_id).where(
                LlmProviderConnectionOrganization.connection_id == connection.id,
                LlmProviderConnectionOrganization.organization_id == organization_id,
            )
        ).all()
        return connection.organization_access, frozenset(listed)

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

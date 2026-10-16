from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentStatus
from api.domains.agents.repository import agent_scope_predicates
from api.domains.custom_api.models import CustomApiConnection
from api.domains.events import ActorIdentity, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import AGENT_UPDATED, EVENT_REGISTRY
from api.domains.events.repository import OutboxMessageRepository
from api.domains.integrations.models import AgentIntegrationRuntime
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class CustomApiRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def list_in_scope(self, agent_id: UUID, scope: AuthorizationScope) -> list[CustomApiConnection]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(CustomApiConnection)
                    .join(Agent)
                    .where(CustomApiConnection.agent_id == agent_id, *agent_scope_predicates(scope))
                    .order_by(CustomApiConnection.slug)
                ).all()
            )

    def runtime_connections(self, agent_id: UUID) -> list[CustomApiConnection]:
        """Internal lifecycle only; caller has authorized the Agent operation."""
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(CustomApiConnection)
                    .join(Agent)
                    .where(CustomApiConnection.agent_id == agent_id, col(Agent.deleted_at).is_(None))
                    .order_by(CustomApiConnection.slug)
                ).all()
            )

    def save(self, connection: CustomApiConnection) -> CustomApiConnection:
        return self.delegate.save(connection)

    def delete(self, connection: CustomApiConnection) -> None:
        self.delegate.delete(connection)

    def authorize_token(self, token_hash: str) -> CustomApiConnection | None:
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(CustomApiConnection)
                .join(Agent)
                .join(AgentIntegrationRuntime, col(AgentIntegrationRuntime.agent_id) == col(Agent.id))
                .where(
                    CustomApiConnection.token_hash == token_hash,
                    CustomApiConnection.generation == AgentIntegrationRuntime.generation,
                    col(AgentIntegrationRuntime.state).in_(["preparing", "provisioned", "ready", "stopping"]),
                    Agent.status == AgentStatus.RUNNING,
                    col(Agent.deleted_at).is_(None),
                )
            ).first()
            if row is None:
                return None
            runtime = session.exec(
                select(AgentIntegrationRuntime).where(AgentIntegrationRuntime.agent_id == row.agent_id)
            ).one()
            snapshot = runtime.bindings.get("custom_api:" + row.slug, {})
            if snapshot.get("isolated") is not True or snapshot.get("binding_id") != str(row.id):
                return None
            return row

    def mutate_with_event(
        self, row: CustomApiConnection, actor: ActorIdentity, actor_display: str, operation: str
    ) -> list[UUID]:
        return self.mutate_many_with_events([(row, operation)], actor, actor_display)

    def mutate_many_with_events(
        self, changes: list[tuple[CustomApiConnection, str]], actor: ActorIdentity, actor_display: str
    ) -> list[UUID]:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            deliveries: list[UUID] = []
            for row, operation in sorted(changes, key=lambda change: change[1] != "deleted"):
                deliveries.extend(self._stage_change(session, row, actor, actor_display, operation))
                # A deleted identifier can be reused by a create in this transaction.
                session.flush()
            session.commit()
            return deliveries

    def _stage_change(
        self, session: Session, row: CustomApiConnection, actor: ActorIdentity, actor_display: str, operation: str
    ) -> list[UUID]:
        agent = session.get(Agent, row.agent_id)
        if agent is None:
            raise ValueError("Agent no longer exists")
        if operation == "deleted":
            session.delete(row)
        else:
            session.add(row)
        event = EVENT_REGISTRY.build_event(
            event_name=AGENT_UPDATED,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=agent.organization_id,
            actor=actor,
            subject=SubjectIdentity(type=SubjectIdentityType.AGENT, id=agent.id, organization_id=agent.organization_id),
            correlation_id=uuid4(),
            payload={
                "organization_id": agent.organization_id,
                "agent_id": agent.id,
                "field_changes": {"custom_api_connections." + row.slug: {"previous": None, "new": operation}},
                "actor_display": actor_display,
                "subject_display": agent.name,
            },
        )
        self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
        deliveries = list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))
        return deliveries

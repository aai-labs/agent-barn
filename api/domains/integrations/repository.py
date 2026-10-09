"""Integration intent, source-bound generations, and machine authorization."""

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentSecret, SecretProvider
from api.domains.events import ActorIdentity, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import AGENT_UPDATED, EVENT_REGISTRY
from api.domains.events.repository import OutboxMessageRepository
from api.domains.integrations.isolation import legacy_isolation
from api.domains.integrations.models import AgentIntegrationIsolation, AgentIntegrationRuntime
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class IntegrationRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def policies(self, agent_id: UUID, source: str = "agent_secret") -> dict[SecretProvider, bool]:
        with Session(self.delegate.engine) as session:
            return {
                SecretProvider(row.provider): row.isolated
                for row in session.exec(
                    select(AgentIntegrationIsolation).where(
                        AgentIntegrationIsolation.agent_id == agent_id, AgentIntegrationIsolation.source == source
                    )
                ).all()
            }

    def set_policy(
        self,
        agent_id: UUID,
        provider: SecretProvider,
        isolated: bool,
        source: str = "agent_secret",
        *,
        actor: ActorIdentity | None = None,
        actor_display: str | None = None,
    ) -> list[UUID]:
        with Session(self.delegate.engine) as session:
            policy = session.exec(
                select(AgentIntegrationIsolation).where(
                    AgentIntegrationIsolation.agent_id == agent_id,
                    AgentIntegrationIsolation.provider == provider,
                    AgentIntegrationIsolation.source == source,
                )
            ).first()
            previous = (
                policy.isolated if policy else (False if source == "platform_default" else legacy_isolation(provider))
            )
            if policy is None:
                policy = AgentIntegrationIsolation(
                    agent_id=agent_id, provider=provider, isolated=isolated, source=source
                )
            policy.isolated = isolated
            session.add(policy)
            deliveries: list[UUID] = []
            if actor is not None and previous != isolated:
                agent = session.get(Agent, agent_id)
                if agent is None:
                    raise ValueError("Agent no longer exists")
                event = EVENT_REGISTRY.build_event(
                    event_name=AGENT_UPDATED,
                    schema_version=1,
                    occurred_at=datetime.now(UTC),
                    organization_id=agent.organization_id,
                    actor=actor,
                    subject=SubjectIdentity(
                        type=SubjectIdentityType.AGENT, id=agent.id, organization_id=agent.organization_id
                    ),
                    correlation_id=uuid4(),
                    payload={
                        "organization_id": agent.organization_id,
                        "agent_id": agent.id,
                        "field_changes": {
                            f"integration_isolation.{provider.value}."
                            + ("default" if source == "platform_default" else "stored"): {
                                "previous": previous,
                                "new": isolated,
                            }
                        },
                        "actor_display": actor_display or actor.type.value,
                        "subject_display": agent.name,
                    },
                )
                self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)
                deliveries = list(
                    session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id))
                )
            session.commit()
            return deliveries

    def runtime(self, agent_id: UUID) -> AgentIntegrationRuntime | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentIntegrationRuntime).where(AgentIntegrationRuntime.agent_id == agent_id)
            ).first()

    def begin(self, agent_id: UUID, bindings: dict) -> AgentIntegrationRuntime:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            runtime = session.exec(
                select(AgentIntegrationRuntime).where(AgentIntegrationRuntime.agent_id == agent_id)
            ).first()
            if runtime is None:
                runtime = AgentIntegrationRuntime(agent_id=agent_id, generation=uuid4(), state="preparing")
            runtime.bindings = bindings
            runtime.generation = uuid4()
            runtime.state = "preparing"
            session.add(runtime)
            session.commit()
            return runtime

    def set_state(
        self, agent_id: UUID, state: str, generation: UUID | None = None, *, expected_state: str | None = None
    ) -> None:
        with Session(self.delegate.engine) as session:
            runtime = session.exec(
                select(AgentIntegrationRuntime).where(AgentIntegrationRuntime.agent_id == agent_id).with_for_update()
            ).first()
            if (
                runtime is not None
                and (generation is None or generation == runtime.generation)
                and (expected_state is None or expected_state == runtime.state)
            ):
                if state == "ready" and not runtime.authentication_complete:
                    raise ValueError("SharePoint authentication handoff is incomplete")
                runtime.state = state
                if state == "ready":
                    runtime.previous_bindings = runtime.bindings
                session.add(runtime)
                session.commit()

    def authorizes(
        self,
        agent_id: UUID,
        organization_id: UUID,
        provider: SecretProvider,
        binding_id: UUID | None,
        generation: UUID | None,
        source: str,
    ) -> bool:
        with Session(self.delegate.engine) as session:
            agent = session.exec(
                select(Agent).where(
                    Agent.id == agent_id, Agent.organization_id == organization_id, col(Agent.deleted_at).is_(None)
                )
            ).first()
            if agent is None:
                return False
            secret = session.exec(
                select(AgentSecret).where(AgentSecret.agent_id == agent_id, AgentSecret.provider == provider)
            ).first()
            if source == "platform_default":
                if (
                    provider != SecretProvider.FIRECRAWL
                    or secret is not None
                    or binding_id is not None
                    or generation is None
                ):
                    return False
            elif source != "agent_secret" or secret is None or secret.id != binding_id:
                return False
            policy = session.exec(
                select(AgentIntegrationIsolation).where(
                    AgentIntegrationIsolation.agent_id == agent_id,
                    AgentIntegrationIsolation.provider == provider,
                    AgentIntegrationIsolation.source == source,
                )
            ).first()
            isolated = (
                policy.isolated if policy else (False if source == "platform_default" else legacy_isolation(provider))
            )
            if generation is None:
                return isolated  # Compatibility for existing, source-bound gateway tokens.
            runtime = session.exec(
                select(AgentIntegrationRuntime).where(AgentIntegrationRuntime.agent_id == agent_id)
            ).first()
            return bool(
                runtime
                and runtime.generation == generation
                and runtime.state in {"preparing", "provisioned", "ready", "stopping"}
                and runtime.bindings.get(provider.value, {}).get("isolated") is True
                and runtime.bindings.get(provider.value, {}).get("binding_id") == (str(secret.id) if secret else None)
                and runtime.bindings.get(provider.value, {}).get("source", "agent_secret") == source
            )

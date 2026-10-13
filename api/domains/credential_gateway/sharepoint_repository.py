"""Tenant-scoped row locks for broker rotation and generation handoff."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentSecret, SecretProvider
from api.domains.integrations.models import AgentIntegrationRuntime
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class SharePointHandoffRefused(Exception):
    """Imports and minting are restricted to their current runtime binding."""


@dataclass
class SharePointTransaction:
    session: Session
    secret: AgentSecret
    runtime: AgentIntegrationRuntime | None
    binding: dict
    generation: UUID | None
    direct: bool

    def save(self, ciphertext: str, *, handoff_complete: bool | None = None) -> None:
        if not self.direct and self.runtime:
            self.session.refresh(self.runtime)
            current = self.runtime.bindings.get("sharepoint", {})
            if (
                self.runtime.generation != self.generation
                or self.runtime.state not in {"preparing", "provisioned", "ready", "stopping"}
                or not current.get("isolated")
                or current.get("binding_id") != str(self.secret.id)
                or (handoff_complete is None and not current.get("handoff_complete"))
            ):
                raise SharePointHandoffRefused()
        self.secret.content = ciphertext
        self.session.add(self.secret)
        if handoff_complete is not None and self.runtime:
            self.runtime.bindings = {
                **self.runtime.bindings,
                "sharepoint": {**self.binding, "handoff_complete": handoff_complete, "reconnect_required": False},
            }
            self.session.add(self.runtime)
        self.session.commit()


@inject
@singleton
@dataclass
class SharePointBrokerRepository:
    delegate: PostgresRepositoryDelegate

    def record_reconnect_required(self, agent_id: UUID, generation: UUID | None) -> None:
        with Session(self.delegate.engine) as session:
            runtime = session.exec(
                select(AgentIntegrationRuntime).where(AgentIntegrationRuntime.agent_id == agent_id).with_for_update()
            ).first()
            if runtime is not None and runtime.generation == generation:
                binding = runtime.bindings.get("sharepoint", {})
                runtime.bindings = {**runtime.bindings, "sharepoint": {**binding, "reconnect_required": True}}
                session.add(runtime)
                session.commit()

    @contextmanager
    def locked(
        self,
        agent_id: UUID,
        organization_id: UUID,
        generation: UUID | None = None,
        *,
        handoff: bool = False,
        direct: bool = False,
    ) -> Iterator[SharePointTransaction]:
        with Session(self.delegate.engine) as session:
            runtime_query = select(AgentIntegrationRuntime).where(AgentIntegrationRuntime.agent_id == agent_id)
            # Imports modify the generation snapshot. Ordinary cached minting needs
            # only the credential lock, so provider latency cannot lock Agent reads.
            if handoff or direct:
                runtime_query = runtime_query.with_for_update()
            runtime = session.exec(runtime_query).first()
            binding = runtime.bindings.get("sharepoint", {}) if runtime else {}
            if not direct:
                states = (
                    {"preparing", "provisioned", "ready"}
                    if handoff
                    else {"preparing", "provisioned", "ready", "stopping"}
                )
                if (
                    runtime is None
                    or runtime.generation != generation
                    or runtime.state not in states
                    or not binding.get("isolated")
                    or (not handoff and not binding.get("handoff_complete"))
                    or (handoff and runtime.state == "ready" and not binding.get("handoff_complete"))
                ):
                    raise SharePointHandoffRefused()
            secret = session.exec(
                select(AgentSecret)
                .join(Agent, col(Agent.id) == col(AgentSecret.agent_id))
                .where(
                    AgentSecret.agent_id == agent_id,
                    Agent.organization_id == organization_id,
                    col(Agent.deleted_at).is_(None),
                    AgentSecret.provider == SecretProvider.SHAREPOINT,
                )
                .with_for_update(of=AgentSecret)
            ).first()
            if secret is None or secret.content is None or secret.shared_credential_id is not None:
                raise SharePointHandoffRefused()
            if not direct and binding.get("binding_id") != str(secret.id):
                raise SharePointHandoffRefused()
            if runtime and not direct:
                session.refresh(runtime)
                binding = runtime.bindings.get("sharepoint", {})
                if (
                    runtime.generation != generation
                    or runtime.state not in states
                    or not binding.get("isolated")
                    or binding.get("binding_id") != str(secret.id)
                    or (not handoff and not binding.get("handoff_complete"))
                ):
                    raise SharePointHandoffRefused()
            yield SharePointTransaction(session, secret, runtime, binding, generation, direct)

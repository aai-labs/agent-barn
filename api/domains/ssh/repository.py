import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException
from injector import inject, singleton
from sqlalchemy import delete, func
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentStatus
from api.domains.agents.repository import agent_scope_predicates
from api.domains.events import ActorIdentity, ActorIdentityType, SubjectIdentity, SubjectIdentityType
from api.domains.events.catalog import EVENT_REGISTRY
from api.domains.events.repository import OutboxMessageRepository
from api.domains.integrations.models import AgentIntegrationRuntime
from api.domains.rbac.policy import AuthorizationScope
from api.domains.ssh.models import AgentSshCredential, SshCredential, SshRuntimeCredential
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


@inject
@singleton
@dataclass
class SshRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository

    def _event(
        self,
        session: Session,
        name: str,
        org: UUID,
        actor: ActorIdentity,
        *,
        agent_id: UUID | None = None,
        key: SshCredential | None = None,
        **metadata,
    ) -> None:
        subject = SubjectIdentity(
            type=SubjectIdentityType.AGENT if agent_id else SubjectIdentityType.ORGANIZATION,
            id=agent_id or org,
            organization_id=org,
        )
        event = EVENT_REGISTRY.build_event(
            event_name=name,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=org,
            actor=actor,
            subject=subject,
            correlation_id=metadata.get("request_id") or uuid4(),
            payload={
                "organization_id": org,
                "agent_id": agent_id,
                "ssh_key_id": key.id if key else None,
                "fingerprint": key.fingerprint if key else None,
                "revision": key.revision if key else None,
                **metadata,
            },
        )
        self.outbox.stage(session=session, registry=EVENT_REGISTRY, event=event)

    def list_keys(self, org: UUID, page: int = 1, size: int = 100, search: str = "") -> tuple[list[SshCredential], int]:
        with Session(self.delegate.engine) as session:
            conditions = [SshCredential.organization_id == org]
            if search:
                conditions.append(col(SshCredential.name).ilike(f"%{search}%"))
            total = session.scalar(select(func.count()).select_from(SshCredential).where(*conditions)) or 0
            rows = session.exec(
                select(SshCredential)
                .where(*conditions)
                .order_by(col(SshCredential.created_at).desc())
                .offset((page - 1) * size)
                .limit(size)
            ).all()
            return list(rows), total

    def key(self, key_id: UUID, org: UUID) -> SshCredential | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(SshCredential).where(SshCredential.id == key_id, SshCredential.organization_id == org)
            ).first()

    def count_attachments(self, key_id: UUID, org: UUID) -> int:
        with Session(self.delegate.engine) as session:
            return (
                session.scalar(
                    select(func.count())
                    .select_from(AgentSshCredential)
                    .join(Agent)
                    .where(
                        AgentSshCredential.credential_id == key_id,
                        AgentSshCredential.organization_id == org,
                        col(Agent.deleted_at).is_(None),
                    )
                )
                or 0
            )

    def save_key(self, row: SshCredential, actor: ActorIdentity, expected_revision: int | None = None) -> SshCredential:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            if expected_revision is not None:
                existing = session.exec(
                    select(SshCredential)
                    .where(SshCredential.id == row.id, SshCredential.organization_id == row.organization_id)
                    .with_for_update()
                ).first()
                if existing is None or existing.revision != expected_revision:
                    raise HTTPException(409, "SSH credential changed; refresh and try again")
            session.merge(row)
            self._event(
                session,
                "ssh.key.created" if expected_revision is None else "ssh.key.changed",
                row.organization_id,
                actor,
                key=row,
            )
            session.commit()
        return row

    def delete_key(self, row: SshCredential, actor: ActorIdentity) -> None:
        with Session(self.delegate.engine) as session:
            # The FK also protects against concurrent assignment while deleting.
            session.exec(
                delete(AgentSshCredential).where(
                    col(AgentSshCredential.credential_id) == row.id,
                    col(AgentSshCredential.agent_id).in_(select(Agent.id).where(col(Agent.deleted_at).is_not(None))),
                )
            )
            existing = session.get(SshCredential, row.id)
            if existing is None:
                raise HTTPException(404, "SSH credential not found")
            self._event(session, "ssh.key.deleted", row.organization_id, actor, key=row)
            session.delete(existing)
            session.commit()

    def assigned(self, agent_id: UUID, scope: AuthorizationScope) -> list[SshCredential]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(SshCredential)
                    .join(AgentSshCredential)
                    .join(Agent)
                    .where(Agent.id == agent_id, *agent_scope_predicates(scope))
                    .order_by(col(SshCredential.id))
                ).all()
            )

    def runtime_keys(self, agent_id: UUID, org: UUID) -> list[SshCredential]:
        """Internal lifecycle only; the user caller has already authorized this Agent."""
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(SshCredential)
                    .join(AgentSshCredential)
                    .join(Agent)
                    .where(
                        Agent.id == agent_id,
                        Agent.organization_id == org,
                        col(Agent.deleted_at).is_(None),
                    )
                    .order_by(col(SshCredential.id))
                ).all()
            )

    def state(self, agent_id: UUID, org: UUID) -> SshRuntimeCredential | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(SshRuntimeCredential).where(
                    SshRuntimeCredential.agent_id == agent_id, SshRuntimeCredential.organization_id == org
                )
            ).first()

    def replace_assignments(
        self, agent_id: UUID, scope: AuthorizationScope, ids: list[UUID], revision: int, actor: ActorIdentity
    ) -> None:
        with Session(self.delegate.engine) as session:
            agent = session.exec(
                select(Agent).where(Agent.id == agent_id, *agent_scope_predicates(scope)).with_for_update()
            ).first()
            if agent is None:
                raise HTTPException(404, "Agent not found")
            state = session.exec(
                select(SshRuntimeCredential).where(SshRuntimeCredential.agent_id == agent_id).with_for_update()
            ).first()
            if (state.revision if state else 0) != revision:
                raise HTTPException(409, "SSH assignments changed; refresh and try again")
            keys = (
                list(
                    session.exec(
                        select(SshCredential).where(
                            col(SshCredential.id).in_(ids),
                            SshCredential.organization_id == scope.organization_id,
                        )
                    ).all()
                )
                if ids
                else []
            )
            if len(keys) != len(ids):
                raise HTTPException(404, "SSH credential not found")
            session.exec(delete(AgentSshCredential).where(col(AgentSshCredential.agent_id) == agent_id))
            for key in keys:
                session.add(
                    AgentSshCredential(agent_id=agent_id, organization_id=scope.organization_id, credential_id=key.id)
                )
            if state is None:
                state = SshRuntimeCredential(agent_id=agent_id, organization_id=scope.organization_id)
            state.revision += 1
            # Narrow the applied set immediately. Re-adding a removed key requires apply/restart.
            state.applied = [item for item in state.applied if item["id"] in {str(i) for i in ids}]
            session.add(state)
            self._event(session, "ssh.assignments.changed", scope.organization_id, actor, agent_id=agent_id)
            session.commit()

    def issue(self, agent_id: UUID, org: UUID, generation: UUID, keys: list[SshCredential]) -> str:
        value = "abssh_" + secrets.token_urlsafe(32)
        with Session(self.delegate.engine) as session:
            row = session.exec(select(SshRuntimeCredential).where(SshRuntimeCredential.agent_id == agent_id)).first()
            if row is None:
                row = SshRuntimeCredential(agent_id=agent_id, organization_id=org)
            row.token_hash, row.generation, row.revoked_at = token_digest(value), generation, None
            row.applied = [{"id": str(key.id), "revision": key.revision} for key in keys]
            session.add(row)
            session.commit()
        return value

    def revoke(self, agent_id: UUID, *, remove_assignments: bool = False) -> None:
        with Session(self.delegate.engine) as session:
            row = session.exec(select(SshRuntimeCredential).where(SshRuntimeCredential.agent_id == agent_id)).first()
            if row:
                row.revoked_at, row.token_hash = datetime.now(UTC), None
                session.add(row)
            if remove_assignments:
                session.exec(delete(AgentSshCredential).where(col(AgentSshCredential.agent_id) == agent_id))
            session.commit()

    def authorize(self, digest: str) -> tuple[SshRuntimeCredential, list[SshCredential]]:
        """Runtime boundary: identity and tenancy come only from persisted token ownership."""
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(SshRuntimeCredential)
                .join(Agent)
                .join(AgentIntegrationRuntime, col(AgentIntegrationRuntime.agent_id) == col(Agent.id))
                .where(
                    SshRuntimeCredential.token_hash == digest,
                    col(SshRuntimeCredential.revoked_at).is_(None),
                    SshRuntimeCredential.generation == AgentIntegrationRuntime.generation,
                    col(AgentIntegrationRuntime.state).in_(["provisioned", "ready"]),
                    Agent.status == AgentStatus.RUNNING,
                    col(Agent.deleted_at).is_(None),
                )
            ).first()
            if row is None:
                raise HTTPException(403, "SSH access is unavailable")
            ids = [UUID(item["id"]) for item in row.applied]
            keys = list(
                session.exec(
                    select(SshCredential)
                    .join(AgentSshCredential)
                    .where(
                        AgentSshCredential.agent_id == row.agent_id,
                        AgentSshCredential.organization_id == row.organization_id,
                        col(SshCredential.id).in_(ids),
                        SshCredential.enabled == True,
                    )
                    .order_by(col(SshCredential.id))
                ).all()
            )
            return row, keys

    def record_signing(
        self,
        state: SshRuntimeCredential,
        key: SshCredential | None,
        outcome: str,
        request_id: UUID,
        host_fingerprint: str | None = None,
    ) -> None:
        with Session(self.delegate.engine) as session:
            self._event(
                session,
                "ssh.signing." + outcome,
                state.organization_id,
                ActorIdentity(type=ActorIdentityType.RUNTIME, id=state.agent_id, organization_id=state.organization_id),
                agent_id=state.agent_id,
                key=key,
                request_id=request_id,
                outcome=outcome,
                host_fingerprint=host_fingerprint,
            )
            session.commit()

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.agents.service import AgentService, _refuse_during_managed_update
from api.domains.auth.models import CurrentUserContext
from api.domains.events import resolve_actor_identity
from api.domains.rbac.catalog import IMPLICIT_AGENT_OWNER_ROLES, PermissionKey
from api.domains.ssh.keys import fingerprint, prepare_key
from api.domains.ssh.models import (
    SshAssignmentsRead,
    SshAssignmentsUpdate,
    SshCredential,
    SshCredentialCreate,
    SshCredentialRead,
    SshCredentialUpdate,
)
from api.domains.ssh.repository import SshRepository
from api.infrastructure.crypto import encrypt_token


@inject
@singleton
@dataclass
class SshService:
    repository: SshRepository
    authorization: AgentAuthorization
    agents: AgentRepository
    lifecycle: AgentService
    config: Config

    def _org(self, context: CurrentUserContext, *, manage: bool = False) -> UUID:
        org = context.require_current_user_organization().organization_id
        if manage:
            context.require_org_role(org, IMPLICIT_AGENT_OWNER_ROLES, detail="Admin access required")
        return org

    def _key(self, key_id: UUID, org: UUID) -> SshCredential:
        row = self.repository.key(key_id, org)
        if row is None:
            raise HTTPException(404, "SSH credential not found")
        return row

    def _read(self, row: SshCredential, *, count: bool = False) -> SshCredentialRead:
        return SshCredentialRead(
            **row.model_dump(exclude={"private_key_encrypted", "organization_id", "created_by", "updated_at"}),
            agent_count=self.repository.count_attachments(row.id, row.organization_id) if count else 0,
        )

    def list_keys(self, context: CurrentUserContext, page: int, size: int, search: str) -> dict:
        rows, total = self.repository.list_keys(self._org(context), page, size, search)
        return {"items": [self._read(row, count=True) for row in rows], "total": total}

    def get_key(self, key_id: UUID, context: CurrentUserContext) -> SshCredentialRead:
        return self._read(self._key(key_id, self._org(context)), count=True)

    def create_key(self, data: SshCredentialCreate, context: CurrentUserContext) -> SshCredentialRead:
        org = self._org(context, manage=True)
        try:
            private, public, algorithm = prepare_key(
                data.private_key, data.passphrase, generate=data.source == "generate"
            )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        row = SshCredential(
            organization_id=org,
            name=data.name,
            private_key_encrypted=encrypt_token(private, self.config.agent_token_encryption_key),
            public_key=public,
            fingerprint=fingerprint(public),
            algorithm=algorithm,
            origin=data.source,
            mode=data.mode,
            servers=[s.model_dump() for s in data.servers],
            created_by=context.user.id,
        )
        try:
            self.repository.save_key(row, resolve_actor_identity(context, org))
        except IntegrityError:
            raise HTTPException(409, "An SSH credential with this name or public key already exists") from None
        return self._read(row)

    def update_key(self, key_id: UUID, data: SshCredentialUpdate, context: CurrentUserContext) -> SshCredentialRead:
        org = self._org(context, manage=True)
        row = self._key(key_id, org)
        row.name, row.enabled, row.mode = data.name, data.enabled, data.mode
        row.servers = [s.model_dump() for s in data.servers]
        row.revision = data.expected_revision + 1
        try:
            self.repository.save_key(row, resolve_actor_identity(context, org), data.expected_revision)
        except IntegrityError:
            raise HTTPException(409, "An SSH credential with this name already exists") from None
        return self._read(row, count=True)

    def delete_key(self, key_id: UUID, context: CurrentUserContext) -> None:
        org = self._org(context, manage=True)
        try:
            self.repository.delete_key(self._key(key_id, org), resolve_actor_identity(context, org))
        except IntegrityError:
            raise HTTPException(409, "Detach this SSH credential from all Agents before deleting it") from None

    def assignments(self, agent_id: UUID, context: CurrentUserContext) -> SshAssignmentsRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_READ)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
        keys = self.repository.assigned(agent_id, scope)
        state = self.repository.state(agent_id, agent.organization_id)
        applied = state.applied if state and state.token_hash and state.revoked_at is None else []
        current = [{"id": str(key.id), "revision": key.revision} for key in keys]
        actions = self.authorization.allowed_actions(context, [agent])[agent.id]
        return SshAssignmentsRead(
            credentials=[self._read(key) for key in keys],
            revision=state.revision if state else 0,
            applied_ids=[UUID(item["id"]) for item in applied] if agent.status == AgentStatus.RUNNING else [],
            pending_apply=(current != applied) or (bool(keys) and agent.status != AgentStatus.RUNNING),
            enabled=self.config.ssh_enabled,
            allowed_actions=["manage"] if {"agent.update", "agent.secret.manage"}.issubset(actions) else [],
        )

    def apply(self, agent_id: UUID, data: SshAssignmentsUpdate, context: CurrentUserContext) -> SshAssignmentsRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action(context, agent_id, PermissionKey.AGENT_SECRET_MANAGE)
        pod_id = agent.parent_agent_id or agent_id
        if data.restart:
            self.authorization.require_action(context, pod_id, PermissionKey.AGENT_LIFECYCLE_MANAGE)
        with self.agents.lifecycle_lock(pod_id) as acquired:
            if not acquired:
                raise HTTPException(409, "Agent already has a lifecycle operation in progress")
            agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_SECRET_MANAGE)
            pod = self.lifecycle.pod_of(agent)
            _refuse_during_managed_update(pod)
            if self.lifecycle.restore_points.has_blocking_operation(pod_id):
                raise HTTPException(409, "Agent has a restore operation in progress")
            scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_SECRET_MANAGE)
            state = self.repository.state(agent_id, agent.organization_id)
            if (state.revision if state else 0) != data.expected_revision:
                raise HTTPException(409, "SSH assignments changed; refresh and try again")
            keys = [self._key(key_id, agent.organization_id) for key_id in sorted(data.credential_ids)]
            previous = self.repository.assigned(agent_id, scope)
            additions = set(data.credential_ids) - {key.id for key in previous}
            if pod.status == AgentStatus.RUNNING and additions and not data.restart:
                raise HTTPException(409, "Adding SSH credentials to a running Agent requires Apply & Restart")
            actor = resolve_actor_identity(context, agent.organization_id)
            if data.restart:
                self.authorization.require_action(context, pod_id, PermissionKey.AGENT_LIFECYCLE_MANAGE)
                self.lifecycle._provision_and_start(agent, preflight=True, ssh_keys_override=keys)
                if pod_id != agent_id:
                    self.lifecycle._provision_and_start(pod, preflight=True)
                if pod.status == AgentStatus.RUNNING:
                    pod = self.lifecycle._stop_agent_unchecked(pod, actor)
            self.repository.replace_assignments(agent_id, scope, data.credential_ids, data.expected_revision, actor)
            if data.restart:
                self.lifecycle._start_agent_unchecked(pod, actor)
        return self.assignments(agent_id, context)

from __future__ import annotations

import hashlib
import json
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
from api.domains.custom_api.models import (
    CustomApiConnection,
    CustomApiConnectionApply,
    CustomApiConnectionCreate,
    CustomApiConnectionRead,
    CustomApiConnectionsApply,
    CustomApiConnectionUpdate,
    HeaderRead,
    requires_isolation,
    validate_credentials,
)
from api.domains.custom_api.repository import CustomApiRepository
from api.domains.custom_api.request import RequestRefused, TokenExchangeFailed, fetch_access_token, parse_url
from api.domains.events import resolve_actor_identity
from api.domains.integrations.repository import IntegrationRepository
from api.domains.rbac.catalog import PermissionKey
from api.infrastructure.crypto import decrypt_token, encrypt_token


@inject
@singleton
@dataclass
class CustomApiService:
    repository: CustomApiRepository
    authorization: AgentAuthorization
    agents: AgentRepository
    lifecycle: AgentService
    integrations: IntegrationRepository
    config: Config

    def _credentials(self, row: CustomApiConnection) -> dict:
        return json.loads(decrypt_token(row.credentials_encrypted, self.config.agent_token_encryption_key))

    def _read(self, row: CustomApiConnection) -> CustomApiConnectionRead:
        config = self._credentials(row)
        runtime = self.integrations.runtime(row.agent_id)
        applied = runtime.bindings.get("custom_api:" + row.slug) if runtime and runtime.state == "ready" else None
        if applied and runtime and (applied.get("binding_id") != str(row.id) or runtime.generation != row.generation):
            applied = None
        return CustomApiConnectionRead(
            id=row.id,
            slug=row.slug,
            name=row.name,
            base_url=row.base_url,
            isolated=row.isolated,
            applied_isolated=applied.get("isolated") if applied else None,
            pending_apply=not applied
            or applied.get("revision") != hashlib.sha256(row.credentials_encrypted.encode()).hexdigest()
            or applied.get("isolated") != row.isolated
            or applied.get("base_url") != row.base_url,
            auth_type=config["auth"]["type"],
            auth_header_name=config["auth"].get("header_name"),
            auth_token_url=config["auth"].get("token_url"),
            headers=[
                HeaderRead(name=h["name"], secret=h["secret"], value=None if h["secret"] else h["value"])
                for h in config["headers"]
            ],
        )

    def list_connections(self, agent_id: UUID, context: CurrentUserContext) -> list[CustomApiConnectionRead]:
        agent = self.authorization.require_visible(context, agent_id)
        self.lifecycle._observe_integration_readiness(agent)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
        return [self._read(row) for row in self.repository.list_in_scope(agent_id, scope)]

    def _find(self, agent_id: UUID, connection_id: UUID, context: CurrentUserContext) -> CustomApiConnection:
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
        row = next((row for row in self.repository.list_in_scope(agent_id, scope) if row.id == connection_id), None)
        if row is None:
            raise HTTPException(404, "Custom API connection not found")
        return row

    def _require_editable(self, agent_id: UUID, context: CurrentUserContext) -> None:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        _refuse_during_managed_update(agent)
        if agent.status == AgentStatus.RUNNING:
            raise HTTPException(409, "Stop the Agent before editing Custom API connections; start it to apply changes")
        if self.lifecycle.restore_points.has_blocking_operation(agent_id):
            raise HTTPException(409, "An Agent restore operation is in progress")

    def apply_many(
        self, agent_id: UUID, data: CustomApiConnectionsApply, context: CurrentUserContext, *, preflight: bool = False
    ) -> list[CustomApiConnectionRead]:
        self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action(context, agent_id, PermissionKey.AGENT_SECRET_MANAGE)
        with self.agents.lifecycle_lock(agent_id) as acquired:
            if not acquired:
                raise HTTPException(409, "An Agent lifecycle operation is already in progress")
            scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
            rows = {row.id: row for row in self.repository.list_in_scope(agent_id, scope)}
            targets = [update.id for update in data.updates] + data.deletes
            if len(targets) != len(set(targets)):
                raise HTTPException(422, "Each connection may only be changed once")
            if any(target not in rows for target in targets):
                raise HTTPException(404, "Custom API connection not found")
            changes: list[tuple[CustomApiConnection, str]] = [(rows.pop(key), "deleted") for key in data.deletes]
            for update in data.updates:
                row = rows[update.id]
                self._prepare_update(row, update.data)
                changes.append((row, "updated"))
            for create in data.creates:
                row = self._new_connection(agent_id, create)
                rows[row.id] = row
                changes.append((row, "created"))
            slugs = [row.slug for row in rows.values()]
            if len(slugs) != len(set(slugs)):
                raise HTTPException(
                    409, "This connection name produces an identifier already in use. Choose another name."
                )
            self._apply_changes_locked(agent_id, changes, context, data.restart, preflight=preflight)
            return [] if preflight else self.list_connections(agent_id, context)

    def _new_connection(self, agent_id: UUID, data: CustomApiConnectionCreate) -> CustomApiConnection:
        config = {"auth": data.auth.model_dump(exclude_none=True), "headers": [h.model_dump() for h in data.headers]}
        self._validate(config, data.base_url, data.isolated, check_credentials=True)
        return CustomApiConnection(
            agent_id=agent_id,
            slug=data.slug,
            name=data.name,
            base_url=data.base_url,
            isolated=data.isolated,
            credentials_encrypted=encrypt_token(json.dumps(config), self.config.agent_token_encryption_key),
        )

    def create(
        self, agent_id: UUID, data: CustomApiConnectionCreate, context: CurrentUserContext
    ) -> CustomApiConnectionRead:
        self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        with self.agents.lifecycle_lock(agent_id) as acquired:
            if not acquired:
                raise HTTPException(409, "An Agent lifecycle operation is already in progress")
            scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
            if any(row.slug == data.slug for row in self.repository.list_in_scope(agent_id, scope)):
                raise HTTPException(
                    409, "This connection name produces an identifier already in use. Choose another name."
                )
            row = self._new_connection(agent_id, data)
            try:
                self._apply_locked(row, context, "created", data.restart)
                return self._read(row)
            except IntegrityError:
                raise HTTPException(
                    409, "This connection name produces an identifier already in use. Choose another name."
                ) from None

    def update(
        self, agent_id: UUID, connection_id: UUID, data: CustomApiConnectionUpdate, context: CurrentUserContext
    ) -> CustomApiConnectionRead:
        self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        with self.agents.lifecycle_lock(agent_id) as acquired:
            if not acquired:
                raise HTTPException(409, "An Agent lifecycle operation is already in progress")
            self._require_editable(agent_id, context)
            row = self._find(agent_id, connection_id, context)
            self._prepare_update(row, data)
            self._persist(row, context, "updated")
            return self._read(row)

    def _prepare_update(self, row: CustomApiConnection, data: CustomApiConnectionUpdate) -> None:
        config = self._credentials(row)
        if data.auth is not None:
            auth = data.auth.model_dump(exclude_none=True)
            previous = config["auth"]
            # Saved secrets carry over only within the same scheme and the same place they
            # are sent to: a new header name or token URL needs its credentials entered again.
            if (
                auth["type"] == previous["type"]
                and (
                    auth["type"] != "api_key"
                    or auth.get("header_name", "").lower() == previous.get("header_name", "").lower()
                )
                and (auth["type"] != "oauth2_client_credentials" or auth.get("token_url") == previous.get("token_url"))
            ):
                auth = {**previous, **auth}
            config["auth"] = auth
        if data.headers is not None:
            previous_headers = {h["name"].lower(): h for h in config["headers"]}
            headers = []
            for h in data.headers:
                value = h.value
                old = previous_headers.get(h.name.lower())
                if value is None and h.secret and old and old["secret"]:
                    value = old["value"]
                headers.append({"name": h.name, "value": value, "secret": h.secret})
            config["headers"] = headers
        for field in ("name", "base_url", "isolated"):
            if field in data.model_fields_set:
                value = getattr(data, field)
                if value is None:
                    raise HTTPException(422, f"{field} cannot be null")
                setattr(row, field, value)
        self._validate(config, row.base_url, row.isolated, check_credentials=data.auth is not None)
        row.credentials_encrypted = encrypt_token(json.dumps(config), self.config.agent_token_encryption_key)
        row.token_hash = None
        row.generation = None

    def delete(self, agent_id: UUID, connection_id: UUID, context: CurrentUserContext, restart: bool = False) -> None:
        self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        with self.agents.lifecycle_lock(agent_id) as acquired:
            if not acquired:
                raise HTTPException(409, "An Agent lifecycle operation is already in progress")
            row = self._find(agent_id, connection_id, context)
            self._apply_locked(row, context, "deleted", restart)

    @staticmethod
    def _validate(config: dict, base_url: str, isolated: bool, *, check_credentials: bool) -> None:
        try:
            parse_url(base_url, base=True)
            validate_credentials(config)
        except RequestRefused, KeyError, TypeError:
            raise HTTPException(422, "Invalid Custom API authentication, headers or base URL") from None
        if not requires_isolation(config):
            return
        if not isolated:
            raise HTTPException(
                422,
                "OAuth2 client credentials require credential isolation; the Agent never receives the client secret",
            )
        if check_credentials:
            # The other schemes are checked only for shape, because any request can carry them.
            # A client-credentials grant is worth one token request at save time: a wrong
            # secret would otherwise surface only as the Agent's first failed call.
            try:
                fetch_access_token(config["auth"])
            except (TokenExchangeFailed, RequestRefused) as exc:
                raise HTTPException(422, f"OAuth2 client credentials could not be verified: {exc}") from None

    def apply(
        self, agent_id: UUID, connection_id: UUID, data: CustomApiConnectionApply, context: CurrentUserContext
    ) -> CustomApiConnectionRead:
        self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        with self.agents.lifecycle_lock(agent_id) as acquired:
            if not acquired:
                raise HTTPException(409, "An Agent lifecycle operation is already in progress")
            row = self._find(agent_id, connection_id, context)
            self._prepare_update(row, data)
            self._apply_locked(row, context, "applied", data.restart)
            return self._read(row)

    def _apply_locked(
        self, row: CustomApiConnection, context: CurrentUserContext, operation: str, restart: bool
    ) -> None:
        self._apply_changes_locked(row.agent_id, [(row, operation)], context, restart)

    def _apply_changes_locked(
        self,
        agent_id: UUID,
        changes: list[tuple[CustomApiConnection, str]],
        context: CurrentUserContext,
        restart: bool,
        *,
        preflight: bool = False,
    ) -> None:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        self.lifecycle.restore_points.reconcile_agent(agent.id)
        _refuse_during_managed_update(agent)
        if self.lifecycle.restore_points.has_blocking_operation(agent.id):
            raise HTTPException(409, "An Agent restore operation is in progress")
        running = agent.status == AgentStatus.RUNNING
        if running or restart:
            self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_LIFECYCLE_MANAGE)
        if running and not restart:
            raise HTTPException(409, "Applying to a running Agent requires an explicit restart")
        try:
            self.lifecycle._provision_and_start(
                agent,
                preflight=True,
                custom_api_overrides={row.id: None if operation == "deleted" else row for row, operation in changes},
            )
        except ValueError, TypeError:
            raise HTTPException(400, "Invalid Custom API runtime configuration") from None
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, "The resulting Agent configuration could not be prepared") from None
        if preflight or not changes:
            return
        actor = resolve_actor_identity(context, agent.organization_id)
        if running:
            self.lifecycle._observe_integration_readiness(agent)
            agent = self.lifecycle._stop_agent_unchecked(agent, actor)
        elif agent.status == AgentStatus.ERROR and restart:
            name = f"agent-{agent.id}"
            self.lifecycle.k8s.delete_deployment(name, self.lifecycle.config.k8s_namespace)
            self.lifecycle.k8s.wait_for_termination(name, self.lifecycle.config.k8s_namespace)
            self.lifecycle.credential_gateway.revoke_for_agent(agent.id, agent.organization_id)
        try:
            deliveries = self.repository.mutate_many_with_events(
                changes, actor, context.user.full_name or context.user.email
            )
        except IntegrityError:
            raise HTTPException(409, "A connection identifier is already in use") from None
        self.lifecycle.event_delivery_dispatcher.enqueue_immediate(deliveries)
        if running or restart:
            self.lifecycle._start_agent_unchecked(agent, actor)

    def _persist(self, row: CustomApiConnection, context: CurrentUserContext, operation: str) -> None:
        agent = self.authorization.require_visible(context, row.agent_id)
        deliveries = self.repository.mutate_with_event(
            row,
            resolve_actor_identity(context, agent.organization_id),
            context.user.full_name or context.user.email,
            operation,
        )
        self.lifecycle.event_delivery_dispatcher.enqueue_immediate(deliveries)

"""MCP servers seen from one Agent: the Organization's it may use, its attachments and own
credentials for them, and its own Agent MCP Servers.

Kept apart from `service.py` because it depends on the Agent lifecycle, and the Agent start
path depends on this domain's repository and runtime modules.
"""

import json
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent, AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.agents.service import AgentService, _refuse_during_managed_update
from api.domains.auth.models import CurrentUserContext
from api.domains.events import resolve_actor_identity
from api.domains.integrations.repository import IntegrationRepository
from api.domains.mcp_servers import runtime as mcp_runtime
from api.domains.mcp_servers.broker import McpCredentialBroker, is_oauth
from api.domains.mcp_servers.models import (
    AgentMcpCredentialUpdate,
    AgentMcpServerCreate,
    AgentMcpServerRead,
    AgentMcpServersRead,
    AgentMcpServersUpdate,
    AgentMcpServerUpdate,
    McpAgentCredentialRead,
    McpCredentialKind,
    McpCredentialStatus,
    McpHeaderRead,
    McpServerProbeRead,
    McpServerProbeRequest,
    McpServerRead,
    McpServerScope,
    OrganizationMcpServer,
)
from api.domains.mcp_servers.repository import McpServerRepository
from api.domains.mcp_servers.service import McpServerService, _header, _merged_auth
from api.domains.mcp_servers.sign_in import RESTRICTED_DENIED
from api.domains.rbac.catalog import PermissionKey
from api.infrastructure.crypto import decrypt_token, encrypt_token


@inject
@singleton
@dataclass
class AgentMcpServerService:
    repository: McpServerRepository
    authorization: AgentAuthorization
    agents: AgentRepository
    lifecycle: AgentService
    integrations: IntegrationRepository
    broker: McpCredentialBroker
    servers: McpServerService

    def read(self, agent_id: UUID, context: CurrentUserContext) -> AgentMcpServersRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_READ)
        return self._read(agent, context)

    def update(self, agent_id: UUID, data: AgentMcpServersUpdate, context: CurrentUserContext) -> AgentMcpServersRead:
        """Saves the Agent's complete set of Selected Agents attachments.

        A running Agent may be saved without a restart: a removal takes effect at the gateway
        at once, and an addition is reported as pending until the Agent next starts.
        """
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        if data.restart:
            self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_LIFECYCLE_MANAGE)
        servers = {server.id: server for server in self.repository.list_for_organization(agent.organization_id)}
        wanted = set(data.attached_server_ids)
        unknown = [
            server_id
            for server_id in wanted
            if server_id not in servers or servers[server_id].scope != McpServerScope.SELECTED_AGENTS.value
        ]
        if unknown:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Only this Organization's Selected Agents MCP servers can be attached to an Agent.",
            )
        with self.agents.lifecycle_lock(agent.id) as acquired:
            if not acquired:
                raise HTTPException(status.HTTP_409_CONFLICT, "An Agent lifecycle operation is already in progress")
            agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
            _refuse_during_managed_update(agent)
            self.lifecycle.restore_points.reconcile_agent(agent.id)
            if self.lifecycle.restore_points.has_blocking_operation(agent.id):
                raise HTTPException(status.HTTP_409_CONFLICT, "An Agent restore operation is in progress")
            # Attachments to servers now scoped to All Agents are kept as they are, so a later
            # switch back to Selected Agents restores them.
            current = self.repository.attached_server_ids(agent.id)
            selected = {
                sid for sid in current if sid in servers and servers[sid].scope == McpServerScope.SELECTED_AGENTS.value
            }
            target = (current - selected) | wanted
            if any(servers[sid].restricted for sid in selected ^ wanted) and not self.servers._is_manager(
                context, agent.organization_id
            ):
                raise HTTPException(status.HTTP_403_FORBIDDEN, RESTRICTED_DENIED)
            actor = resolve_actor_identity(context, agent.organization_id)
            if target != current:
                names = lambda ids: sorted(servers[sid].identifier for sid in ids if sid in servers)
                deliveries = self.repository.replace_attachments_with_event(
                    agent,
                    target,
                    previous=names(current),
                    current=names(target),
                    actor=actor,
                    actor_display=context.user.full_name or context.user.email,
                )
                self.lifecycle.event_delivery_dispatcher.enqueue_immediate(deliveries)
            if data.restart:
                agent = self._restart(agent, actor)
        return self._read(self.agents.get_by_id(agent.id) or agent, context)

    def set_credential(
        self, agent_id: UUID, server_id: UUID, data: AgentMcpCredentialUpdate, context: CurrentUserContext
    ) -> AgentMcpServersRead:
        """Saves the Agent's own token and headers for a token-based server, after checking them.

        A secret left out keeps the Agent's saved one under the same rules as the server's.
        """
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        server = self.repository.get(agent.organization_id, server_id)
        if server is None or server.agent_id is not None:
            # An Agent server's credential is the server's own; it is edited with the server.
            raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP server not found")
        if server.restricted and not self.servers._is_manager(context, agent.organization_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, RESTRICTED_DENIED)
        if is_oauth(self.broker.server_config(server)):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, "This server uses an OAuth sign-in; sign the Agent in instead."
            )
        held = self.repository.credential(server.id, agent.id)
        previous: dict = (
            json.loads(decrypt_token(held.credentials_encrypted, self.lifecycle.config.agent_token_encryption_key))
            if held is not None and held.kind == McpCredentialKind.STATIC.value
            else {"auth": {"type": "none"}, "headers": []}
        )
        saved = {h["name"].lower(): h for h in previous["headers"]}
        config = {
            "auth": _merged_auth(previous["auth"], data.auth.model_dump(exclude_none=True)),
            "headers": [_header(h, saved.get(h.name.lower())) for h in data.headers],
        }
        # Checked against the live server like an Organization credential.
        self.servers.check_connection(server.url, config)
        deliveries = self.repository.put_credential_with_event(
            server,
            agent,
            kind=McpCredentialKind.STATIC.value,
            credentials_encrypted=encrypt_token(json.dumps(config), self.lifecycle.config.agent_token_encryption_key),
            user_id=context.user.id,
            actor=resolve_actor_identity(context, agent.organization_id),
            actor_display=context.user.full_name or context.user.email,
        )
        self.lifecycle.event_delivery_dispatcher.enqueue_immediate(deliveries)
        return self._read(agent, context)

    # --- the Agent's own servers ---------------------------------------------

    def _editable_agent(self, agent_id: UUID, context: CurrentUserContext) -> Agent:
        """Adding, changing or removing an Agent server takes what changing the Agent's secrets
        takes. No Organization switch gates it: an Agent that runs code can reach any public MCP
        server with a credential of its own anyway, so refusing the managed path would protect
        nothing."""
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        return agent

    def _own_server(self, agent: Agent, server_id: UUID) -> OrganizationMcpServer:
        server = self.repository.get(agent.organization_id, server_id)
        if server is None or server.agent_id != agent.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "MCP server not found")
        return server

    def create_own(self, agent_id: UUID, data: AgentMcpServerCreate, context: CurrentUserContext) -> McpServerRead:
        """A running Agent lists the new server after its next start."""
        agent = self._editable_agent(agent_id, context)
        return self.servers._create(agent.organization_id, data, context, agent=agent)

    def update_own(
        self, agent_id: UUID, server_id: UUID, data: AgentMcpServerUpdate, context: CurrentUserContext
    ) -> McpServerRead:
        agent = self._editable_agent(agent_id, context)
        server = self._own_server(agent, server_id)
        self.servers._update(server, data, context)
        return self.servers._read(server, None, manager=True, agent_name=agent.name)

    def delete_own(self, agent_id: UUID, server_id: UUID, context: CurrentUserContext) -> None:
        """The Agent loses it at the gateway at once."""
        agent = self._editable_agent(agent_id, context)
        self.servers._delete(self._own_server(agent, server_id), context)

    def probe_own_new(
        self, agent_id: UUID, data: McpServerProbeRequest, context: CurrentUserContext
    ) -> McpServerProbeRead:
        self._editable_agent(agent_id, context)
        return self.servers._probe_new(data, agent=True)

    def probe_own_saved(
        self, agent_id: UUID, server_id: UUID, data: AgentMcpServerUpdate | None, context: CurrentUserContext
    ) -> McpServerProbeRead:
        agent = self._editable_agent(agent_id, context)
        return self.servers._probe_saved(self._own_server(agent, server_id), data)

    def _can(self, context: CurrentUserContext, agent: Agent, *permissions: PermissionKey) -> bool:
        try:
            for permission in permissions:
                self.authorization.require_action_for_visible(context, agent, permission)
        except HTTPException:
            return False
        return True

    def _credential_shape(self, row) -> McpAgentCredentialRead | None:
        if row is None or row.kind != McpCredentialKind.STATIC.value:
            return None
        config = json.loads(decrypt_token(row.credentials_encrypted, self.lifecycle.config.agent_token_encryption_key))
        return McpAgentCredentialRead(
            auth_type=config["auth"]["type"],
            auth_header_name=config["auth"].get("header_name"),
            headers=[
                McpHeaderRead(name=h["name"], secret=h["secret"], value=None if h["secret"] else h["value"])
                for h in config["headers"]
            ],
        )

    def _restart(self, agent: Agent, actor) -> Agent:
        if agent.status == AgentStatus.RUNNING:
            self.lifecycle._observe_integration_readiness(agent)
            agent = self.lifecycle._stop_agent_unchecked(agent, actor)
        elif agent.status == AgentStatus.ERROR:
            name = f"agent-{agent.id}"
            self.lifecycle.k8s.delete_deployment(name, self.lifecycle.config.k8s_namespace)
            self.lifecycle.k8s.wait_for_termination(name, self.lifecycle.config.k8s_namespace)
            self.lifecycle.credential_gateway.revoke_for_agent(agent.id, agent.organization_id)
        return self.lifecycle._start_agent_unchecked(agent, actor)

    def _read(self, agent: Agent, context: CurrentUserContext) -> AgentMcpServersRead:
        servers = self.repository.list_for_organization(agent.organization_id)
        attached = self.repository.attached_server_ids(agent.id)
        effective_servers = self.repository.effective_for_agent(agent.id)
        effective = {server.id for server in effective_servers}
        pending = False
        if agent.status == AgentStatus.RUNNING:
            runtime = self.integrations.runtime(agent.id)
            started = mcp_runtime.started_identifiers(runtime.bindings) if runtime else set()
            pending = started != {server.identifier for server in effective_servers}
        held = self.repository.credentials_for(agent.organization_id, agent.id)
        own = {row.mcp_server_id: row for row in held if row.agent_id == agent.id}
        organization = {row.mcp_server_id: row for row in held if row.agent_id is None}
        reads = []
        for server in servers:
            auth_type = self.broker.server_config(server)["auth"]["type"]
            row = own.get(server.id)
            if row is not None:
                source = "agent"
            elif auth_type != "oauth" or server.id in organization:
                source = "organization"
                row = organization.get(server.id)
            else:
                source = "missing"
            reads.append(
                AgentMcpServerRead(
                    id=server.id,
                    identifier=server.identifier,
                    name=server.name,
                    description=server.description,
                    scope=server.scope,
                    enabled=server.enabled,
                    restricted=server.restricted,
                    attached=server.id in attached,
                    active=server.id in effective,
                    auth_type=auth_type,
                    credential_source=source,
                    needs_sign_in=source == "missing"
                    or (row is not None and row.status == McpCredentialStatus.NEEDS_SIGN_IN.value),
                    has_agent_credential=server.id in own,
                    agent_credential=self._credential_shape(own.get(server.id)),
                )
            )
        editor = self._can(context, agent, PermissionKey.AGENT_UPDATE, PermissionKey.AGENT_SECRET_MANAGE)
        own_servers = [
            self.servers._read(server, None, manager=editor, agent_name=agent.name)
            for server, _ in self.repository.list_agent_servers(agent.organization_id, agent.id)
        ]
        return AgentMcpServersRead(
            servers=reads,
            agent_servers=own_servers,
            can_manage_restricted=self.servers._is_manager(context, agent.organization_id),
            pending_restart=pending,
        )

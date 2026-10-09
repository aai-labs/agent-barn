"""Authorized, serialized isolation apply; failures retain desired intent for retry."""

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException
from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import AgentRead, AgentStatus, IntegrationIsolationUpdate, SecretProvider
from api.domains.agents.repository import AgentRepository
from api.domains.agents.service import AgentService
from api.domains.auth.models import CurrentUserContext
from api.domains.events import resolve_actor_identity
from api.domains.integrations.repository import IntegrationRepository
from api.domains.integrations.runtime import select_egress_mode
from api.domains.rbac.catalog import PermissionKey


@inject
@singleton
@dataclass
class IntegrationIsolationService:
    authorization: AgentAuthorization
    agents: AgentService
    agent_repository: AgentRepository
    repository: IntegrationRepository

    def apply(
        self, agent_id: UUID, provider: SecretProvider, data: IntegrationIsolationUpdate, context: CurrentUserContext
    ) -> AgentRead:
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_SECRET_MANAGE)
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_UPDATE)
        try:
            select_egress_mode(provider, isolated=data.isolated)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        self.agents.restore_points.reconcile_agent(agent.id)
        with self.agent_repository.lifecycle_lock(agent.id) as acquired:
            if not acquired:
                raise HTTPException(409, "An Agent lifecycle operation is already in progress")
            current = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_SECRET_MANAGE)
            self.authorization.require_action_for_visible(context, current, PermissionKey.AGENT_UPDATE)
            if self.agents.restore_points.has_blocking_operation(agent_id):
                raise HTTPException(409, "An Agent restore operation is in progress")
            if self.agent_repository.get_secret(agent_id, provider) is None and (
                provider != SecretProvider.FIRECRAWL
                or not (self.agents.config.agent_firecrawl_api_key and self.agents.config.agent_firecrawl_base_url)
            ):
                raise HTTPException(404, "Integration not configured")
            running = current.status == AgentStatus.RUNNING
            if data.restart:
                self.authorization.require_action_for_visible(context, current, PermissionKey.AGENT_LIFECYCLE_MANAGE)
            if running:
                self.authorization.require_action_for_visible(context, current, PermissionKey.AGENT_LIFECYCLE_MANAGE)
                if not data.restart:
                    raise HTTPException(409, "Applying isolation to a running Agent requires an explicit restart")
            try:
                self.agents._provision_and_start(current, preflight=True, isolation_overrides={provider: data.isolated})
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, f"Invalid {provider.value} runtime configuration") from exc
            except HTTPException:
                raise
            except Exception as exc:
                raise HTTPException(400, "The resulting Agent configuration could not be prepared") from exc
            actor = resolve_actor_identity(context, current.organization_id)
            if running:
                # Capture a healthy ordinary Start before replacing its generation.
                self.agents._observe_integration_readiness(current)
                current = self.agents._stop_agent_unchecked(current, actor)
            elif current.status == AgentStatus.ERROR and data.restart:
                name = f"agent-{agent_id}"
                self.agents.k8s.delete_deployment(name, self.agents.config.k8s_namespace)
                self.agents.k8s.wait_for_termination(name, self.agents.config.k8s_namespace)
                self.agents.credential_gateway.revoke_for_agent(agent_id, current.organization_id)
            source = "agent_secret" if self.agent_repository.get_secret(agent_id, provider) else "platform_default"
            deliveries = self.repository.set_policy(
                agent_id,
                provider,
                data.isolated,
                source,
                actor=actor,
                actor_display=context.user.full_name or context.user.email,
            )
            self.agents.event_delivery_dispatcher.enqueue_immediate(deliveries)
            if running or data.restart:
                self.authorization.require_action_for_visible(context, current, PermissionKey.AGENT_LIFECYCLE_MANAGE)
                current = self.agents._start_agent_unchecked(current, actor)
                # Scheduling, volume attach and image pulls continue independently.
                # A created deployment is provisioned, never assumed ready.
        return self.agents._get_agent_read(current, context)

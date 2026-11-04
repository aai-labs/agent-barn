"""Apply one Integrations form under the Agent lifecycle lock."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError

from api.domains.agents.models import Agent, AgentRead, AgentStatus, SecretProvider
from api.domains.agents.service import AgentService, _refuse_during_managed_update
from api.domains.auth.models import CurrentUserContext
from api.domains.custom_api.service import CustomApiService
from api.domains.events import resolve_actor_identity
from api.domains.integrations.isolation import default_isolation
from api.domains.integrations.models import AgentIntegrationsApply
from api.domains.integrations.runtime import select_egress_mode
from api.domains.rbac.catalog import PermissionKey


@inject
@singleton
@dataclass
class IntegrationSetupService:
    agents: AgentService
    custom_api: CustomApiService

    def apply(self, agent_id: UUID, data: AgentIntegrationsApply, context: CurrentUserContext) -> AgentRead:
        authorization = self.agents.authorization
        agent = authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_SECRET_MANAGE)
        self.agents.restore_points.reconcile_agent(agent.id)
        with self.agents.repository.lifecycle_lock(agent.id) as acquired:
            if not acquired:
                raise HTTPException(409, "An Agent lifecycle operation is already in progress")
            current = authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
            authorization.require_action_for_visible(context, current, PermissionKey.AGENT_SECRET_MANAGE)
            _refuse_during_managed_update(current)
            if self.agents.restore_points.has_blocking_operation(agent_id):
                raise HTTPException(409, "An Agent restore operation is in progress")
            running = current.status == AgentStatus.RUNNING
            if running or data.restart:
                authorization.require_action_for_visible(context, current, PermissionKey.AGENT_LIFECYCLE_MANAGE)
            if running and not data.restart:
                raise HTTPException(409, "Applying to a running Agent requires an explicit restart")

            changes = self.custom_api._prepare_changes(agent_id, data.custom_api, context)
            policies = {policy.provider: policy.isolated for policy in data.policies}
            try:
                for provider, isolated in policies.items():
                    select_egress_mode(provider, isolated=isolated)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
            actor = resolve_actor_identity(context, current.organization_id)

            def before_save(agent: Agent, credentials: dict[SecretProvider, Any]) -> Agent:
                stored_providers = {
                    SecretProvider(secret.provider) for secret in self.agents.repository.get_secrets_for_agent(agent_id)
                }
                providers = (stored_providers - set(data.removed_secret_providers)) | credentials.keys()
                effective_policies = {
                    provider: default_isolation(provider) for provider in credentials.keys() - stored_providers
                }
                effective_policies.update(policies)
                if self.agents.config.agent_firecrawl_api_key and self.agents.config.agent_firecrawl_base_url:
                    providers.add(SecretProvider.FIRECRAWL)
                if policies.keys() - providers:
                    raise HTTPException(404, "Integration not configured")
                try:
                    self.agents._provision_and_start(
                        agent,
                        preflight=True,
                        credential_overrides=credentials,
                        removed_providers=data.removed_secret_providers,
                        isolation_overrides=effective_policies,
                        custom_api_overrides={
                            row.id: None if operation == "deleted" else row for row, operation in changes
                        },
                    )
                except ValueError, TypeError:
                    raise HTTPException(400, "Invalid integration runtime configuration") from None

                if running:
                    self.agents._observe_integration_readiness(agent)
                    return self.agents._stop_agent_unchecked(agent, actor)
                if agent.status == AgentStatus.ERROR and data.restart:
                    name = f"agent-{agent_id}"
                    self.agents.k8s.delete_deployment(name, self.agents.config.k8s_namespace)
                    self.agents.k8s.wait_for_termination(name, self.agents.config.k8s_namespace)
                    self.agents.credential_gateway.revoke_for_agent(agent_id, agent.organization_id)
                return agent

            self.agents._update_agent_locked(agent_id, data.credential_update(), context, before_save=before_save)
            # All rejection checks above are read-only. Persistence or infrastructure
            # failures after stop retain the stopped/error state for an explicit retry.
            display = context.user.full_name or context.user.email
            try:
                deliveries = (
                    self.custom_api.repository.mutate_many_with_events(changes, actor, display) if changes else []
                )
            except IntegrityError:
                raise HTTPException(409, "A connection identifier is already in use") from None
            for provider, isolated in policies.items():
                source = "agent_secret" if self.agents.repository.get_secret(agent_id, provider) else "platform_default"
                deliveries += self.agents.integrations.set_policy(
                    agent_id, provider, isolated, source, actor=actor, actor_display=display
                )
            self.agents.event_delivery_dispatcher.enqueue_immediate(deliveries)
            current = authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
            if data.restart:
                current = self.agents._start_agent_unchecked(current, actor)
        return self.agents._get_agent_read(current, context)

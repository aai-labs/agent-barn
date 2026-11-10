"""Tier Holds: what an Organization's Tier no longer covers is stopped, never deleted.

Holds apply as soon as an Organization's coverage drops: a Platform Administrator puts it on
a lower Tier, or edits its Tier down. The oldest Agents are kept up to the Agent Limit, and
Connections, Agent Memory and Agent Webhooks the Tier leaves out are switched off. Owners and
Admins then choose what to keep: they hold an Agent to free its place and release another.
A held Connection, Agent Webhook or Agent Memory is released by enabling it again, which the
Tier Entitlement check allows once the Tier covers it. Nothing is released automatically.
"""

import logging
from dataclasses import dataclass, replace
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.service import AgentService
from api.domains.auth.models import CurrentUserContext
from api.domains.events import ActorIdentity, EventDeliveryDispatcher, resolve_actor_identity
from api.domains.onboarding.settings_service import TrialSettingsService
from api.domains.organizations.lookup import OrganizationLookupService
from api.domains.organizations.settings_service import OrganizationSettingsService
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.domains.tiers.models import Tier, TierHoldPreviewRead, TierHoldsRead
from api.domains.tiers.repository import TierHoldChange, TierRepository

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class TierHoldService:
    repository: TierRepository
    agents: AgentService
    authorization: AgentAuthorization
    permission_policy: PermissionPolicy
    organization_lookup: OrganizationLookupService
    trial_settings: TrialSettingsService
    organization_settings: OrganizationSettingsService
    event_delivery_dispatcher: EventDeliveryDispatcher

    def apply(self, organization_id: UUID, *, actor: ActorIdentity, actor_display: str) -> TierHoldChange:
        """Hold what the Organization's Tier no longer covers."""
        limit = self._agent_limit(organization_id)
        change = self.repository.apply_holds(
            organization_id, limit if limit is not None else 0, actor=actor, actor_display=actor_display
        )
        self._settle(change, actor)
        return change

    def apply_for_tier(self, tier_id: UUID, context: CurrentUserContext) -> None:
        """Hold, in every Organization on a Tier just edited, what it no longer covers."""
        for organization_id in self.repository.organizations_on(tier_id):
            self.apply(
                organization_id,
                actor=resolve_actor_identity(context, organization_id),
                actor_display=context.user.full_name or context.user.email,
            )

    def list_holds(self, organization_id: UUID, context: CurrentUserContext) -> TierHoldsRead:
        self._require_manage(organization_id, context)
        return self.repository.list_holds(organization_id)

    def hold_agent(self, organization_id: UUID, agent_id: UUID, context: CurrentUserContext) -> TierHoldsRead:
        """Put an Agent on hold by choice, stopping it, so another can be released in its place."""
        actor = self._require_agent(organization_id, agent_id, context)
        change = self.repository.hold_agent(
            organization_id, agent_id, actor=actor, actor_display=context.user.full_name or context.user.email
        )
        if change is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found")
        self._settle(change, actor)
        return self.repository.list_holds(organization_id)

    def release_agent(self, organization_id: UUID, agent_id: UUID, context: CurrentUserContext) -> TierHoldsRead:
        """Release a held Agent when the Agent Limit has a place for it; it stays stopped."""
        actor = self._require_agent(organization_id, agent_id, context)
        change = self.repository.release_agent(
            organization_id,
            agent_id,
            self._agent_limit(organization_id),
            actor=actor,
            actor_display=context.user.full_name or context.user.email,
        )
        if change is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found")
        self._settle(change, actor)
        return self.repository.list_holds(organization_id)

    def stop_running_held(self, actor: ActorIdentity) -> None:
        """Stop held Agents still running, for the Tier sweep."""
        self.agents.stop_running_suspended(actor)

    def preview(self, organization_id: UUID, tier: Tier) -> TierHoldPreviewRead:
        """What moving the Organization to `tier` would hold. The caller authorizes."""
        limits = self.organization_lookup.get_agent_limit(organization_id)
        limit = (
            replace(limits, tier=tier.agent_limit).in_force(
                trial_limit=self.trial_settings.agent_limit, default=self.organization_settings.default_agent_limit
            )
            if limits is not None
            else tier.agent_limit
        )
        return self.repository.preview_holds(organization_id, tier, limit)

    def _agent_limit(self, organization_id: UUID) -> int | None:
        limits = self.organization_lookup.get_agent_limit(organization_id)
        if limits is None:
            return None
        return limits.in_force(
            trial_limit=self.trial_settings.agent_limit, default=self.organization_settings.default_agent_limit
        )

    def _settle(self, change: TierHoldChange, actor: ActorIdentity) -> None:
        self.event_delivery_dispatcher.enqueue_immediate(change.delivery_ids)
        for agent_id in change.running_agent_ids:
            try:
                self.agents.stop_suspended(agent_id, actor)
            except Exception:
                # The hold is recorded and refuses any start; a failed stop leaves the Agent
                # for its owner to stop.
                logger.exception("Could not stop agent %s for its Tier Hold", agent_id)
        for agent_id in change.restart_agent_ids:
            try:
                self.agents.restart_to_apply(agent_id, actor)
            except Exception:
                # Its held Connection is switched off in the database; the runtime drops it at
                # the Agent's next start.
                logger.exception("Could not restart agent %s to drop its held Connections", agent_id)

    def _require_manage(self, organization_id: UUID, context: CurrentUserContext) -> None:
        self.permission_policy.require_organization(
            context,
            organization_id,
            PermissionKey.TIER_HOLD_MANAGE,
            detail="Only an owner or admin can choose what your organization keeps.",
        )

    def _require_agent(self, organization_id: UUID, agent_id: UUID, context: CurrentUserContext) -> ActorIdentity:
        # The Agent resolves first, so a concealed one is 404 before the Organization check.
        agent = self.authorization.require_action(context, agent_id, PermissionKey.AGENT_LIFECYCLE_MANAGE)
        if agent.organization_id != organization_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found")
        self._require_manage(organization_id, context)
        return resolve_actor_identity(context, organization_id)

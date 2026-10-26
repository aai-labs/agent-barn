from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agent_addons.models import (
    KINDS_BY_RUNTIME,
    MAX_ACTIVE_ADDONS_PER_AGENT,
    AgentAddon,
    AgentAddonCreate,
    AgentAddonPersonRead,
    AgentAddonRead,
    AgentAddonRow,
    AgentAddonSpecRead,
    AgentAddonsRead,
    AgentAddonState,
    PlatformAgentAddonRead,
    PlatformAgentAddonRow,
    addon_spec,
)
from api.domains.agent_addons.repository import (
    AgentAddonChange,
    AgentAddonLimitReached,
    AgentAddonNameTaken,
    AgentAddonRepository,
    AgentAddonStateConflict,
)
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent, AgentType
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.rbac.catalog import PermissionKey
from api.infrastructure.shared.models import PaginatedItems, Pagination

_MANAGE_DETAIL = "You don't have permission to manage this agent's add-ons."


def _not_found(addon_id: UUID) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Add-on {addon_id} not found")


def _state_conflict(state: AgentAddonState, action: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=f"A {state.value.lower()} add-on cannot be {action}.",
    )


def _actor_display(context: CurrentUserContext) -> str:
    return context.user.full_name or context.user.email


def _person(name: str | None, email: str | None) -> AgentAddonPersonRead | None:
    return AgentAddonPersonRead(full_name=name, email=email) if email is not None else None


def _to_read(row: AgentAddonRow) -> AgentAddonRead:
    addon = row.addon
    return AgentAddonRead(
        id=addon.id,
        agent_id=addon.agent_id,
        kind=addon.kind,
        name=addon.name,
        spec=AgentAddonSpecRead.model_validate(addon.spec),
        reason=addon.reason,
        state=addon.state,
        rejection_reason=addon.rejection_reason,
        requested_by=_person(row.requester_name, row.requester_email),
        decided_at=addon.decided_at,
        created_at=addon.created_at,
        updated_at=addon.updated_at,
    )


def _to_platform_read(row: PlatformAgentAddonRow) -> PlatformAgentAddonRead:
    return PlatformAgentAddonRead(
        id=row.id,
        organization_id=row.organization_id,
        organization_name=row.organization_name,
        agent_id=row.agent_id,
        agent_name=row.agent_name,
        agent_type=row.agent_type,
        agent_deleted=row.agent_deleted,
        kind=row.kind,
        name=row.name,
        spec=AgentAddonSpecRead.model_validate(row.spec),
        reason=row.reason,
        state=row.state,
        rejection_reason=row.rejection_reason,
        requested_by=_person(row.requester_name, row.requester_email),
        decided_by=_person(row.decider_name, row.decider_email),
        created_at=row.created_at,
        decided_at=row.decided_at,
        updated_at=row.updated_at,
    )


@inject
@singleton
@dataclass
class AgentAddonService:
    """An Organization's side of Agent Add-ons: listing, requesting and withdrawing.

    Only Organization Owners and Admins, through `agent.addon.manage`, which no Agent Access
    Role grants. Every call resolves the Agent through `AgentAuthorization` first (`404` when
    it is concealed, `403` when visible without the grant), then checks the Organization grant.
    """

    repository: AgentAddonRepository
    authorization: AgentAuthorization
    event_delivery_dispatcher: EventDeliveryDispatcher

    def _require_manage(self, context: CurrentUserContext, agent_id: UUID) -> Agent:
        agent = self.authorization.require_action(
            context, agent_id, PermissionKey.AGENT_ADDON_MANAGE, detail=_MANAGE_DETAIL
        )
        # The Organization grant, which the Agent check above takes for granted from an Owner
        # or Admin role.
        self.authorization.policy.require(
            context, agent.organization_id, PermissionKey.AGENT_ADDON_MANAGE, detail=_MANAGE_DETAIL
        )
        return agent

    def list_addons(self, agent_id: UUID, context: CurrentUserContext) -> AgentAddonsRead:
        agent = self._require_manage(context, agent_id)
        rows = self.repository.list_for_agent(agent.id, agent.organization_id)
        return AgentAddonsRead(
            items=[_to_read(row) for row in rows],
            available_kinds=list(KINDS_BY_RUNTIME[agent.agent_type]),
        )

    def request_addon(self, agent_id: UUID, data: AgentAddonCreate, context: CurrentUserContext) -> AgentAddonRead:
        agent = self._require_manage(context, agent_id)
        if data.kind not in KINDS_BY_RUNTIME[agent.agent_type]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"A {AgentType(agent.agent_type).value} agent cannot install {data.kind.value} add-ons.",
            )
        addon = AgentAddon(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            kind=data.kind,
            name=data.name,
            spec=addon_spec(data),
            reason=data.reason,
            requested_by_user_id=context.user.id,
        )
        try:
            change = self.repository.create_with_event(
                addon,
                actor=resolve_actor_identity(context, agent.organization_id),
                actor_display=_actor_display(context),
            )
        except AgentAddonLimitReached:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"An agent can have at most {MAX_ACTIVE_ADDONS_PER_AGENT} pending and approved add-ons.",
            ) from None
        except AgentAddonNameTaken:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This agent already has a pending or approved {data.kind.value} add-on named {data.name}.",
            ) from None
        if change is None:
            # Deleted between the visibility check and the write.
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent.id} not found")
        self.event_delivery_dispatcher.enqueue_immediate(change.delivery_ids)
        return self._read(change, agent)

    def withdraw_addon(self, agent_id: UUID, addon_id: UUID, context: CurrentUserContext) -> AgentAddonRead:
        """Withdraw a Pending request. Withdrawing one already withdrawn is a no-op."""
        agent = self._require_manage(context, agent_id)
        try:
            change = self.repository.change_state_with_event(
                addon_id,
                to_state=AgentAddonState.WITHDRAWN,
                from_states={AgentAddonState.PENDING},
                actor=resolve_actor_identity(context, agent.organization_id),
                actor_display=_actor_display(context),
                decided_by_user_id=context.user.id,
                organization_id=agent.organization_id,
                agent_id=agent.id,
            )
        except AgentAddonStateConflict as conflict:
            raise _state_conflict(conflict.state, "withdrawn") from None
        if change is None:
            raise _not_found(addon_id)
        self.event_delivery_dispatcher.enqueue_immediate(change.delivery_ids)
        return self._read(change, agent)

    def _read(self, change: AgentAddonChange, agent: Agent) -> AgentAddonRead:
        row = self.repository.get_for_agent(change.addon.id, agent.id, agent.organization_id)
        if row is None:
            raise _not_found(change.addon.id)
        return _to_read(row)


@inject
@singleton
@dataclass
class PlatformAgentAddonService:
    """A Platform Administrator's side: every request across Organizations, and deciding one.

    Authorization is the routes' `require_platform_admin`; no Membership is checked. A
    Platform Administrator reads the request itself, which is what they review, and nothing
    else of the Agent, and their only writes are these decisions. Neither restarts the Agent:
    an approved or revoked add-on applies at its next start. See
    docs/adr/2026-10-26-platform-administrators-approve-agent-add-ons.md.
    """

    repository: AgentAddonRepository
    event_delivery_dispatcher: EventDeliveryDispatcher

    def list_requests(
        self,
        *,
        state: AgentAddonState | None,
        organization_id: UUID | None,
        search: str | None,
        page: int,
        page_size: int,
    ) -> PaginatedItems[PlatformAgentAddonRead]:
        rows, total = self.repository.find_platform_requests(
            state=state,
            organization_id=organization_id,
            search=search.strip() if search else None,
            pagination=Pagination(page=page, size=page_size),
        )
        return PaginatedItems(
            page=page, page_size=page_size, total=total, items=[_to_platform_read(row) for row in rows]
        )

    def approve(self, addon_id: UUID, context: CurrentUserContext) -> PlatformAgentAddonRead:
        return self._decide(addon_id, AgentAddonState.APPROVED, {AgentAddonState.PENDING}, context, "approved")

    def reject(self, addon_id: UUID, reason: str, context: CurrentUserContext) -> PlatformAgentAddonRead:
        return self._decide(
            addon_id, AgentAddonState.REJECTED, {AgentAddonState.PENDING}, context, "rejected", rejection_reason=reason
        )

    def revoke(self, addon_id: UUID, context: CurrentUserContext) -> PlatformAgentAddonRead:
        return self._decide(addon_id, AgentAddonState.REVOKED, {AgentAddonState.APPROVED}, context, "revoked")

    def _decide(
        self,
        addon_id: UUID,
        to_state: AgentAddonState,
        from_states: set[AgentAddonState],
        context: CurrentUserContext,
        action: str,
        *,
        rejection_reason: str | None = None,
    ) -> PlatformAgentAddonRead:
        row = self.repository.get_platform_request(addon_id)
        if row is None:
            raise _not_found(addon_id)
        try:
            change = self.repository.change_state_with_event(
                addon_id,
                to_state=to_state,
                from_states=from_states,
                actor=resolve_actor_identity(context, row.organization_id),
                actor_display=_actor_display(context),
                decided_by_user_id=context.user.id,
                rejection_reason=rejection_reason,
            )
        except AgentAddonStateConflict as conflict:
            raise _state_conflict(conflict.state, action) from None
        if change is None:
            raise _not_found(addon_id)
        self.event_delivery_dispatcher.enqueue_immediate(change.delivery_ids)
        updated = self.repository.get_platform_request(addon_id)
        if updated is None:
            raise _not_found(addon_id)
        return _to_platform_read(updated)

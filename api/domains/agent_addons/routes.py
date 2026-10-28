from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi_injector import Injected

from api.domains.agent_addons.models import (
    AgentAddonCreate,
    AgentAddonRead,
    AgentAddonRejection,
    AgentAddonsRead,
    AgentAddonState,
    PlatformAgentAddonRead,
)
from api.domains.agent_addons.service import AgentAddonService, PlatformAgentAddonService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user, require_platform_admin
from api.infrastructure.shared.models import PaginatedItems

agent_addons_router = APIRouter(prefix="/organizations/{organization_id}/agents", tags=["agent-addons"])
# Platform Oversight surface: no Active Organization is resolved, and the organization
# filter narrows the list rather than naming a scope the caller belongs to.
platform_agent_addons_router = APIRouter(prefix="/platform/agent-addons", tags=["platform-agent-addons"])


@agent_addons_router.get("/{agent_id}/addons", response_model=AgentAddonsRead)
def list_agent_addons(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentAddonService, Injected(AgentAddonService)],
):
    """The Agent's add-ons, newest first, and the kinds its runtime offers."""
    return service.list_addons(agent_id, context)


@agent_addons_router.post("/{agent_id}/addons", response_model=AgentAddonRead, status_code=status.HTTP_201_CREATED)
def request_agent_addon(
    agent_id: UUID,
    data: AgentAddonCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentAddonService, Injected(AgentAddonService)],
):
    """Ask a Platform Administrator to approve an add-on for this Agent. It stays Pending until
    they decide, and an approved one is installed the next time the Agent starts."""
    return service.request_addon(agent_id, data, context)


@agent_addons_router.post("/{agent_id}/addons/{addon_id}/withdraw", response_model=AgentAddonRead)
def withdraw_agent_addon(
    agent_id: UUID,
    addon_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentAddonService, Injected(AgentAddonService)],
):
    """Withdraw a Pending request."""
    return service.withdraw_addon(agent_id, addon_id, context)


@platform_agent_addons_router.get("", response_model=PaginatedItems[PlatformAgentAddonRead])
def list_platform_agent_addons(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformAgentAddonService, Injected(PlatformAgentAddonService)],
    state: Annotated[AgentAddonState | None, Query()] = None,
    organization_id: Annotated[UUID | None, Query()] = None,
    search: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
):
    """Every add-on request across Organizations, newest first."""
    return service.list_requests(
        state=state, organization_id=organization_id, search=search, page=page, page_size=page_size
    )


@platform_agent_addons_router.post("/{addon_id}/approve", response_model=PlatformAgentAddonRead)
def approve_platform_agent_addon(
    addon_id: UUID,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformAgentAddonService, Injected(PlatformAgentAddonService)],
):
    """Approve the request exactly as made. It is installed the next time the Agent starts."""
    return service.approve(addon_id, context)


@platform_agent_addons_router.post("/{addon_id}/reject", response_model=PlatformAgentAddonRead)
def reject_platform_agent_addon(
    addon_id: UUID,
    data: AgentAddonRejection,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformAgentAddonService, Injected(PlatformAgentAddonService)],
):
    """Refuse a Pending request, saying why."""
    return service.reject(addon_id, data.reason, context)


@platform_agent_addons_router.post("/{addon_id}/revoke", response_model=PlatformAgentAddonRead)
def revoke_platform_agent_addon(
    addon_id: UUID,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformAgentAddonService, Injected(PlatformAgentAddonService)],
):
    """Withdraw an approval. The Agent loses the add-on the next time it starts."""
    return service.revoke(addon_id, context)

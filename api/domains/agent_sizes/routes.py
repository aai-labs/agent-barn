from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi_injector import Injected

from api.domains.agent_sizes.models import (
    AgentSizeCreate,
    AgentSizeRead,
    AgentSizeUpdate,
    OrganizationAgentSizesRead,
    OrganizationAgentSizesUpdate,
)
from api.domains.agent_sizes.service import AgentSizeService, OrganizationAgentSizeService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user, require_platform_admin
from api.domains.organizations.models import PlatformOrganizationRead

# Platform Resource: no Active Organization is resolved.
platform_agent_sizes_router = APIRouter(prefix="/platform/agent-sizes", tags=["platform-agent-sizes"])
platform_organization_agent_sizes_router = APIRouter(
    prefix="/platform/organizations/{organization_id}/agent-sizes", tags=["platform-organizations"]
)
organization_agent_sizes_router = APIRouter(
    prefix="/organizations/{organization_id}/agent-sizes", tags=["organizations"]
)


@platform_agent_sizes_router.get("", response_model=list[AgentSizeRead])
def list_agent_sizes(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[AgentSizeService, Injected(AgentSizeService)],
):
    return service.list_sizes()


@platform_agent_sizes_router.post("", response_model=AgentSizeRead, status_code=status.HTTP_201_CREATED)
def create_agent_size(
    data: AgentSizeCreate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[AgentSizeService, Injected(AgentSizeService)],
):
    return service.create_size(data, context)


@platform_agent_sizes_router.patch("/{size_id}", response_model=AgentSizeRead)
def update_agent_size(
    size_id: UUID,
    data: AgentSizeUpdate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[AgentSizeService, Injected(AgentSizeService)],
):
    return service.update_size(size_id, data, context)


@platform_agent_sizes_router.delete("/{size_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_size(
    size_id: UUID,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[AgentSizeService, Injected(AgentSizeService)],
):
    service.delete_size(size_id, context)


@platform_organization_agent_sizes_router.put("", response_model=PlatformOrganizationRead)
def set_organization_agent_sizes(
    organization_id: UUID,
    data: OrganizationAgentSizesUpdate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[OrganizationAgentSizeService, Injected(OrganizationAgentSizeService)],
):
    """Set the sizes an Organization may choose beyond the default. Empty: it cannot choose."""
    return service.set_allowed(organization_id, data.agent_size_ids, context)


@organization_agent_sizes_router.get("", response_model=OrganizationAgentSizesRead)
def get_organization_agent_sizes(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[OrganizationAgentSizeService, Injected(OrganizationAgentSizeService)],
):
    """The sizes this Organization's Agents may be put on, the default first."""
    return service.get_choosable(organization_id, context)

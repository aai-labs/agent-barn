from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi_injector import Injected

from api.domains.agent_sizes.models import AgentSizeCreate, AgentSizeRead, AgentSizeUpdate
from api.domains.agent_sizes.service import AgentSizeService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin

# Platform Resource: no Active Organization is resolved. Organizations get their own read of
# the sizes they may choose in a later slice of the Agent Sizes epic.
platform_agent_sizes_router = APIRouter(prefix="/platform/agent-sizes", tags=["platform-agent-sizes"])


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

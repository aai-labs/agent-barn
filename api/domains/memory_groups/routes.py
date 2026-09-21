from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.memory_groups.models import (
    MemoryGroupCreate,
    MemoryGroupRead,
    MemoryGroupUpdate,
    ShareMemoryItemCreate,
    ShareMemoryItemResult,
)
from api.domains.memory_groups.service import MemoryGroupService

memory_groups_router = APIRouter(prefix="/organizations/{organization_id}/memory-groups", tags=["memory-groups"])


@memory_groups_router.get("", response_model=list[MemoryGroupRead])
def list_memory_groups(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[MemoryGroupService, Injected(MemoryGroupService)],
):
    return service.list_groups(context)


@memory_groups_router.post("", response_model=MemoryGroupRead, status_code=status.HTTP_201_CREATED)
def create_memory_group(
    data: MemoryGroupCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[MemoryGroupService, Injected(MemoryGroupService)],
):
    return service.create_group(data, context)


@memory_groups_router.get("/{group_id}", response_model=MemoryGroupRead)
def get_memory_group(
    group_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[MemoryGroupService, Injected(MemoryGroupService)],
):
    return service.get_group(group_id, context)


@memory_groups_router.patch("/{group_id}", response_model=MemoryGroupRead)
def rename_memory_group(
    group_id: UUID,
    data: MemoryGroupUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[MemoryGroupService, Injected(MemoryGroupService)],
):
    return service.rename_group(group_id, data, context)


@memory_groups_router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_memory_group(
    group_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[MemoryGroupService, Injected(MemoryGroupService)],
):
    service.delete_group(group_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@memory_groups_router.post("/{source_group_id}/shared-items", response_model=ShareMemoryItemResult)
def share_memory_item(
    source_group_id: UUID,
    data: ShareMemoryItemCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[MemoryGroupService, Injected(MemoryGroupService)],
):
    return service.share_item(source_group_id, data, context)


@memory_groups_router.put("/{group_id}/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def add_agent_to_memory_group(
    group_id: UUID,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[MemoryGroupService, Injected(MemoryGroupService)],
):
    service.add_agent(group_id, agent_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@memory_groups_router.delete("/{group_id}/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_agent_from_memory_group(
    group_id: UUID,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[MemoryGroupService, Injected(MemoryGroupService)],
):
    service.remove_agent(group_id, agent_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

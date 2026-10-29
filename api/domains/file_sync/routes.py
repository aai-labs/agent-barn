from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.file_sync.models import (
    AgentFileSyncActivityRead,
    AgentFileSyncRead,
    AgentFileSyncSettingRead,
    AgentFileSyncUpdate,
)
from api.domains.file_sync.service import AgentFileSyncService
from api.infrastructure.shared.models import PaginatedItems, Pagination

agent_file_sync_router = APIRouter(
    prefix="/organizations/{organization_id}/agents/{agent_id}/file-sync", tags=["file-sync"]
)


@agent_file_sync_router.get("", response_model=AgentFileSyncRead)
def get_agent_file_sync(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentFileSyncService, Injected(AgentFileSyncService)],
) -> AgentFileSyncRead:
    return service.status(agent_id, context)


@agent_file_sync_router.get("/activity", response_model=PaginatedItems[AgentFileSyncActivityRead])
def list_agent_file_sync_activity(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentFileSyncService, Injected(AgentFileSyncService)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedItems[AgentFileSyncActivityRead]:
    return service.activity(agent_id, Pagination(page=page, size=page_size), context)


@agent_file_sync_router.put("", response_model=AgentFileSyncSettingRead)
def set_agent_file_sync(
    agent_id: UUID,
    payload: AgentFileSyncUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentFileSyncService, Injected(AgentFileSyncService)],
) -> AgentFileSyncSettingRead:
    return service.set_enabled(agent_id, payload.enabled, context)

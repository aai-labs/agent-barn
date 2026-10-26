from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.file_sync.models import (
    AgentFileSyncSettingRead,
    AgentFileSyncUpdate,
)
from api.domains.file_sync.service import AgentFileSyncService

agent_file_sync_router = APIRouter(
    prefix="/organizations/{organization_id}/agents/{agent_id}/file-sync", tags=["file-sync"]
)


@agent_file_sync_router.put("", response_model=AgentFileSyncSettingRead)
def set_agent_file_sync(
    agent_id: UUID,
    payload: AgentFileSyncUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentFileSyncService, Injected(AgentFileSyncService)],
) -> AgentFileSyncSettingRead:
    return service.set_enabled(agent_id, payload.enabled, context)

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.agent_settings.models import AgentSettingsRead, AgentSettingsUpdate
from api.domains.agent_settings.service import AgentSettingsService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user

agent_settings_router = APIRouter(prefix="/organizations/{organization_id}/agent-settings", tags=["agent-settings"])


@agent_settings_router.get("", response_model=AgentSettingsRead)
def get_agent_settings(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentSettingsService, Injected(AgentSettingsService)],
):
    return service.get_settings(organization_id, context)


@agent_settings_router.put("", response_model=AgentSettingsRead)
def update_agent_settings(
    organization_id: UUID,
    data: AgentSettingsUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentSettingsService, Injected(AgentSettingsService)],
):
    return service.update_settings(organization_id, data, context)

from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.agent_memory.platform_models import PlatformMemorySettingsRead, PlatformMemorySettingsUpdate
from api.domains.agent_memory.platform_service import PlatformMemoryService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin

platform_memory_router = APIRouter(prefix="/platform/settings/agent-memory", tags=["platform-settings"])


@platform_memory_router.get("", response_model=PlatformMemorySettingsRead)
def read_settings(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformMemoryService, Injected(PlatformMemoryService)],
):
    return service.read(context)


@platform_memory_router.get("/models")
def list_models(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformMemoryService, Injected(PlatformMemoryService)],
):
    return service.models(context)


@platform_memory_router.put("", response_model=PlatformMemorySettingsRead)
def update_settings(
    data: PlatformMemorySettingsUpdate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformMemoryService, Injected(PlatformMemoryService)],
):
    return service.update(data, context)

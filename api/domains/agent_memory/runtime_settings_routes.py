"""Read-only service-to-service model configuration; never accepts Agent credentials."""

from typing import Annotated

from fastapi import APIRouter, Header
from fastapi_injector import Injected

from api.domains.agent_memory.platform_service import PlatformMemoryService

memory_runtime_settings_router = APIRouter()


@memory_runtime_settings_router.get("/model")
def runtime_model(
    service: Annotated[PlatformMemoryService, Injected(PlatformMemoryService)],
    authorization: Annotated[str | None, Header()] = None,
):
    return service.runtime_model(authorization)

"""Read-only service-to-service model configuration; never accepts Agent credentials."""

from typing import Annotated

from fastapi import APIRouter, Header
from fastapi_injector import Injected

from api.domains.agent_memory.runtime_settings_service import MemoryRuntimeSettingsService

memory_runtime_settings_router = APIRouter()


@memory_runtime_settings_router.get("/model")
def runtime_model(
    service: Annotated[MemoryRuntimeSettingsService, Injected(MemoryRuntimeSettingsService)],
    authorization: Annotated[str | None, Header()] = None,
    bank: str | None = None,
):
    return service.read(authorization, bank)

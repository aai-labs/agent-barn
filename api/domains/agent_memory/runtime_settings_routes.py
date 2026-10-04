"""Read-only service-to-service model configuration; never accepts Agent credentials."""

import hmac
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException
from fastapi_injector import Injected

from api.core.config import Config
from api.domains.agent_memory.platform_repository import PlatformMemoryRepository

memory_runtime_settings_router = APIRouter()


@memory_runtime_settings_router.get("/model")
def runtime_model(
    repository: Annotated[PlatformMemoryRepository, Injected(PlatformMemoryRepository)],
    config: Annotated[Config, Injected(Config)],
    authorization: Annotated[str | None, Header()] = None,
):
    scheme, _, token = (authorization or "").partition(" ")
    if (
        scheme.lower() != "bearer"
        or not config.hindsight_api_key
        or not hmac.compare_digest(token.encode(), config.hindsight_api_key.encode())
    ):
        raise HTTPException(401, "Invalid memory service credential.")
    return {"model": repository.read(config.memory_default_model).model}

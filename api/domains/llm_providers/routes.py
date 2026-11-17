from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.domains.llm_providers.models import (
    LlmProviderConnectionRead,
    OpenRouterConnectionRead,
    OpenRouterKeyUpdate,
)
from api.domains.llm_providers.service import PlatformLlmProviderService


class CredentialSafeRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return JSONResponse(status_code=422, content={"detail": "Invalid LLM provider key request"})

        return safe_handler


platform_llm_providers_router = APIRouter(
    route_class=CredentialSafeRoute, prefix="/platform/settings/llm-providers", tags=["platform-settings"]
)


@platform_llm_providers_router.get("", response_model=list[LlmProviderConnectionRead])
def list_connections(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformLlmProviderService, Injected(PlatformLlmProviderService)],
):
    return service.list_connections(context)


@platform_llm_providers_router.get("/openrouter", response_model=OpenRouterConnectionRead)
def read_openrouter_connection(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformLlmProviderService, Injected(PlatformLlmProviderService)],
):
    return service.read_openrouter(context)


@platform_llm_providers_router.put("/openrouter", response_model=OpenRouterConnectionRead)
def replace_openrouter_key(
    data: OpenRouterKeyUpdate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformLlmProviderService, Injected(PlatformLlmProviderService)],
):
    return service.replace_openrouter_key(data, context)

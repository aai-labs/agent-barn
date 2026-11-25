from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.domains.llm_providers.models import (
    LlmProviderCatalogueEntryRead,
    LlmProviderConnectionCreate,
    LlmProviderConnectionRead,
    LlmProviderKeyReplace,
    LlmProviderModelRead,
    LlmProviderModelsReplace,
    LlmProviderOrganizationsRead,
    LlmProviderOrganizationsReplace,
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


@platform_llm_providers_router.post("", response_model=LlmProviderConnectionRead, status_code=201)
def add_connection(
    data: LlmProviderConnectionCreate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformLlmProviderService, Injected(PlatformLlmProviderService)],
):
    return service.add_connection(data, context)


@platform_llm_providers_router.put("/{slug}/key", response_model=LlmProviderConnectionRead)
def replace_key(
    slug: str,
    data: LlmProviderKeyReplace,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformLlmProviderService, Injected(PlatformLlmProviderService)],
):
    return service.replace_key(slug, data, context)


@platform_llm_providers_router.get("/{slug}/models", response_model=list[LlmProviderModelRead])
def list_models(
    slug: str,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformLlmProviderService, Injected(PlatformLlmProviderService)],
):
    return service.list_models(slug, context)


@platform_llm_providers_router.put("/{slug}/models", response_model=list[LlmProviderModelRead])
def replace_models(
    slug: str,
    data: LlmProviderModelsReplace,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformLlmProviderService, Injected(PlatformLlmProviderService)],
):
    return service.replace_models(slug, data, context)


@platform_llm_providers_router.get("/{slug}/model-catalogue", response_model=list[LlmProviderCatalogueEntryRead])
def read_model_catalogue(
    slug: str,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformLlmProviderService, Injected(PlatformLlmProviderService)],
):
    return service.read_model_catalogue(slug, context)


@platform_llm_providers_router.get("/{slug}/organizations", response_model=LlmProviderOrganizationsRead)
def read_organizations(
    slug: str,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformLlmProviderService, Injected(PlatformLlmProviderService)],
):
    return service.read_organizations(slug, context)


@platform_llm_providers_router.put("/{slug}/organizations", response_model=LlmProviderOrganizationsRead)
def replace_organizations(
    slug: str,
    data: LlmProviderOrganizationsReplace,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformLlmProviderService, Injected(PlatformLlmProviderService)],
):
    return service.replace_organizations(slug, data, context)


@platform_llm_providers_router.delete("/{slug}", status_code=204)
def delete_connection(
    slug: str,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformLlmProviderService, Injected(PlatformLlmProviderService)],
):
    service.delete_connection(slug, context)

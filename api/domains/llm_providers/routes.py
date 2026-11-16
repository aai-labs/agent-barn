from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.domains.llm_providers.models import OpenRouterConnectionRead
from api.domains.llm_providers.service import PlatformLlmProviderService

platform_llm_providers_router = APIRouter(prefix="/platform/settings/llm-providers", tags=["platform-settings"])


@platform_llm_providers_router.get("/openrouter", response_model=OpenRouterConnectionRead)
def read_openrouter_connection(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformLlmProviderService, Injected(PlatformLlmProviderService)],
):
    return service.read_openrouter(context)

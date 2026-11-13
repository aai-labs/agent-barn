from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.domains.decisions.models import PlatformDecisionSettingsRead, PlatformDecisionSettingsUpdate
from api.domains.decisions.service import DecisionService

platform_decisions_router = APIRouter(prefix="/platform/settings/decisions", tags=["platform-settings"])


@platform_decisions_router.get("", response_model=PlatformDecisionSettingsRead)
def read_settings(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[DecisionService, Injected(DecisionService)],
):
    return service.read_settings(context)


@platform_decisions_router.get("/models")
def list_models(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[DecisionService, Injected(DecisionService)],
):
    return service.models(context)


@platform_decisions_router.put("", response_model=PlatformDecisionSettingsRead)
def update_settings(
    data: PlatformDecisionSettingsUpdate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[DecisionService, Injected(DecisionService)],
):
    return service.update_settings(data, context)

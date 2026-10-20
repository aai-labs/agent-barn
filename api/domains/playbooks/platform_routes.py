from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.domains.playbooks.platform_models import PlatformPlaybookSettingsRead, PlatformPlaybookSettingsUpdate
from api.domains.playbooks.platform_service import PlatformPlaybookService

platform_playbooks_router = APIRouter(prefix="/platform/settings/playbooks", tags=["platform-settings"])


@platform_playbooks_router.get("", response_model=PlatformPlaybookSettingsRead)
def read_settings(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformPlaybookService, Injected(PlatformPlaybookService)],
):
    return service.read(context)


@platform_playbooks_router.get("/models")
def list_models(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformPlaybookService, Injected(PlatformPlaybookService)],
):
    return service.models(context)


@platform_playbooks_router.put("", response_model=PlatformPlaybookSettingsRead)
def update_settings(
    data: PlatformPlaybookSettingsUpdate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformPlaybookService, Injected(PlatformPlaybookService)],
):
    return service.update(data, context)

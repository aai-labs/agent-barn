from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.domains.workflows.platform_models import PlatformWorkflowSettingsRead, PlatformWorkflowSettingsUpdate
from api.domains.workflows.platform_service import PlatformWorkflowService

platform_workflow_router = APIRouter(prefix="/platform/settings/workflows", tags=["platform-settings"])


@platform_workflow_router.get("", response_model=PlatformWorkflowSettingsRead)
def read_settings(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformWorkflowService, Injected(PlatformWorkflowService)],
):
    return service.read(context)


@platform_workflow_router.put("", response_model=PlatformWorkflowSettingsRead)
def update_settings(
    data: PlatformWorkflowSettingsUpdate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformWorkflowService, Injected(PlatformWorkflowService)],
):
    return service.update(data, context)

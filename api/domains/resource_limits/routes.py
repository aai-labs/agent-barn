from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.domains.resource_limits.models import ResourceLimitsRead, ResourceLimitsUpdate
from api.domains.resource_limits.service import ResourceLimitsService

# Platform Oversight surface: no Active Organization is resolved. The current limits are
# read through the Platform resource usage response, so there is no GET here.
platform_resource_limits_router = APIRouter(prefix="/platform/resource-limits", tags=["platform-resource-limits"])


@platform_resource_limits_router.put("", response_model=ResourceLimitsRead)
def update_platform_resource_limits(
    data: ResourceLimitsUpdate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[ResourceLimitsService, Injected(ResourceLimitsService)],
):
    return service.update_limits(data, context)

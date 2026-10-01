from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.domains.resource_usage.models import PlatformResourceUsageRead, ResourceUsageRange
from api.domains.resource_usage.platform_service import PlatformResourceUsageService

# Platform Oversight surface: no Active Organization is resolved, and the organization
# filter narrows the view rather than naming a scope the caller belongs to. Authorization
# is require_platform_admin, with no membership to check, which is why this lives apart
# from the Organization routes and returns its own read model.
platform_resource_usage_router = APIRouter(prefix="/platform/resource-usage", tags=["platform-resource-usage"])


@platform_resource_usage_router.get("", response_model=PlatformResourceUsageRead)
def get_platform_resource_usage(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformResourceUsageService, Injected(PlatformResourceUsageService)],
    usage_range: Annotated[ResourceUsageRange, Query(alias="range")] = ResourceUsageRange.ONE_DAY,
    organization_id: Annotated[UUID | None, Query()] = None,
):
    return service.get_usage(usage_range, organization_id)

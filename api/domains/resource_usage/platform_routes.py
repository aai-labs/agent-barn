from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.domains.resource_usage.models import (
    PlatformAgentDetailsRead,
    PlatformResourceUsageRead,
    UsageWindow,
    get_usage_window,
)
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
    window: Annotated[UsageWindow, Depends(get_usage_window)],
    organization_id: Annotated[UUID | None, Query()] = None,
):
    return service.get_usage(window, organization_id)


@platform_resource_usage_router.get("/agents/{agent_id}", response_model=PlatformAgentDetailsRead)
def get_platform_agent_details(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformResourceUsageService, Injected(PlatformResourceUsageService)],
    window: Annotated[UsageWindow, Depends(get_usage_window)],
):
    """Status and usage over a window for one Agent: what a Heaviest agents row shows when opened."""
    return service.get_agent_details(agent_id, window)

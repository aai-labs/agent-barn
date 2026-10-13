from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.platform_admin.models import StatsWindow, get_stats_window
from api.domains.resource_usage.models import AgentOverviewRead, AgentResourceUsageRead, ResourceUsageRange
from api.domains.resource_usage.service import AgentOverviewService, ResourceUsageService

resource_usage_router = APIRouter(prefix="/organizations/{organization_id}/agents", tags=["resource-usage"])
agent_overview_router = APIRouter(prefix="/organizations/{organization_id}/agent-overview", tags=["agent-overview"])


@resource_usage_router.get("/{agent_id}/resource-usage", response_model=AgentResourceUsageRead)
def get_agent_resource_usage(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[ResourceUsageService, Injected(ResourceUsageService)],
    usage_range: Annotated[ResourceUsageRange, Query(alias="range")] = ResourceUsageRange.ONE_DAY,
):
    return service.get_agent_resource_usage(agent_id, context, usage_range)


@agent_overview_router.get("", response_model=AgentOverviewRead)
def get_agent_overview(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[AgentOverviewService, Injected(AgentOverviewService)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
):
    return service.get_overview(context, window)

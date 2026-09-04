from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.costs.models import (
    AgentCostRead,
    CostFilter,
    CostFilterOption,
    CostRecordRead,
    CostSummaryRead,
    get_cost_filter,
)
from api.domains.costs.service import CostService
from api.domains.platform_admin.models import StatsWindow, get_stats_window
from api.infrastructure.shared.models import PaginatedItems

costs_router = APIRouter(prefix="/organizations/{organization_id}/costs", tags=["costs"])

# Org spend is billing-sensitive, so it's restricted to the org's managers — owners/admins
# (platform admins bypass). Plain members can run agents but not see the org's aggregate cost.
#
# Every route takes the same window and filter, so the summary above the table and the
# rows inside it always describe the same set of calls.


@costs_router.get("/summary", response_model=CostSummaryRead)
def get_cost_summary(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CostService, Injected(CostService)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
    filters: Annotated[CostFilter, Depends(get_cost_filter)],
):
    return service.get_org_cost_summary(context, window, filters)


@costs_router.get("", response_model=PaginatedItems[CostRecordRead])
def list_costs(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CostService, Injected(CostService)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
    filters: Annotated[CostFilter, Depends(get_cost_filter)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return service.list_org_costs(context, window, filters, page=page, page_size=page_size)


@costs_router.get("/filters/agents", response_model=list[CostFilterOption])
def list_agent_filter_options(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CostService, Injected(CostService)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
    filters: Annotated[CostFilter, Depends(get_cost_filter)],
):
    return service.list_org_agent_options(context, window, filters)


@costs_router.get("/filters/models", response_model=list[CostFilterOption])
def list_model_filter_options(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CostService, Injected(CostService)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
    filters: Annotated[CostFilter, Depends(get_cost_filter)],
):
    return service.list_org_model_options(context, window, filters)


@costs_router.get("/agents/{agent_id}", response_model=AgentCostRead)
def get_agent_cost(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CostService, Injected(CostService)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
):
    return service.get_agent_cost(agent_id, context, window)

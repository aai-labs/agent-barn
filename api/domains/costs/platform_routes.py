from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.domains.costs.models import (
    CostFilter,
    CostFilterOption,
    OrganizationSpendRead,
    PlatformCostRecordRead,
    PlatformCostSummaryRead,
    get_platform_cost_filter,
)
from api.domains.costs.platform_service import PlatformCostService
from api.domains.platform_admin.models import StatsWindow, get_stats_window
from api.infrastructure.shared.models import PaginatedItems

# Platform Oversight surface: no Active Organization is resolved, and the
# organization filter is a narrowing choice rather than a scope the caller belongs
# to. Authorization is require_platform_admin on every route — there is deliberately
# no membership to check, which is exactly why these routes live apart from the
# org-scoped ones and return their own read model.
platform_costs_router = APIRouter(prefix="/platform/costs", tags=["platform-costs"])


@platform_costs_router.get("/summary", response_model=PlatformCostSummaryRead)
def get_platform_cost_summary(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformCostService, Injected(PlatformCostService)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
    filters: Annotated[CostFilter, Depends(get_platform_cost_filter)],
):
    return service.get_summary(window, filters)


@platform_costs_router.get("", response_model=PaginatedItems[PlatformCostRecordRead])
def list_platform_costs(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformCostService, Injected(PlatformCostService)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
    filters: Annotated[CostFilter, Depends(get_platform_cost_filter)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return service.list_costs(window, filters, page=page, page_size=page_size)


@platform_costs_router.get("/organizations", response_model=list[OrganizationSpendRead])
def list_organizations_by_spend(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformCostService, Injected(PlatformCostService)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
    filters: Annotated[CostFilter, Depends(get_platform_cost_filter)],
):
    """Organizations ranked by spend. Doubles as the org filter's option source."""
    return service.list_organizations(window, filters)


@platform_costs_router.get("/filters/agents", response_model=list[CostFilterOption])
def list_platform_agent_filter_options(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformCostService, Injected(PlatformCostService)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
    filters: Annotated[CostFilter, Depends(get_platform_cost_filter)],
):
    return service.list_agent_options(window, filters)


@platform_costs_router.get("/filters/models", response_model=list[CostFilterOption])
def list_platform_model_filter_options(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformCostService, Injected(PlatformCostService)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
    filters: Annotated[CostFilter, Depends(get_platform_cost_filter)],
):
    return service.list_model_options(window, filters)

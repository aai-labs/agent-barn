from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi_injector import Injected

from api.domains.activity.models import (
    ActivityFilter,
    AgentActivityCallRead,
    AgentActivitySummaryRead,
    AgentWakeRead,
    get_activity_filter,
)
from api.domains.activity.service import ActivityService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.platform_admin.models import StatsWindow, get_stats_window
from api.infrastructure.shared.models import PaginatedItems, Pagination

activity_router = APIRouter(prefix="/organizations/{organization_id}/agents", tags=["activity"])

# One window parameter drives all three routes, so drilling in is just a
# narrower window: a day from the summary, then a single wake's bounds.


@activity_router.get("/{agent_id}/activity", response_model=AgentActivitySummaryRead)
def get_agent_activity(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[ActivityService, Injected(ActivityService)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
):
    return service.get_summary(agent_id, context, window)


@activity_router.get("/{agent_id}/activity/wakes", response_model=PaginatedItems[AgentWakeRead])
def list_agent_wakes(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[ActivityService, Injected(ActivityService)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
    filters: Annotated[ActivityFilter, Depends(get_activity_filter)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 25,
):
    return service.list_wakes(agent_id, context, window, filters, Pagination(page=page, size=page_size))


@activity_router.get("/{agent_id}/activity/calls", response_model=PaginatedItems[AgentActivityCallRead])
def list_agent_activity_calls(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[ActivityService, Injected(ActivityService)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
    filters: Annotated[ActivityFilter, Depends(get_activity_filter)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
):
    return service.list_calls(agent_id, context, window, filters, Pagination(page=page, size=page_size))

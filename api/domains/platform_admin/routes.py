from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.domains.platform_admin.models import (
    PlatformAgentStatsRead,
    PlatformMessageStatsRead,
    PlatformStatsFilter,
    StatsWindow,
    get_platform_stats_filter,
    get_stats_window,
)
from api.domains.platform_admin.stats_service import PlatformStatsService

# Global Platform View surface (AF-256): no Active Organization is resolved or
# accepted, and there is no Organization-scoped equivalent of these stats. An
# Organization dashboard is expected later; it will reuse the underlying
# aggregates through its own routes, read models, and AuthorizationScope rather
# than widening these.
platform_stats_router = APIRouter(prefix="/platform/stats", tags=["platform-stats"])


@platform_stats_router.get("/messages", response_model=PlatformMessageStatsRead)
def get_platform_message_stats(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformStatsService, Injected(PlatformStatsService)],
    stats_filter: Annotated[PlatformStatsFilter, Depends(get_platform_stats_filter)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
):
    return service.get_message_stats(window, stats_filter)


@platform_stats_router.get("/agents", response_model=PlatformAgentStatsRead)
def get_platform_agent_stats(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[PlatformStatsService, Injected(PlatformStatsService)],
    stats_filter: Annotated[PlatformStatsFilter, Depends(get_platform_stats_filter)],
    window: Annotated[StatsWindow, Depends(get_stats_window)],
):
    return service.get_agent_stats(window, stats_filter)

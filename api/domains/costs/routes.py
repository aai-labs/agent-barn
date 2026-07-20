from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.costs.models import AgentCostRead, OrgCostSummaryRead
from api.domains.costs.service import CostService

costs_router = APIRouter(prefix="/costs", tags=["costs"])

# Org spend is billing-sensitive, so it's restricted to the org's managers — owners/admins
# (superusers bypass). Plain members can run agents but not see the org's aggregate cost.


@costs_router.get(
    "/summary",
    response_model=OrgCostSummaryRead,
    response_model_by_alias=True,
)
def get_cost_summary(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CostService, Injected(CostService)],
    start_date: str | None = None,
    end_date: str | None = None,
):
    return service.get_org_cost_summary(
        context, start_date=start_date, end_date=end_date
    )


@costs_router.get("/agents/{agent_id}", response_model=AgentCostRead)
def get_agent_cost(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[CostService, Injected(CostService)],
):
    return service.get_agent_cost(agent_id, context)

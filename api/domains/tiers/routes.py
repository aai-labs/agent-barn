from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user, require_platform_admin
from api.domains.tiers.holds import TierHoldService
from api.domains.tiers.models import PublicTierRead, TierCreate, TierHoldsRead, TierRead, TierUpdate
from api.domains.tiers.repository import TierRepository
from api.domains.tiers.service import TierService

# Platform Resource: no Active Organization is resolved.
platform_tiers_router = APIRouter(prefix="/platform/tiers", tags=["platform-tiers"])


@platform_tiers_router.get("", response_model=list[TierRead])
def list_tiers(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TierService, Injected(TierService)],
):
    """The catalog, by `sort_order`, then name, the system's tiers included."""
    return service.list_tiers()


@platform_tiers_router.post("", response_model=TierRead, status_code=status.HTTP_201_CREATED)
def create_tier(
    data: TierCreate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TierService, Injected(TierService)],
):
    return service.create_tier(data, context)


@platform_tiers_router.patch("/{tier_id}", response_model=TierRead)
def update_tier(
    tier_id: UUID,
    data: TierUpdate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TierService, Injected(TierService)],
):
    return service.update_tier(tier_id, data, context)


@platform_tiers_router.delete("/{tier_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tier(
    tier_id: UUID,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TierService, Injected(TierService)],
):
    service.delete_tier(tier_id, context)


organization_tier_holds_router = APIRouter(
    prefix="/organizations/{organization_id}/tier-holds", tags=["organization-tier-holds"]
)


@organization_tier_holds_router.get("", response_model=TierHoldsRead)
def list_tier_holds(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[TierHoldService, Injected(TierHoldService)],
):
    """The Organization's live Agents and everything its Tier has put on hold."""
    return service.list_holds(organization_id, context)


@organization_tier_holds_router.post("/agents/{agent_id}/hold", response_model=TierHoldsRead)
def hold_agent(
    organization_id: UUID,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[TierHoldService, Injected(TierHoldService)],
):
    """Put an Agent on hold, stopping it, to free its place for another."""
    return service.hold_agent(organization_id, agent_id, context)


@organization_tier_holds_router.post("/agents/{agent_id}/release", response_model=TierHoldsRead)
def release_agent(
    organization_id: UUID,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[TierHoldService, Injected(TierHoldService)],
):
    """Release a held Agent when the Agent Limit has a place for it."""
    return service.release_agent(organization_id, agent_id, context)


# Public: the pricing page and onboarding list what is offered.
public_tiers_router = APIRouter(prefix="/tiers", tags=["tiers"])


@public_tiers_router.get("", response_model=list[PublicTierRead])
def list_offered_tiers(repository: Annotated[TierRepository, Injected(TierRepository)]):
    """The Tiers offered to new Organizations, in catalog order."""
    return [tier for tier in repository.list_offered() if tier.agent_limit > 0]

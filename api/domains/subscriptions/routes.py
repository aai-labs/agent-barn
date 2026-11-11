from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user, require_platform_admin
from api.domains.organizations.models import PlatformOrganizationRead
from api.domains.subscriptions.assignment import TierAssignmentService
from api.domains.subscriptions.models import (
    SubscriptionPortal,
    SubscriptionRead,
    SubscriptionStart,
    SubscriptionStartRead,
)
from api.domains.subscriptions.service import SubscriptionService
from api.domains.tiers.models import OrganizationTierAssignment, TierHoldPreviewRead

organization_subscription_router = APIRouter(
    prefix="/organizations/{organization_id}/subscription", tags=["organization-subscription"]
)
platform_subscription_router = APIRouter(
    prefix="/platform/organizations/{organization_id}/subscription", tags=["platform-subscription"]
)


@organization_subscription_router.get("", response_model=SubscriptionRead | None)
def read_subscription(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SubscriptionService, Injected(SubscriptionService)],
):
    """The Organization's live subscription, or null."""
    return service.get(organization_id, context)


@organization_subscription_router.get("/preview", response_model=TierHoldPreviewRead)
def preview_subscription_change(
    organization_id: UUID,
    tier_key: str,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SubscriptionService, Injected(SubscriptionService)],
):
    """What moving to `tier_key` would put on hold: `free` for a cancellation, or a paid tier to
    switch to. Nothing changes."""
    return service.preview(organization_id, tier_key, context)


@organization_subscription_router.post("", response_model=SubscriptionStartRead)
def start_subscription(
    organization_id: UUID,
    data: SubscriptionStart,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SubscriptionService, Injected(SubscriptionService)],
):
    """Subscribe to a paid Tier, or move the live subscription to another one."""
    return service.start(organization_id, data.tier_key, context, return_to=data.return_to)


@organization_subscription_router.post("/cancel", response_model=SubscriptionRead)
def cancel_subscription(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SubscriptionService, Injected(SubscriptionService)],
):
    """End the subscription when the current period does."""
    return service.set_cancel_at_period_end(organization_id, True, context)


@organization_subscription_router.post("/portal", response_model=SubscriptionPortal)
def open_subscription_portal(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SubscriptionService, Injected(SubscriptionService)],
):
    """A link to the payment provider's page for the card, billing details and invoices."""
    return service.portal(organization_id, context)


@organization_subscription_router.post("/resume", response_model=SubscriptionRead)
def resume_subscription(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SubscriptionService, Injected(SubscriptionService)],
):
    """Take back a cancellation scheduled for the end of the period."""
    return service.set_cancel_at_period_end(organization_id, False, context)


@platform_subscription_router.get("", response_model=SubscriptionRead | None)
def read_subscription_for_platform(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SubscriptionService, Injected(SubscriptionService)],
):
    return service.read_for_platform(organization_id, context)


@platform_subscription_router.post("/end-period", response_model=SubscriptionRead | None)
def end_subscription_period(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SubscriptionService, Injected(SubscriptionService)],
):
    """End the current period now: expire its unused allowance, then renew or end."""
    return service.end_period_now(organization_id, context)


# A Platform Administrator puts an Organization on a Tier from its Platform page. Here, beside
# subscriptions, because choosing its Tier ends a subscription it pays for.
platform_organization_tier_router = APIRouter(prefix="/platform/organizations", tags=["platform-organizations"])


@platform_organization_tier_router.put("/{organization_id}/tier", response_model=PlatformOrganizationRead)
def set_organization_tier(
    organization_id: UUID,
    data: OrganizationTierAssignment,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TierAssignmentService, Injected(TierAssignmentService)],
):
    """Put an Organization on a Tier; null takes it off any Tier. A subscription it pays for
    ends at once."""
    return service.assign(organization_id, data.tier_id, context)

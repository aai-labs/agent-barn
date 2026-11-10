from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.organizations.models import PlatformOrganizationRead
from api.domains.organizations.service import OrganizationService
from api.domains.tiers.holds import TierHoldService
from api.domains.tiers.repository import TierRepository


@inject
@singleton
@dataclass
class TierAssignmentService:
    """A Platform Administrator putting an Organization on a Tier, or taking it off any."""

    repository: TierRepository
    holds: TierHoldService
    organizations: OrganizationService
    event_delivery_dispatcher: EventDeliveryDispatcher

    def assign(
        self, organization_id: UUID, tier_id: UUID | None, context: CurrentUserContext
    ) -> PlatformOrganizationRead:
        """Any Tier in the catalog may be assigned, offered or not. What the Organization
        already runs is kept: a lower Tier only refuses new use until its holds apply."""
        context.require_platform_admin()
        tier = None
        if tier_id is not None:
            tier = self.repository.get(tier_id)
            if tier is None:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Tier not found")
        actor = resolve_actor_identity(context, organization_id)
        actor_display = context.user.full_name or context.user.email
        result = self.repository.assign_with_event(organization_id, tier, actor=actor, actor_display=actor_display)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Organization {organization_id} not found"
            )
        self.event_delivery_dispatcher.enqueue_immediate(result[1])
        self.holds.apply(organization_id, actor=actor, actor_display=actor_display)
        return self.organizations.get_platform_organization(organization_id)

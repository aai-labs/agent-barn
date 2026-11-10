from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError

from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher
from api.domains.tiers.holds import TierHoldService
from api.domains.tiers.models import (
    NONE_TIER_KEY,
    Tier,
    TierActivation,
    TierCreate,
    TierRead,
    TierUpdate,
    check_tier_values,
)
from api.domains.tiers.repository import Actor, TierRepository

# The settings that decide what an Organization on the Tier may keep.
_COVERAGE_SETTINGS = frozenset({"agent_limit", "allowed_platform_keys", "features"})


def to_read(tier: Tier) -> TierRead:
    return TierRead.model_validate(tier, from_attributes=True)


def _conflict(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail)


def _not_found() -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tier not found")


def _invalid(error: ValueError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error))


@inject
@singleton
@dataclass
class TierService:
    """The Tier catalog, kept by Platform Administrators.

    Authorization is the route's `require_platform_admin`: the catalog is a Platform
    Resource. The rules that keep it usable live here and in the database: what each
    activation requires, unique keys and names, a key and activation that never change, the
    system's Free and none Tiers that are never deleted, and none, which never changes.
    """

    repository: TierRepository
    event_delivery_dispatcher: EventDeliveryDispatcher
    holds: TierHoldService

    def list_tiers(self) -> list[TierRead]:
        return [to_read(tier) for tier in self.repository.list_all()]

    def create_tier(self, data: TierCreate, context: CurrentUserContext) -> TierRead:
        if self.repository.key_taken(data.key):
            raise _conflict(f"A tier with the key {data.key!r} already exists")
        if self.repository.name_taken(data.name):
            raise _conflict(f"A tier named {data.name!r} already exists")
        try:
            result = self.repository.create_with_event(Tier(**data.model_dump()), actor=_actor(context))
        except IntegrityError:
            raise _conflict("A tier with that key or name already exists") from None
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return to_read(result.tier)

    def update_tier(self, tier_id: UUID, data: TierUpdate, context: CurrentUserContext) -> TierRead:
        changes = data.changes()
        tier = self.repository.get(tier_id)
        if tier is None:
            raise _not_found()
        if tier.key == NONE_TIER_KEY:
            raise _conflict("The none tier is part of the system and can't be changed.")
        sent = data.model_fields_set

        def kept[T](setting: str, stored: T) -> T:
            return getattr(data, setting) if setting in sent else stored

        try:
            check_tier_values(
                TierActivation(tier.activation),
                price_usd=kept("price_usd", tier.price_usd),
                monthly_usage_usd=kept("monthly_usage_usd", tier.monthly_usage_usd),
                one_time_credit_usd=kept("one_time_credit_usd", tier.one_time_credit_usd),
                agent_limit=kept("agent_limit", tier.agent_limit),
                enabled=kept("enabled", tier.enabled),
                contact_url=kept("contact_url", tier.contact_url),
            )
        except ValueError as error:
            raise _invalid(error) from None
        if data.name is not None and self.repository.name_taken(data.name, excluding=tier_id):
            raise _conflict(f"A tier named {data.name!r} already exists")
        try:
            result = self.repository.update_with_events(tier_id, changes, actor=_actor(context))
        except IntegrityError:
            raise _conflict("The catalog changed while saving. Reload and try again.") from None
        if result is None:
            raise _not_found()
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        # A Tier edited down holds, in every Organization on it, what it no longer covers.
        if result.delivery_ids and _COVERAGE_SETTINGS & changes.keys():
            self.holds.apply_for_tier(tier_id, context)
        return to_read(result.tier)

    def delete_tier(self, tier_id: UUID, context: CurrentUserContext) -> None:
        tier = self.repository.get(tier_id)
        if tier is None:
            raise _not_found()
        if tier.is_system:
            raise _conflict(f"The {tier.name} tier is part of the system and can't be deleted.")
        try:
            result = self.repository.delete_with_event(tier_id, actor=_actor(context))
        except IntegrityError:
            raise _conflict("Organizations are on this tier. Disable it instead, so it isn't offered.") from None
        if result is None:
            raise _not_found()
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)


def _actor(context: CurrentUserContext) -> Actor:
    return Actor(user_id=context.user.id, display=context.user.full_name or context.user.email)

"""Applying Stripe's subscription events.

Stripe sends events out of order and more than once, so an event only names the
subscription it is about: the subscription is read from Stripe as it is now and Agent
Barn's copy is brought in line with it, one subscription at a time. Applying the same state
twice changes nothing.
"""

import logging
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from injector import inject, singleton

from api.domains.events import ActorIdentity, ActorIdentityType
from api.domains.subscriptions.models import SubscriptionProviderKey, SubscriptionStatus
from api.domains.subscriptions.repository import SubscriptionRepository
from api.domains.subscriptions.service import SubscriptionService, _Actor
from api.domains.tiers.models import Tier, TierActivation
from api.domains.tiers.repository import TierRepository
from api.infrastructure.stripe.subscriptions import StripeSubscriptions, StripeSubscriptionState

logger = logging.getLogger(__name__)

STRIPE = _Actor(ActorIdentity(type=ActorIdentityType.SYSTEM, id="stripe"), "Stripe")
_PAID = frozenset({"active", "trialing"})
_FAILING = frozenset({"past_due", "unpaid"})
_ENDED = frozenset({"canceled", "incomplete_expired"})
# Stripe's times are whole seconds; Agent Barn's carry microseconds.
_SAME_MOMENT = timedelta(seconds=1)


def subscription_reference(event_type: str, data: dict[str, Any]) -> str | None:
    """The Stripe subscription an event is about, or None when it isn't about one."""
    if event_type.startswith("customer.subscription."):
        return data.get("id")
    if event_type.startswith("checkout.session."):
        return _id(data.get("subscription")) if data.get("mode") == "subscription" else None
    if event_type.startswith("invoice."):
        parent = ((data.get("parent") or {}).get("subscription_details") or {}).get("subscription")
        return _id(data.get("subscription") or parent)
    return None


def _id(value: Any) -> str | None:
    return value.get("id") if isinstance(value, dict) else value


@inject
@singleton
@dataclass
class StripeSubscriptionSync:
    service: SubscriptionService
    repository: SubscriptionRepository
    tiers: TierRepository
    stripe: StripeSubscriptions

    def handle(self, event_type: str, data: dict[str, Any]) -> None:
        reference = subscription_reference(event_type, data)
        if reference is None:
            return
        with self.repository.provider_lock(reference):
            self.apply(self.stripe.subscription(reference))

    def apply(self, state: StripeSubscriptionState) -> None:
        tier = self._tier(state.price.lookup_key)
        local = self.repository.by_provider_reference(SubscriptionProviderKey.STRIPE.value, state.id)
        if local is None:
            self._start(state, tier)
            return
        if local.status == SubscriptionStatus.CANCELED.value:
            return
        if state.status in _ENDED:
            self.service.finish(local, STRIPE)
            return
        if tier is not None and tier.id != local.tier_id:
            local = self.service.apply_tier(local, tier, STRIPE)
        if state.period_start > local.current_period_start + _SAME_MOMENT:
            local = self.service.renew_period(
                local,
                period_start=state.period_start,
                period_end=state.period_end,
                actor=STRIPE,
                paid=state.status in _PAID,
            )
        local = self.service.set_payment_failed(local, state.status in _FAILING, STRIPE)
        local = self.service.note_cancel_at_period_end(local, state.cancel_at_period_end, STRIPE)
        if state.schedule_id is None and local.scheduled_tier_id is not None:
            # The scheduled change was dropped at Stripe.
            local.scheduled_tier_id = None
            local.provider_schedule_id = None
            self.repository.save(local)

    def _start(self, state: StripeSubscriptionState, tier: Tier | None) -> None:
        if state.status not in _PAID:
            # Not paid yet, or already over: the event that pays for it starts it.
            return
        if state.organization_id is None or tier is None:
            logger.info("Ignoring Stripe subscription %s: it isn't for an Agent Barn Tier", state.id)
            return
        live = self.repository.live_for(state.organization_id)
        if live is not None:
            logger.error(
                "Stripe subscription %s was paid for Organization %s, which already has subscription %s",
                state.id,
                state.organization_id,
                live.id,
            )
            return
        subscription = self.service.activate(
            state.organization_id,
            tier,
            provider=SubscriptionProviderKey.STRIPE,
            provider_subscription_id=state.id,
            period_start=state.period_start,
            period_end=state.period_end,
            actor=STRIPE,
        )
        if state.cancel_at_period_end:
            self.service.note_cancel_at_period_end(subscription, True, STRIPE)

    def _tier(self, key: str | None) -> Tier | None:
        if not key:
            return None
        return next(
            (tier for tier in self.tiers.list_all() if tier.key == key and tier.activation == TierActivation.PAID),
            None,
        )

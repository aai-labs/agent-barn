"""Stripe as a subscription provider.

Subscribing goes through Stripe's hosted Checkout; the subscription starts when Stripe
reports it paid (`StripeSubscriptionSync`). Each Tier's monthly Price is found by its lookup
key, the Tier's key, and must charge what the Tier costs. A bigger Tier is charged for at
once, prorated; a smaller one waits for the period's end on a subscription schedule. Stripe
renews, retries failed payments and cancels; its events drive the rest.
"""

from dataclasses import dataclass
from typing import ClassVar

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.billing.repository import BillingCustomerRepository, BillingSettingsRepository
from api.domains.subscriptions.models import Buyer, OrganizationSubscription, ProviderStart, SubscriptionProviderKey
from api.domains.tiers.models import Tier
from api.infrastructure.stripe.subscriptions import StripePrice, StripeSubscriptions


def cents(amount) -> int:
    return int((amount * 100).to_integral_value())


@inject
@singleton
@dataclass
class StripeSubscriptionProvider:
    key: ClassVar[SubscriptionProviderKey] = SubscriptionProviderKey.STRIPE
    config: Config
    settings: BillingSettingsRepository
    customers: BillingCustomerRepository
    stripe: StripeSubscriptions

    def available(self) -> bool:
        """Wherever the platform takes payments, as for buying credit."""
        return self.config.payments_configured and self.settings.read().payments_enabled

    def price(self, tier: Tier) -> StripePrice:
        """The Tier's monthly Price, refused unless it charges what Agent Barn shows."""
        price = self.stripe.price_for(tier.key)
        if (
            price is None
            or price.unit_amount != cents(tier.price_usd)
            or price.currency != "usd"
            or price.interval != "month"
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"{tier.name} can't be paid for yet. Please contact support.",
            )
        return price

    def begin(self, buyer: Buyer, tier: Tier) -> ProviderStart:
        price = self.price(tier)
        customer_id = self.stripe.customer(
            self.customers.get_customer_id(buyer.organization_id),
            organization_id=buyer.organization_id,
            name=buyer.organization_name,
            email=buyer.email,
        )
        customer_id = self.customers.save_customer_id(buyer.organization_id, customer_id)
        url = self.stripe.checkout(
            customer_id=customer_id,
            price_id=price.id,
            organization_id=buyer.organization_id,
            tier_key=tier.key,
            success_url=f"{buyer.return_url}?subscription=started",
            cancel_url=f"{buyer.return_url}?subscription=cancelled",
        )
        return ProviderStart(activate_now=False, redirect_url=url)

    def renews_itself(self) -> bool:
        return False

    def cancel_at_period_end(self, subscription: OrganizationSubscription, cancel: bool) -> None:
        # A subscription on a schedule can't be cancelled through the subscription itself.
        if cancel:
            self._release(subscription)
        self.stripe.set_cancel_at_period_end(self._reference(subscription), cancel)

    def upgrade_now(self, subscription: OrganizationSubscription, tier: Tier) -> None:
        price = self.price(tier)
        self._release(subscription)
        self.stripe.change_price_now(self.stripe.subscription(self._reference(subscription)), price.id)

    def schedule_change(self, subscription: OrganizationSubscription, tier: Tier) -> str | None:
        price = self.price(tier)
        return self.stripe.schedule_price_change(self.stripe.subscription(self._reference(subscription)), price.id)

    def cancel_scheduled_change(self, subscription: OrganizationSubscription) -> None:
        self._release(subscription)

    def end_now(self, subscription: OrganizationSubscription) -> None:
        self.stripe.cancel_now(self._reference(subscription))

    def portal_url(self, subscription: OrganizationSubscription, return_url: str) -> str | None:
        customer_id = self.customers.get_customer_id(subscription.organization_id)
        return self.stripe.portal_url(customer_id, return_url) if customer_id else None

    def _release(self, subscription: OrganizationSubscription) -> None:
        """Take the subscription off any schedule. Asked of Stripe, since a schedule stays
        attached for a while after its change took effect."""
        schedule_id = self.stripe.subscription(self._reference(subscription)).schedule_id
        if schedule_id:
            self.stripe.release_schedule(schedule_id)

    @staticmethod
    def _reference(subscription: OrganizationSubscription) -> str:
        if not subscription.provider_subscription_id:
            raise RuntimeError(f"Stripe subscription {subscription.id} has no Stripe reference")
        return subscription.provider_subscription_id

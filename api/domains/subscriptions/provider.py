"""The seam a payment provider plugs into.

`SubscriptionService` asks the active provider to begin a subscription. A provider that
takes the payment itself, like the mock, activates at once; one that sends the buyer to its
own page returns where to send them and later calls `SubscriptionService.activate`, `renew`
and `end` from its verified events. Everything else (Tiers, credit, holds, audit) stays in
the service, whichever provider took the payment.
"""

from dataclasses import dataclass
from typing import ClassVar, Protocol
from uuid import uuid4

from injector import inject, singleton

from api.core.config import Config
from api.domains.subscriptions.models import Buyer, OrganizationSubscription, ProviderStart, SubscriptionProviderKey
from api.domains.subscriptions.stripe_provider import StripeSubscriptionProvider
from api.domains.tiers.models import Tier, TierActivation
from api.domains.tiers.repository import TierRepository


class SubscriptionProvider(Protocol):
    key: ClassVar[SubscriptionProviderKey]

    def available(self) -> bool: ...

    def begin(self, buyer: Buyer, tier: Tier) -> ProviderStart: ...

    def renews_itself(self) -> bool:
        """True when Agent Barn renews each period; False when the provider reports renewals."""
        ...

    def cancel_at_period_end(self, subscription: OrganizationSubscription, cancel: bool) -> None:
        """Also drops a scheduled change: a cancellation ends the subscription as it is."""
        ...

    def upgrade_now(self, subscription: OrganizationSubscription, tier: Tier) -> None:
        """Move to a bigger Tier now, charging what it costs for the rest of the period.
        Raises PaymentDeclined when that payment fails; then nothing changes."""
        ...

    def schedule_change(self, subscription: OrganizationSubscription, tier: Tier) -> str | None:
        """Move to a smaller Tier when the period ends. Returns the provider's record of it."""
        ...

    def cancel_scheduled_change(self, subscription: OrganizationSubscription) -> None: ...

    def end_now(self, subscription: OrganizationSubscription) -> None:
        """Stop charging at once, for a subscription whose payment grace period ran out."""
        ...

    def portal_url(self, subscription: OrganizationSubscription, return_url: str) -> str | None:
        """The provider's page for the card, billing details and invoices, if it has one."""
        ...


@inject
@singleton
@dataclass
class MockSubscriptionProvider:
    """A pretend payment: subscribing succeeds at once and nothing is charged. Only where
    the deployment turns on `TIERS_MOCK_PAYMENTS`. A scheduled change waits for the period's
    end, which `SubscriptionService` applies when it renews."""

    key: ClassVar[SubscriptionProviderKey] = SubscriptionProviderKey.MOCK
    config: Config

    def available(self) -> bool:
        return self.config.tiers_mock_payments

    def begin(self, buyer: Buyer, tier: Tier) -> ProviderStart:
        return ProviderStart(activate_now=True, provider_subscription_id=f"mock_{uuid4().hex}")

    def renews_itself(self) -> bool:
        return True

    def cancel_at_period_end(self, subscription: OrganizationSubscription, cancel: bool) -> None:
        return None

    def upgrade_now(self, subscription: OrganizationSubscription, tier: Tier) -> None:
        return None

    def schedule_change(self, subscription: OrganizationSubscription, tier: Tier) -> str | None:
        return None

    def cancel_scheduled_change(self, subscription: OrganizationSubscription) -> None:
        return None

    def end_now(self, subscription: OrganizationSubscription) -> None:
        return None

    def portal_url(self, subscription: OrganizationSubscription, return_url: str) -> str | None:
        return None


@inject
@singleton
@dataclass
class SubscriptionProviders:
    """The provider that takes new subscriptions, and whether anything can be bought with
    it. Apart from `SubscriptionService`, so sign-up and Organization creation can ask
    without depending on it. Stripe takes them wherever the platform takes payments;
    otherwise the demo provider, where the deployment allows it."""

    mock: MockSubscriptionProvider
    stripe: StripeSubscriptionProvider
    tiers: TierRepository

    def active(self) -> SubscriptionProvider | None:
        if self.stripe.available():
            return self.stripe
        return self.mock if self.mock.available() else None

    def for_key(self, key: str) -> SubscriptionProvider:
        return self.stripe if key == SubscriptionProviderKey.STRIPE.value else self.mock

    def paid_tiers_purchasable(self) -> bool:
        """Whether an Organization could subscribe to a paid Tier now."""
        return self.active() is not None and any(
            tier.activation == TierActivation.PAID for tier in self.tiers.list_offered()
        )

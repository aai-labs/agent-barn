"""Stripe Billing for Tier subscriptions: monthly Prices found by lookup key, hosted
Checkout to subscribe, changing or scheduling a subscription's Price, cancelling, and the
customer portal.

Calls are synchronous, as `SubscriptionService` is. What callers get back are small
read-only views, so nothing outside this module depends on the SDK's objects.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import stripe
from injector import inject, singleton

from api.core.config import Config
from api.infrastructure.stripe.client import PaymentProviderUnavailable, StripeNotConfigured

# On Products and Prices the setup script creates, the Tier they belong to.
TIER_KEY_METADATA = "agent_barn_tier"
# The customer portal configuration the setup script keeps, found by this metadata.
PORTAL_CONFIGURATION_METADATA = {"agent_barn": "tiers"}
# What the webhook endpoint must send for subscriptions, beside the credit purchase's events.
SUBSCRIPTION_WEBHOOK_EVENTS = (
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
)


class PaymentDeclined(RuntimeError):
    """Stripe couldn't take a payment needed now, such as an upgrade's prorated charge."""


@dataclass(frozen=True)
class StripePrice:
    id: str
    lookup_key: str | None
    unit_amount: int
    currency: str
    interval: str | None


@dataclass(frozen=True)
class StripeSubscriptionState:
    """A subscription as Stripe has it now."""

    id: str
    customer_id: str
    # active, past_due, unpaid, canceled, incomplete, incomplete_expired, trialing, paused
    status: str
    organization_id: UUID | None
    item_id: str
    price: StripePrice
    period_start: datetime
    period_end: datetime
    cancel_at_period_end: bool
    schedule_id: str | None


def _when(seconds: int | None) -> datetime:
    return datetime.fromtimestamp(seconds or 0, tz=UTC)


def _id(value: Any) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return value.get("id")


def price_from(data: dict[str, Any]) -> StripePrice:
    recurring = data.get("recurring") or {}
    return StripePrice(
        id=data["id"],
        lookup_key=data.get("lookup_key"),
        unit_amount=int(data.get("unit_amount") or 0),
        currency=data.get("currency") or "",
        interval=recurring.get("interval"),
    )


def subscription_from(data: dict[str, Any]) -> StripeSubscriptionState:
    """Read a subscription object, from the API or an event. Periods are on the item in
    current API versions and on the subscription in older ones."""
    item = data["items"]["data"][0]
    organization = (data.get("metadata") or {}).get("organization_id")
    try:
        organization_id = UUID(organization) if organization else None
    except ValueError:
        organization_id = None
    return StripeSubscriptionState(
        id=data["id"],
        customer_id=_id(data.get("customer")) or "",
        status=data.get("status") or "",
        organization_id=organization_id,
        item_id=item["id"],
        price=price_from(item["price"]),
        period_start=_when(item.get("current_period_start") or data.get("current_period_start")),
        period_end=_when(item.get("current_period_end") or data.get("current_period_end")),
        cancel_at_period_end=bool(data.get("cancel_at_period_end")),
        schedule_id=_id(data.get("schedule")),
    )


@inject
@singleton
class StripeSubscriptions:
    def __init__(self, config: Config) -> None:
        self.secret_key = config.stripe_secret_key
        self._client: stripe.StripeClient | None = None
        self._portal_configuration: str | None = None

    def _stripe(self) -> stripe.StripeClient:
        if not self.secret_key:
            raise StripeNotConfigured("STRIPE_SECRET_KEY is not set")
        if self._client is None:
            self._client = stripe.StripeClient(self.secret_key)
        return self._client

    def price_for(self, lookup_key: str) -> StripePrice | None:
        """The active Price with this lookup key, the Tier's key."""
        try:
            prices = self._stripe().v1.prices.list(params={"lookup_keys": [lookup_key], "active": True, "limit": 1})
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc
        return price_from(prices.data[0].to_dict()) if prices.data else None

    def customer(self, existing: str | None, *, organization_id: UUID, name: str, email: str) -> str:
        """The Organization's Customer, created when it has none; receipts go to `email`."""
        try:
            if existing:
                self._stripe().v1.customers.update(existing, params={"email": email})
                return existing
            customer = self._stripe().v1.customers.create(
                params={"name": name, "email": email, "metadata": {"organization_id": str(organization_id)}}
            )
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc
        return customer.id

    def checkout(
        self,
        *,
        customer_id: str,
        price_id: str,
        organization_id: UUID,
        tier_key: str,
        success_url: str,
        cancel_url: str,
    ) -> str:
        """Stripe's page to subscribe; the subscription carries the Organization, so its
        events can be matched without a record of the session."""
        metadata = {"organization_id": str(organization_id), TIER_KEY_METADATA: tier_key}
        try:
            session = self._stripe().v1.checkout.sessions.create(
                params={
                    "mode": "subscription",
                    "customer": customer_id,
                    "client_reference_id": str(organization_id),
                    "line_items": [{"price": price_id, "quantity": 1}],
                    "metadata": metadata,
                    "subscription_data": {"metadata": metadata},
                    "success_url": success_url,
                    "cancel_url": cancel_url,
                }
            )
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc
        if not session.url:
            raise PaymentProviderUnavailable("Stripe returned a Checkout Session without a URL")
        return session.url

    def subscription(self, subscription_id: str) -> StripeSubscriptionState:
        try:
            data = self._stripe().v1.subscriptions.retrieve(subscription_id)
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc
        return subscription_from(data.to_dict())

    def change_price_now(self, state: StripeSubscriptionState, price_id: str) -> StripeSubscriptionState:
        """Move to `price_id` at once and charge the prorated difference now. PaymentDeclined
        when the charge fails, in which case nothing changes."""
        try:
            data = self._stripe().v1.subscriptions.update(
                state.id,
                params={
                    "items": [{"id": state.item_id, "price": price_id}],
                    "proration_behavior": "always_invoice",
                    "payment_behavior": "error_if_incomplete",
                },
            )
        except stripe.CardError as exc:
            raise PaymentDeclined(exc.user_message or "Your card was declined.") from exc
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc
        return subscription_from(data.to_dict())

    def schedule_price_change(self, state: StripeSubscriptionState, price_id: str) -> str:
        """Keep the current Price to the period's end, then move to `price_id`. Returns the
        schedule, which a later change of mind releases."""
        try:
            schedule_id = state.schedule_id or (
                self._stripe().v1.subscription_schedules.create(params={"from_subscription": state.id}).id
            )
            schedule = self._stripe().v1.subscription_schedules.retrieve(schedule_id).to_dict()
            phase = schedule.get("current_phase") or {}
            self._stripe().v1.subscription_schedules.update(
                schedule_id,
                params={
                    "end_behavior": "release",
                    "phases": [
                        {
                            "items": [{"price": state.price.id, "quantity": 1}],
                            "start_date": phase.get("start_date") or int(state.period_start.timestamp()),
                            "end_date": phase.get("end_date") or int(state.period_end.timestamp()),
                            "proration_behavior": "none",
                        },
                        {
                            "items": [{"price": price_id, "quantity": 1}],
                            "duration": {"interval": "month", "interval_count": 1},
                            "proration_behavior": "none",
                        },
                    ],
                },
            )
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc
        return schedule_id

    def release_schedule(self, schedule_id: str) -> None:
        """Drop a scheduled change; the subscription carries on as it is."""
        try:
            self._stripe().v1.subscription_schedules.release(schedule_id)
        except stripe.InvalidRequestError as exc:
            # Already released or completed: nothing is scheduled any more.
            if "release" not in str(exc).lower() and "status" not in str(exc).lower():
                raise PaymentProviderUnavailable(str(exc)) from exc
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc

    def set_cancel_at_period_end(self, subscription_id: str, cancel: bool) -> None:
        try:
            self._stripe().v1.subscriptions.update(subscription_id, params={"cancel_at_period_end": cancel})
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc

    def cancel_now(self, subscription_id: str) -> None:
        try:
            self._stripe().v1.subscriptions.cancel(subscription_id)
        except stripe.InvalidRequestError as exc:
            # Already cancelled.
            if exc.code != "resource_missing" and "canceled" not in str(exc).lower():
                raise PaymentProviderUnavailable(str(exc)) from exc
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc

    def portal_url(self, customer_id: str, return_url: str) -> str:
        """Stripe's page for the card, billing details and invoices."""
        try:
            session = self._stripe().v1.billing_portal.sessions.create(
                params={
                    "customer": customer_id,
                    "return_url": return_url,
                    **({"configuration": c} if (c := self._portal_configuration_id()) else {}),
                }
            )
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc
        return session.url

    def _portal_configuration_id(self) -> str | None:
        """The configuration the setup script keeps; None falls back to the account's default."""
        if self._portal_configuration is None:
            for configuration in (
                self._stripe().v1.billing_portal.configurations.list(params={"active": True, "limit": 100})
            ).auto_paging_iter():
                metadata = configuration.to_dict().get("metadata") or {}
                if all(metadata.get(k) == v for k, v in PORTAL_CONFIGURATION_METADATA.items()):
                    self._portal_configuration = configuration.id
                    break
        return self._portal_configuration

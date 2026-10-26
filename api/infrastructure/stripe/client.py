"""Stripe: one Customer per Organization, hosted Checkout for one-off credit purchases,
and verification of Stripe's signed webhooks.

Card details never reach Agent Barn: payment happens on Stripe's own page, and what comes
back is a signed event. Calls out to Stripe are async (over httpx); verifying a webhook is
local and needs no call at all.
"""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

import stripe
from injector import inject, singleton

from api.core.config import Config

# What the purchase is called on Stripe's page and the receipt.
_PRODUCT_NAME = "Model credit"


@dataclass(frozen=True)
class CheckoutSession:
    id: str
    url: str


class StripeNotConfigured(RuntimeError):
    """Payments are on but the deployment has no Stripe key or webhook secret."""


class PaymentProviderUnavailable(RuntimeError):
    """Stripe refused or couldn't be reached; the caller may try again."""


@inject
@singleton
class StripeGateway:
    def __init__(self, config: Config) -> None:
        self.secret_key = config.stripe_secret_key
        self.webhook_secret = config.stripe_webhook_secret
        self._client: stripe.StripeClient | None = None

    def _stripe(self) -> stripe.StripeClient:
        if not self.secret_key:
            raise StripeNotConfigured("STRIPE_SECRET_KEY is not set")
        if self._client is None:
            self._client = stripe.StripeClient(self.secret_key, http_client=stripe.HTTPXClient())
        return self._client

    async def create_customer(self, *, organization_id: UUID, name: str, email: str | None) -> str:
        params: dict = {"name": name, "metadata": {"organization_id": str(organization_id)}}
        if email:
            params["email"] = email
        try:
            customer = await self._stripe().v1.customers.create_async(params=params)  # ty: ignore[invalid-argument-type]
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc
        return customer.id

    async def create_checkout_session(
        self,
        *,
        customer_id: str,
        organization_id: UUID,
        purchased_by_user_id: UUID,
        credit_usd: Decimal,
        amount_cents: int,
        success_url: str,
        cancel_url: str,
    ) -> CheckoutSession:
        """A one-off payment of `amount_cents` for `credit_usd` of credit. The credit, the
        Organization and who is buying travel in the session's metadata, which only we
        write, so the webhook grants exactly what was bought."""
        metadata = {
            "organization_id": str(organization_id),
            "credit_usd": str(credit_usd),
            # What we charge for it, so the webhook can check the payment matches.
            "amount_cents": str(amount_cents),
            "purchased_by_user_id": str(purchased_by_user_id),
        }
        params = {
            "mode": "payment",
            "customer": customer_id,
            "client_reference_id": str(organization_id),
            "line_items": [
                {
                    "quantity": 1,
                    "price_data": {
                        "currency": "usd",
                        "unit_amount": amount_cents,
                        "product_data": {"name": _PRODUCT_NAME},
                    },
                }
            ],
            "metadata": metadata,
            # Refunds and disputes arrive against the payment, not the session.
            "payment_intent_data": {"metadata": metadata},
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        try:
            session = await self._stripe().v1.checkout.sessions.create_async(params=params)  # ty: ignore[invalid-argument-type]
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc
        if not session.url:
            raise PaymentProviderUnavailable("Stripe returned a Checkout Session without a URL")
        return CheckoutSession(id=session.id, url=session.url)

    async def update_customer_email(self, customer_id: str, email: str) -> None:
        """Send receipts to whoever is buying now, not whoever bought first."""
        try:
            await self._stripe().v1.customers.update_async(customer_id, params={"email": email})
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc

    async def refund_status(self, refund_id: str) -> str:
        """The refund's status now: Stripe doesn't deliver events in order, so an event's
        own copy may be out of date. PaymentProviderUnavailable when it can't be read."""
        try:
            refund = await self._stripe().v1.refunds.retrieve_async(refund_id)
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc
        return refund.status or ""

    async def payment_metadata(self, payment_intent_id: str) -> dict[str, str]:
        """What a payment was tagged with when it was made: a credit purchase carries its
        Organization and credit. Empty for anyone else's payment."""
        try:
            payment = await self._stripe().v1.payment_intents.retrieve_async(payment_intent_id)
        except stripe.StripeError as exc:
            raise PaymentProviderUnavailable(str(exc)) from exc
        metadata = payment.to_dict().get("metadata") or {}
        return {str(key): str(value) for key, value in metadata.items()}

    def construct_event(self, payload: bytes, signature: str) -> stripe.Event:
        """The event Stripe signed, or PermissionError when the signature doesn't verify."""
        if not self.webhook_secret:
            raise StripeNotConfigured("STRIPE_WEBHOOK_SECRET is not set")
        try:
            return stripe.Webhook.construct_event(payload, signature, self.webhook_secret)
        except stripe.SignatureVerificationError as exc:
            raise PermissionError("Stripe signature verification failed") from exc

"""Set up a Stripe account for Tier subscriptions, from the Tier catalog.

For every paid Tier: a Product and a monthly Price whose lookup key is the Tier's key, at
the Tier's price. A Price whose amount no longer matches is replaced by a new one that takes
over the lookup key, so existing subscribers keep what they pay. Also the customer portal's
configuration, and, given `--webhook-url`, the events that endpoint must send. Safe to run
again: it changes only what differs.

Run against the sandbox, then the live account, with a key allowed to write Products, Prices,
the customer portal and webhook endpoints:

    python -c "from api.domains.subscriptions.stripe_setup import main; main()" [--dry-run]

Stripe's failed-payment retries can't be set through the API: set them in the Dashboard
(retry for the payment grace period, then cancel the subscription).
"""

import argparse
import logging
from decimal import Decimal
from typing import Any

import stripe

from api.domains.tiers.models import Tier, TierActivation
from api.infrastructure.stripe.subscriptions import (
    PORTAL_CONFIGURATION_METADATA,
    SUBSCRIPTION_WEBHOOK_EVENTS,
    TIER_KEY_METADATA,
)

logger = logging.getLogger(__name__)

# The events the credit purchase already needs; the endpoint keeps them.
CREDIT_WEBHOOK_EVENTS = (
    "checkout.session.completed",
    "checkout.session.async_payment_succeeded",
    "refund.created",
    "refund.updated",
    "refund.failed",
    "charge.dispute.funds_withdrawn",
    "charge.dispute.funds_reinstated",
)

_PORTAL_FEATURES: dict[str, Any] = {
    "customer_update": {"enabled": True, "allowed_updates": ["email", "name", "address"]},
    "invoice_history": {"enabled": True},
    "payment_method_update": {"enabled": True},
    "subscription_cancel": {"enabled": True, "mode": "at_period_end", "proration_behavior": "none"},
    # Switching happens in Agent Barn, which says what a smaller Tier would put on hold.
    "subscription_update": {"enabled": False},
}


def cents(amount: Decimal) -> int:
    return int((amount * 100).to_integral_value())


class StripeSetup:
    def __init__(self, client: stripe.StripeClient, *, dry_run: bool) -> None:
        self.client = client
        self.dry_run = dry_run

    def _act(self, what: str) -> bool:
        logger.info("%s%s", "[dry run] " if self.dry_run else "", what)
        return not self.dry_run

    def tier_price(self, tier: Tier) -> None:
        amount = cents(tier.price_usd)
        prices = self.client.v1.prices.list(params={"lookup_keys": [tier.key], "active": True, "limit": 1}).data
        current = prices[0] if prices else None
        if current is not None and current.unit_amount == amount and current.currency == "usd":
            logger.info("%s: price %s already $%s a month", tier.key, current.id, tier.price_usd)
            product_id = current.product if isinstance(current.product, str) else current.product.id
            self._name_product(product_id, tier)
            return
        product_id = (
            current.product if current is not None and isinstance(current.product, str) else self._product_for(tier)
        )
        if not self._act(f"{tier.key}: new monthly price ${tier.price_usd} with lookup key {tier.key}"):
            return
        self.client.v1.prices.create(
            params={
                "product": product_id,
                "currency": "usd",
                "unit_amount": amount,
                "recurring": {"interval": "month"},
                "lookup_key": tier.key,
                # Moves the key off a price at the old amount; its subscribers keep paying it.
                "transfer_lookup_key": True,
                "metadata": {TIER_KEY_METADATA: tier.key},
            }
        )

    def _product_for(self, tier: Tier) -> str:
        for product in self.client.v1.products.list(params={"limit": 100}).auto_paging_iter():
            if (product.to_dict().get("metadata") or {}).get(TIER_KEY_METADATA) == tier.key:
                self._name_product(product.id, tier)
                return product.id
        if not self._act(f"{tier.key}: new product {tier.name}"):
            return "prod_dry_run"
        product = self.client.v1.products.create(params={"name": tier.name, "metadata": {TIER_KEY_METADATA: tier.key}})
        return product.id

    def _name_product(self, product_id: str, tier: Tier) -> None:
        product = self.client.v1.products.retrieve(product_id)
        if product.name != tier.name and self._act(f"{tier.key}: rename product to {tier.name}"):
            self.client.v1.products.update(product_id, params={"name": tier.name})

    def portal(self, *, privacy_url: str | None, terms_url: str | None) -> None:
        params: dict[str, Any] = {
            "features": _PORTAL_FEATURES,
            "metadata": PORTAL_CONFIGURATION_METADATA,
            "business_profile": {
                "headline": "Manage your Agent Barn subscription",
                **({"privacy_policy_url": privacy_url} if privacy_url else {}),
                **({"terms_of_service_url": terms_url} if terms_url else {}),
            },
        }
        existing = next(
            (
                configuration
                for configuration in self.client.v1.billing_portal.configurations.list(
                    params={"active": True, "limit": 100}
                ).auto_paging_iter()
                if all(
                    (configuration.to_dict().get("metadata") or {}).get(k) == v
                    for k, v in PORTAL_CONFIGURATION_METADATA.items()
                )
            ),
            None,
        )
        if existing is None:
            if self._act("customer portal: new configuration"):
                self.client.v1.billing_portal.configurations.create(params=params)  # ty: ignore[invalid-argument-type]
            return
        if self._act(f"customer portal: update configuration {existing.id}"):
            self.client.v1.billing_portal.configurations.update(existing.id, params=params)  # ty: ignore[invalid-argument-type]

    def webhook(self, url: str) -> None:
        wanted = set(CREDIT_WEBHOOK_EVENTS) | set(SUBSCRIPTION_WEBHOOK_EVENTS)
        endpoint = next(
            (
                e
                for e in self.client.v1.webhook_endpoints.list(params={"limit": 100}).auto_paging_iter()
                if e.url == url
            ),
            None,
        )
        if endpoint is None:
            logger.warning(
                "No webhook endpoint for %s. Create it in the Dashboard with these events, and store its signing "
                "secret as STRIPE_WEBHOOK_SECRET: %s",
                url,
                ", ".join(sorted(wanted)),
            )
            return
        enabled = set(endpoint.enabled_events or [])
        if "*" in enabled or wanted <= enabled:
            logger.info("webhook %s already sends every event needed", url)
            return
        if self._act(f"webhook {url}: add {', '.join(sorted(wanted - enabled))}"):
            self.client.v1.webhook_endpoints.update(
                endpoint.id,
                params={"enabled_events": sorted(enabled | wanted)},  # ty: ignore[invalid-argument-type]
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="Set up Stripe for Tier subscriptions from the Tier catalog.")
    parser.add_argument("--dry-run", action="store_true", help="Say what would change without changing it.")
    parser.add_argument("--webhook-url", help="Also make sure this webhook endpoint sends the events needed.")
    parser.add_argument("--privacy-url", help="Privacy policy link shown in the customer portal.")
    parser.add_argument("--terms-url", help="Terms of service link shown in the customer portal.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # The SDK logs every request at INFO.
    logging.getLogger("stripe").setLevel(logging.WARNING)
    from api.core.config import get_config
    from api.core.utils import create_injector
    from api.domains.tiers.repository import TierRepository

    key = get_config().stripe_secret_key
    if not key:
        raise SystemExit("STRIPE_SECRET_KEY is not set")
    setup = StripeSetup(stripe.StripeClient(key), dry_run=args.dry_run)
    account = setup.client.v1.accounts.retrieve_current()
    mode = "live" if key.startswith(("sk_live_", "rk_live_")) else "test"
    logger.info("Stripe account %s (%s mode)", account.id, mode)
    for tier in create_injector().get(TierRepository).list_all():
        if tier.activation == TierActivation.PAID:
            setup.tier_price(tier)
    setup.portal(privacy_url=args.privacy_url, terms_url=args.terms_url)
    if args.webhook_url:
        setup.webhook(args.webhook_url)
    logger.info(
        "Not set through the API: in the Dashboard's billing settings, retry failed subscription payments for the "
        "payment grace period, then cancel the subscription."
    )

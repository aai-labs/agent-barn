"""The Stripe gateway (AF-381): what a credit purchase asks Stripe for, and how a webhook's
signature is checked. No network: the Stripe client is replaced."""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from hamcrest import assert_that, equal_to, has_entries

from api.domains.billing.models import BillingSettingsRead
from api.domains.billing.service import charge_cents
from api.infrastructure.stripe.client import StripeGateway, StripeNotConfigured


def gateway(secret_key="sk_test_x", webhook_secret="whsec_x") -> StripeGateway:
    return StripeGateway(MagicMock(stripe_secret_key=secret_key, stripe_webhook_secret=webhook_secret))


def test_a_credit_purchase_is_a_one_off_payment_carrying_the_organization_and_credit():
    stripe = gateway()
    client = MagicMock()
    client.v1.checkout.sessions.create_async = AsyncMock(return_value=MagicMock(id="cs_1", url="https://pay"))
    organization_id = uuid4()

    with patch.object(StripeGateway, "_stripe", return_value=client):
        session = asyncio.run(
            stripe.create_checkout_session(
                customer_id="cus_1",
                organization_id=organization_id,
                credit_usd=Decimal(20),
                amount_cents=2110,
                success_url="https://app/ok",
                cancel_url="https://app/no",
            )
        )

    call = client.v1.checkout.sessions.create_async.await_args
    assert call is not None
    params = call.kwargs["params"]
    metadata = {"organization_id": str(organization_id), "credit_usd": "20"}
    assert_that((session.id, session.url), equal_to(("cs_1", "https://pay")))
    assert_that(
        params,
        has_entries(mode="payment", customer="cus_1", metadata=metadata, payment_intent_data={"metadata": metadata}),
    )
    assert_that(params["line_items"][0]["price_data"], has_entries(currency="usd", unit_amount=2110))


def test_a_new_customer_is_tagged_with_its_organization():
    stripe = gateway()
    client = MagicMock()
    client.v1.customers.create_async = AsyncMock(return_value=MagicMock(id="cus_9"))
    organization_id = uuid4()

    with patch.object(StripeGateway, "_stripe", return_value=client):
        customer_id = asyncio.run(stripe.create_customer(organization_id=organization_id, name="Acme", email=None))

    assert_that(customer_id, equal_to("cus_9"))
    call = client.v1.customers.create_async.await_args
    assert call is not None
    params = call.kwargs["params"]
    assert_that(params, equal_to({"name": "Acme", "metadata": {"organization_id": str(organization_id)}}))


def test_a_wrongly_signed_event_is_refused():
    with pytest.raises(PermissionError):
        gateway().construct_event(b'{"id": "evt_1"}', "t=1,v1=bad")


def test_nothing_reaches_stripe_without_a_key_or_secret():
    with pytest.raises(StripeNotConfigured):
        gateway(secret_key=None)._stripe()
    with pytest.raises(StripeNotConfigured):
        gateway(webhook_secret=None).construct_event(b"{}", "t=1,v1=x")


@pytest.mark.parametrize(
    "credit,rate,fee,cents",
    [
        ("20", 1.0, 0.0, 2000),
        ("20", 1.0, 5.5, 2110),
        ("20", 0.5, 10.0, 4400),
        # A fraction of a cent is rounded up, never given away.
        ("10.01", 1.0, 3.0, 1032),
    ],
)
def test_the_charge_is_the_credit_at_the_rate_plus_the_fee_rounded_up(credit, rate, fee, cents):
    settings = BillingSettingsRead(credit_rate=rate, purchase_fee_percent=fee)
    assert_that(charge_cents(Decimal(credit), settings), equal_to(cents))

"""The Stripe gateway (AF-381): what a credit purchase asks Stripe for, and how a webhook's
signature is checked. No network: the Stripe client is replaced."""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
import stripe as stripe_sdk
from hamcrest import assert_that, equal_to, has_entries

from api.domains.billing.models import BillingSettingsRead
from api.domains.billing.service import charge_cents
from api.infrastructure.stripe.client import PaymentProviderUnavailable, StripeGateway, StripeNotConfigured


def gateway(secret_key="sk_test_x", webhook_secret="whsec_x") -> StripeGateway:
    return StripeGateway(MagicMock(stripe_secret_key=secret_key, stripe_webhook_secret=webhook_secret))


def test_a_credit_purchase_is_a_one_off_payment_carrying_the_organization_credit_and_buyer():
    stripe = gateway()
    client = MagicMock()
    client.v1.checkout.sessions.create_async = AsyncMock(return_value=MagicMock(id="cs_1", url="https://pay"))
    organization_id = uuid4()
    buyer_id = uuid4()

    with patch.object(StripeGateway, "_stripe", return_value=client):
        session = asyncio.run(
            stripe.create_checkout_session(
                customer_id="cus_1",
                organization_id=organization_id,
                purchased_by_user_id=buyer_id,
                credit_usd=Decimal(20),
                amount_cents=2110,
                success_url="https://app/ok",
                cancel_url="https://app/no",
            )
        )

    call = client.v1.checkout.sessions.create_async.await_args
    assert call is not None
    params = call.kwargs["params"]
    metadata = {
        "organization_id": str(organization_id),
        "credit_usd": "20",
        "amount_cents": "2110",
        "purchased_by_user_id": str(buyer_id),
    }
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


def test_a_customers_email_is_kept_to_the_current_buyer():
    client = MagicMock()
    client.v1.customers.update_async = AsyncMock()

    with patch.object(StripeGateway, "_stripe", return_value=client):
        asyncio.run(gateway().update_customer_email("cus_1", "new@example.com"))

    client.v1.customers.update_async.assert_awaited_once_with("cus_1", params={"email": "new@example.com"})


def test_a_refunds_current_status_is_read_from_stripe():
    client = MagicMock()
    client.v1.refunds.retrieve_async = AsyncMock(return_value=MagicMock(status="canceled"))

    with patch.object(StripeGateway, "_stripe", return_value=client):
        status = asyncio.run(gateway().refund_status("re_1"))

    assert_that(status, equal_to("canceled"))
    client.v1.refunds.retrieve_async.assert_awaited_once_with("re_1")


def test_a_payments_metadata_is_read_from_stripe():
    client = MagicMock()
    client.v1.payment_intents.retrieve_async = AsyncMock(
        return_value=MagicMock(
            to_dict=MagicMock(return_value={"metadata": {"organization_id": "org", "credit_usd": "20"}})
        )
    )

    with patch.object(StripeGateway, "_stripe", return_value=client):
        metadata = asyncio.run(gateway().payment_metadata("pi_1"))

    assert_that(metadata, equal_to({"organization_id": "org", "credit_usd": "20"}))


def test_stripe_failing_is_reported_as_unavailable():
    client = MagicMock()
    client.v1.customers.create_async = AsyncMock(side_effect=stripe_sdk.APIConnectionError("down"))

    with patch.object(StripeGateway, "_stripe", return_value=client), pytest.raises(PaymentProviderUnavailable):
        asyncio.run(gateway().create_customer(organization_id=uuid4(), name="Acme", email=None))


def test_a_wrongly_signed_event_is_refused():
    with pytest.raises(PermissionError):
        gateway().construct_event(b'{"id": "evt_1"}', "t=1,v1=bad")


def test_nothing_reaches_stripe_without_a_key_or_secret():
    with pytest.raises(StripeNotConfigured):
        gateway(secret_key=None)._stripe()
    with pytest.raises(StripeNotConfigured):
        gateway(webhook_secret=None).construct_event(b"{}", "t=1,v1=x")


@pytest.mark.parametrize(
    "credit,fee,cents",
    [
        ("20", 0.0, 2000),
        ("20", 5.5, 2110),
        ("0.50", 0.0, 50),
        # A fraction of a cent is rounded up, never given away.
        ("10.01", 3.0, 1032),
        ("5.15", 33.0, 685),
        # Exact: a fee that lands on a whole cent adds nothing.
        ("1.00", 200.0, 300),
    ],
)
def test_the_charge_is_the_credit_plus_the_fee_rounded_up(credit, fee, cents):
    """$1 of credit is $1 of model spend; only the purchase fee is added."""
    settings = BillingSettingsRead(purchase_fee_percent=fee)
    assert_that(charge_cents(Decimal(credit), settings), equal_to(cents))

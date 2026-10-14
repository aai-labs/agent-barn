"""Buying credit with Stripe (AF-381).

- Payments are opt in: with `PAYMENTS_ENABLED` off, checkout and the webhook are not
  there, and the billing read says credit can't be bought.
- Only an Organization on credit buys it, and only its Owner (`billing.manage`).
- Checkout charges for the credit asked for at the platform's credit rate and purchase
  fee, within its minimum and maximum, and is paid on Stripe's own page.
- Stripe's signed webhook grants a purchase once, converts a trial, and takes refunds and
  lost disputes back off; the ledger's unique reference is what makes a redelivered event
  harmless. Stripe doesn't promise order, so a refund settles on the refund's current
  status, and one for a purchase not yet recorded is retried rather than dropped.
- Turning payments off stops new purchases only: payments already made, refunds and
  disputes still land while the deployment has a webhook secret.
"""

import asyncio
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, equal_to, has_entries, has_length, not_
from injector import Module, provider, singleton

from api.domains.billing.repository import BillingSettingsRepository
from api.domains.billing.service import BillingService
from api.domains.organizations.models import CreditGrantKind
from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import OrganizationRole
from api.domains.users.models import User
from api.domains.users.repository import UserRepository
from api.infrastructure.stripe.client import CheckoutSession, PaymentProviderUnavailable, StripeGateway
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.integration.test_credit_spend_limits import the_organization_runs_on_credit
from api.tests.integration.test_spend_limits import events_named
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.events import event_delivery_tables_are_clean
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

WEBHOOK_SECRET = "whsec_test_only_secret"
BILLING = "/api/v1/organizations/{organization_id}/billing"
CHECKOUT = "/api/v1/organizations/{organization_id}/billing/checkout"
WEBHOOK = "/api/v1/billing/stripe/webhook"
SETTINGS = "/api/v1/platform/settings/billing"


class MockStripeModule(Module):
    @provider
    @singleton
    def provide_stripe(self) -> StripeGateway:
        gateway: Any = MagicMock(spec=StripeGateway)
        gateway.create_customer = AsyncMock(return_value="cus_test")
        gateway.create_checkout_session = AsyncMock(
            return_value=CheckoutSession(id="cs_test", url="https://checkout.stripe.test/cs_test")
        )
        # The signature check is real: only the calls out to Stripe are faked.
        gateway.construct_event.side_effect = lambda payload, signature: StripeGateway.construct_event(
            gateway, payload, signature
        )
        gateway.webhook_secret = WEBHOOK_SECRET
        # Stripe's view now: refunds stand, and other payments aren't credit purchases.
        gateway.refund_status = AsyncMock(return_value="succeeded")
        gateway.payment_metadata = AsyncMock(return_value={})
        return gateway


def _setup(*steps, payments: str = "true", webhook_secret: str = WEBHOOK_SECRET) -> list:
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "WEB_APP_URL": "https://app.test",
                "PAYMENTS_ENABLED": payments,
                "STRIPE_SECRET_KEY": "sk_test_x",
                "STRIPE_WEBHOOK_SECRET": webhook_secret,
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), MockStripeModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        event_delivery_tables_are_clean(),
        *steps,
    ]


def an_owner_on_credit(*, trial: bool = True):
    def step(context):
        there_is_a_user(email="owner@example.com")(context)
        there_is_an_organization(name="Jane's Organization")(context)
        the_organization_runs_on_credit()(context)
        organizations = context.injector.get(OrganizationRepository)
        organization = organizations.get(context.organization.id)
        organization.is_trial = trial
        organization.created_by_user_id = context.user.id
        organizations.save(organization)
        organizations.record_opening_credit(context.organization.id, CreditGrantKind.TRIAL, Decimal(10))
        there_is_an_access_token_for_user()(context)

    return step


def signed_in_as(role: OrganizationRole):
    def step(context):
        there_is_a_user(email=f"{role.value.lower()}@example.com", role=role)(context)
        there_is_an_access_token_for_user()(context)

    return step


def a_platform_administrator():
    def step(context):
        there_is_a_user(email="platform@example.com", is_platform_admin=True, role=OrganizationRole.MEMBER)(context)
        there_is_an_access_token_for_user()(context)

    return step


def the_billing_settings_are(**changes):
    def step(context):
        context.injector.get(BillingSettingsRepository).set_settings(changes, context.user.id, "Platform Admin")

    return step


def auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def stripe(context) -> Any:
    return context.injector.get(StripeGateway)


def buy(context, credit_usd):
    return context.client.post(
        CHECKOUT.format(organization_id=context.organization.id), json={"credit_usd": credit_usd}, headers=auth(context)
    )


def signed(event_type: str, data: dict, *, secret: str = WEBHOOK_SECRET, event_id: str | None = None):
    """A Stripe event and its signature header."""
    payload = json.dumps(
        {"id": event_id or f"evt_{uuid7().hex}", "object": "event", "type": event_type, "data": {"object": data}}
    )
    timestamp = int(time.time())
    signature = hmac.new(secret.encode(), f"{timestamp}.{payload}".encode(), hashlib.sha256).hexdigest()
    return payload, f"t={timestamp},v1={signature}"


def deliver(context, event_type: str, data: dict, *, secret: str = WEBHOOK_SECRET, event_id: str | None = None):
    payload, signature = signed(event_type, data, secret=secret, event_id=event_id)
    return context.client.post(
        WEBHOOK, content=payload, headers={"Stripe-Signature": signature, "Content-Type": "application/json"}
    )


def refund(refund_id="re_1", *, cents=1100, intent="pi_1", status_now="succeeded") -> dict:
    return {"id": refund_id, "object": "refund", "amount": cents, "payment_intent": intent, "status": status_now}


def stripe_says_the_refund_is(context, refund_status: str) -> None:
    stripe(context).refund_status.return_value = refund_status


def stripe_says_the_payment_is_a_credit_purchase(context) -> None:
    stripe(context).payment_metadata.return_value = {
        "organization_id": str(context.organization.id),
        "credit_usd": "20",
    }


def paid_session(
    context, *, credit="20", amount_cents=2000, intent="pi_1", payment_status="paid", buyer: str | None = None
) -> dict:
    metadata = {"organization_id": str(context.organization.id), "credit_usd": credit}
    if buyer is not None:
        metadata["purchased_by_user_id"] = buyer
    return {
        "id": "cs_test",
        "object": "checkout.session",
        "payment_status": payment_status,
        "payment_intent": intent,
        "amount_total": amount_cents,
        "client_reference_id": str(context.organization.id),
        "metadata": metadata,
    }


def ledger(context) -> list[tuple[CreditGrantKind, Decimal]]:
    grants = context.injector.get(OrganizationRepository).list_credit_grants(context.organization.id)
    return [(grant.kind, grant.credit_usd) for grant in grants]


def dispute(context, *, reinstated_cents: int | None = None) -> dict:
    """A $20 dispute on the purchase; reinstated in part or whole when `reinstated_cents`."""
    transactions = [{"object": "balance_transaction", "amount": -2000}]
    if reinstated_cents is not None:
        transactions.append({"object": "balance_transaction", "amount": reinstated_cents})
    return {
        "id": "dp_1",
        "object": "dispute",
        "amount": 2000,
        "payment_intent": "pi_1",
        "balance_transactions": transactions,
    }


def stored(context):
    return context.injector.get(OrganizationRepository).get(context.organization.id)


# --- platform settings ---------------------------------------------------------------------


def test_a_platform_administrator_reads_the_billing_defaults():
    with given(_setup(a_platform_administrator())) as context:
        response = context.client.get(SETTINGS, headers=auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            response.json(),
            has_entries(
                payments_enabled=True,
                min_purchase_usd=5.0,
                max_purchase_usd=500.0,
                credit_rate=1.0,
                purchase_fee_percent=0.0,
            ),
        )


def test_a_platform_administrator_changes_the_billing_settings_and_it_is_audited():
    with given(_setup(a_platform_administrator())) as context:
        response = context.client.put(
            SETTINGS, json={"min_purchase_usd": 10, "purchase_fee_percent": 5.5}, headers=auth(context)
        )

        assert_that(response.json(), has_entries(min_purchase_usd=10.0, purchase_fee_percent=5.5))
        events = events_named(context, "platform.billing_settings.changed")
        assert_that(
            sorted(event.payload["setting"] for event in events), equal_to(["min_purchase_usd", "purchase_fee_percent"])
        )


@pytest.mark.parametrize(
    "payload",
    [{"min_purchase_usd": 600}, {"credit_rate": 0}, {"purchase_fee_percent": -1}, {"max_purchase_usd": None}],
)
def test_impossible_billing_settings_are_refused(payload):
    with given(_setup(a_platform_administrator())) as context:
        response = context.client.put(SETTINGS, json=payload, headers=auth(context))

        assert_that(
            response.status_code, equal_to(status.HTTP_400_BAD_REQUEST if "min_purchase_usd" in payload else 422)
        )


def test_a_minimum_below_what_a_card_can_be_charged_is_refused():
    with given(_setup(a_platform_administrator())) as context:
        response = context.client.put(SETTINGS, json={"min_purchase_usd": 0.49}, headers=auth(context))

        assert_that(response.status_code, equal_to(422))


def test_only_a_platform_administrator_sees_the_billing_settings():
    with given(_setup(an_owner_on_credit())) as context:
        response = context.client.get(SETTINGS, headers=auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


# --- what an Organization sees -------------------------------------------------------------


def test_an_owner_on_credit_sees_their_balance_and_history():
    with given(_setup(an_owner_on_credit())) as context:
        organizations = context.injector.get(OrganizationRepository)
        organization = organizations.get(context.organization.id)
        organization.llm_spend_usd = 2.5
        organization.llm_spend_observed_at = datetime.now(UTC)
        organizations.save(organization)

        response = context.client.get(BILLING.format(organization_id=context.organization.id), headers=auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(
            body,
            has_entries(
                available=True,
                on_credit=True,
                credit_usd=10.0,
                spend_usd=2.5,
                balance_usd=7.5,
                min_purchase_usd=5.0,
                max_purchase_usd=500.0,
            ),
        )
        assert_that(body["history"], has_length(1))
        assert_that(body["history"][0], has_entries(kind="trial", credit_usd=10.0))


def test_credit_cannot_be_bought_while_payments_are_off():
    with given(_setup(an_owner_on_credit(), payments="false")) as context:
        response = context.client.get(BILLING.format(organization_id=context.organization.id), headers=auth(context))

        assert_that(response.json(), has_entries(available=False))
        assert_that(buy(context, 20).status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_an_organization_on_a_renewing_limit_cannot_buy_credit():
    with given(
        _setup(
            there_is_a_user(email="owner@example.com"), there_is_an_organization(), there_is_an_access_token_for_user()
        )
    ) as context:
        response = context.client.get(BILLING.format(organization_id=context.organization.id), headers=auth(context))

        assert_that(response.json(), has_entries(available=False, on_credit=False))
        assert_that(buy(context, 20).status_code, equal_to(status.HTTP_400_BAD_REQUEST))


@pytest.mark.parametrize("role", [OrganizationRole.ADMIN, OrganizationRole.MEMBER])
def test_only_the_owner_buys_credit(role):
    with given(_setup(an_owner_on_credit(), signed_in_as(role))) as context:
        assert_that(
            context.client.get(
                BILLING.format(organization_id=context.organization.id), headers=auth(context)
            ).status_code,
            equal_to(status.HTTP_403_FORBIDDEN),
        )
        assert_that(buy(context, 20).status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_an_owner_cannot_read_or_buy_for_another_organization():
    with given(_setup(an_owner_on_credit())) as context:
        mine = context.organization.id
        acme_owner = User(email="acme-owner@example.com", hashed_password="x")
        context.injector.get(UserRepository).save(acme_owner)
        there_is_an_organization(name="Acme", owner_id=acme_owner.id)(context)
        the_organization_runs_on_credit()(context)
        theirs = context.organization.id

        read = context.client.get(BILLING.format(organization_id=theirs), headers=auth(context))
        bought = context.client.post(
            CHECKOUT.format(organization_id=theirs), json={"credit_usd": 20}, headers=auth(context)
        )

        assert_that([read.status_code, bought.status_code], equal_to([403, 403]))
        assert_that(theirs, not_(equal_to(mine)))
        stripe(context).create_checkout_session.assert_not_awaited()


# --- checkout ------------------------------------------------------------------------------


def test_an_owner_is_sent_to_stripe_to_pay_for_the_credit_they_chose():
    with given(_setup(an_owner_on_credit())) as context:
        with when("the owner asks for $20 of credit"):
            response = buy(context, 20)

        with then("they get Stripe's page, for $20.00, on a customer for their Organization"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(response.json(), has_entries(url="https://checkout.stripe.test/cs_test"))
            stripe(context).create_customer.assert_awaited_once()
            session = stripe(context).create_checkout_session.await_args.kwargs
            assert_that(
                session,
                has_entries(
                    customer_id="cus_test",
                    organization_id=context.organization.id,
                    credit_usd=Decimal(20),
                    amount_cents=2000,
                    purchased_by_user_id=context.user.id,
                ),
            )
            assert_that(
                session["success_url"],
                equal_to(f"https://app.test/dashboard/{context.organization.id}/billing?checkout=success"),
            )


def test_a_second_purchase_reuses_the_organizations_stripe_customer():
    with given(_setup(an_owner_on_credit())) as context:
        buy(context, 20)
        buy(context, 30)

        stripe(context).create_customer.assert_awaited_once()


def test_the_charge_includes_the_credit_rate_and_purchase_fee():
    with given(
        _setup(an_owner_on_credit(), the_billing_settings_are(credit_rate=0.5, purchase_fee_percent=10))
    ) as context:
        buy(context, 20)

        # $20 of credit at 0.5 credit per dollar is $40, plus a 10% fee.
        assert_that(stripe(context).create_checkout_session.await_args.kwargs["amount_cents"], equal_to(4400))


@pytest.mark.parametrize("credit_usd", [4.99, 500.01])
def test_a_purchase_outside_the_platforms_bounds_is_refused_before_stripe(credit_usd):
    with given(_setup(an_owner_on_credit())) as context:
        response = buy(context, credit_usd)

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        stripe(context).create_checkout_session.assert_not_awaited()


def test_a_charge_below_stripes_minimum_is_refused_before_stripe():
    with given(
        _setup(an_owner_on_credit(), the_billing_settings_are(min_purchase_usd=0.5, credit_rate=100))
    ) as context:
        # $1 of credit at 100 credit per dollar would be a one-cent charge.
        response = buy(context, 1)

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        stripe(context).create_checkout_session.assert_not_awaited()


def test_stripe_being_down_at_checkout_says_to_try_again():
    with given(_setup(an_owner_on_credit())) as context:
        stripe(context).create_checkout_session.side_effect = PaymentProviderUnavailable("down")

        response = buy(context, 20)

        assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
        assert_that(response.json()["detail"], equal_to("Payments aren't available right now. Try again shortly."))


# --- the webhook ---------------------------------------------------------------------------


def test_a_paid_checkout_grants_the_credit_and_ends_the_trial():
    with given(_setup(an_owner_on_credit())) as context:
        with when("Stripe reports the payment"):
            response = deliver(context, "checkout.session.completed", paid_session(context))

        with then("the credit is granted and the trial is over, still on credit"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(ledger(context)[-1], equal_to((CreditGrantKind.PURCHASE, Decimal(20))))
            organization = stored(context)
            assert_that((organization.llm_budget_usd, organization.is_trial), equal_to((30.0, False)))
            assert_that(events_named(context, "organization.trial.ended"), has_length(1))


def test_the_history_says_who_bought_the_credit():
    with given(_setup(an_owner_on_credit())) as context:
        users = context.injector.get(UserRepository)
        owner = users.get(context.user.id)
        owner.full_name = "Jane Owner"
        users.save(owner)

        deliver(context, "checkout.session.completed", paid_session(context, buyer=str(context.user.id)))

        history = context.client.get(
            BILLING.format(organization_id=context.organization.id), headers=auth(context)
        ).json()["history"]
        assert_that(history[0], has_entries(kind="purchase", purchased_by="Jane Owner"))
        assert_that(history[1], has_entries(kind="trial", purchased_by=None))


def test_a_purchase_by_someone_no_longer_here_still_grants_the_credit():
    with given(_setup(an_owner_on_credit())) as context:
        response = deliver(context, "checkout.session.completed", paid_session(context, buyer=str(uuid7())))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(ledger(context)[-1], equal_to((CreditGrantKind.PURCHASE, Decimal(20))))
        history = context.client.get(
            BILLING.format(organization_id=context.organization.id), headers=auth(context)
        ).json()["history"]
        # Nobody to name, and never the payment provider's name instead.
        assert_that(history[0], has_entries(kind="purchase", purchased_by=None))


def test_a_redelivered_payment_is_granted_once():
    with given(_setup(an_owner_on_credit())) as context:
        deliver(context, "checkout.session.completed", paid_session(context), event_id="evt_1")
        response = deliver(context, "checkout.session.completed", paid_session(context), event_id="evt_1")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(stored(context).llm_budget_usd, equal_to(30.0))


def test_a_delayed_payment_is_granted_when_it_succeeds():
    with given(_setup(an_owner_on_credit())) as context:
        deliver(context, "checkout.session.completed", paid_session(context, payment_status="unpaid"))
        assert_that(stored(context).llm_budget_usd, equal_to(10.0))

        deliver(context, "checkout.session.async_payment_succeeded", paid_session(context))
        assert_that(stored(context).llm_budget_usd, equal_to(30.0))


def test_a_refund_takes_its_share_of_the_credit_back_and_a_failed_one_returns_it():
    with given(_setup(an_owner_on_credit())) as context:
        deliver(context, "checkout.session.completed", paid_session(context, credit="20", amount_cents=2200))

        with when("half the payment is refunded"):
            deliver(
                context,
                "refund.created",
                {"id": "re_1", "object": "refund", "amount": 1100, "payment_intent": "pi_1", "status": "succeeded"},
            )

        with then("half the credit is taken back"):
            assert_that(ledger(context)[-1], equal_to((CreditGrantKind.REFUND, Decimal(-10))))
            assert_that(stored(context).llm_budget_usd, equal_to(20.0))

        with when("the refund fails"):
            stripe_says_the_refund_is(context, "failed")
            deliver(context, "refund.failed", refund(status_now="failed"))

        with then("the credit comes back"):
            assert_that(stored(context).llm_budget_usd, equal_to(30.0))


def test_a_lost_dispute_takes_the_credit_back_and_a_reinstated_one_returns_it():
    with given(_setup(an_owner_on_credit())) as context:
        deliver(context, "checkout.session.completed", paid_session(context))
        dispute = {"id": "dp_1", "object": "dispute", "amount": 2000, "payment_intent": "pi_1"}

        deliver(context, "charge.dispute.funds_withdrawn", dispute)
        assert_that(ledger(context)[-1], equal_to((CreditGrantKind.CHARGEBACK, Decimal(-20))))

        deliver(context, "charge.dispute.funds_reinstated", dispute)
        assert_that(stored(context).llm_budget_usd, equal_to(30.0))


def test_a_badly_signed_event_is_refused_and_grants_nothing():
    with given(_setup(an_owner_on_credit())) as context:
        response = deliver(context, "checkout.session.completed", paid_session(context), secret="whsec_wrong")

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(stored(context).llm_budget_usd, equal_to(10.0))


def test_events_that_are_not_ours_are_acknowledged_and_ignored():
    with given(_setup(an_owner_on_credit())) as context:
        other = deliver(context, "customer.created", {"id": "cus_1", "object": "customer"})
        unknown_refund = deliver(
            context,
            "refund.created",
            {"id": "re_9", "object": "refund", "amount": 100, "payment_intent": "pi_unknown", "status": "succeeded"},
        )

        assert_that([other.status_code, unknown_refund.status_code], equal_to([200, 200]))
        assert_that(stored(context).llm_budget_usd, equal_to(10.0))


def test_the_webhook_is_not_there_without_a_webhook_secret():
    with given(_setup(an_owner_on_credit(), payments="false", webhook_secret="")) as context:
        response = deliver(context, "checkout.session.completed", paid_session(context))

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(stored(context).llm_budget_usd, equal_to(10.0))


def test_payments_made_and_refunds_still_land_after_payments_are_turned_off():
    with given(_setup(an_owner_on_credit(), payments="false")) as context:
        with when("a payment made before the switch arrives, and is then refunded"):
            paid = deliver(context, "checkout.session.completed", paid_session(context))
            refunded = deliver(context, "refund.created", refund(cents=2000))

        with then("both land"):
            assert_that([paid.status_code, refunded.status_code], equal_to([200, 200]))
            assert_that(
                ledger(context)[1:],
                equal_to([(CreditGrantKind.PURCHASE, Decimal(20)), (CreditGrantKind.REFUND, Decimal(-20))]),
            )


# --- Stripe's events out of order ------------------------------------------------------------


def test_a_refund_before_its_purchase_is_retried_not_dropped():
    with given(_setup(an_owner_on_credit())) as context:
        stripe_says_the_payment_is_a_credit_purchase(context)

        with when("the refund arrives before the payment it refunds"):
            early = deliver(context, "refund.created", refund(cents=2000), event_id="evt_refund")

        with then("Stripe is asked to send it again, and nothing changes yet"):
            assert_that(early.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(stored(context).llm_budget_usd, equal_to(10.0))

        with when("the payment lands and Stripe resends the refund"):
            deliver(context, "checkout.session.completed", paid_session(context))
            deliver(context, "refund.created", refund(cents=2000), event_id="evt_refund")

        with then("the refund takes the credit back"):
            assert_that(stored(context).llm_budget_usd, equal_to(10.0))
            assert_that(ledger(context)[-1], equal_to((CreditGrantKind.REFUND, Decimal(-20))))


def test_a_refund_whose_failure_arrived_first_takes_nothing():
    with given(_setup(an_owner_on_credit())) as context:
        deliver(context, "checkout.session.completed", paid_session(context))
        stripe_says_the_refund_is(context, "failed")

        deliver(context, "refund.failed", refund(status_now="failed"))
        deliver(context, "refund.created", refund(status_now="pending"))

        assert_that(stored(context).llm_budget_usd, equal_to(30.0))


def test_a_cancelled_refund_returns_its_credit():
    with given(_setup(an_owner_on_credit())) as context:
        deliver(context, "checkout.session.completed", paid_session(context, amount_cents=2000))
        deliver(context, "refund.created", refund(cents=1000, status_now="pending"))
        assert_that(stored(context).llm_budget_usd, equal_to(20.0))

        stripe_says_the_refund_is(context, "canceled")
        deliver(context, "refund.updated", refund(cents=1000, status_now="canceled"))

        assert_that(stored(context).llm_budget_usd, equal_to(30.0))


def test_partial_refunds_that_add_up_take_back_exactly_the_purchase():
    with given(_setup(an_owner_on_credit())) as context:
        deliver(context, "checkout.session.completed", paid_session(context, credit="10", amount_cents=1055))

        for refund_id, cents in (("re_1", 333), ("re_2", 333), ("re_3", 389)):
            deliver(context, "refund.created", refund(refund_id, cents=cents))

        assert_that(sum(credit for _, credit in ledger(context)[2:]), equal_to(Decimal(-10)))


def test_a_partly_reinstated_dispute_returns_only_what_was_reinstated():
    with given(_setup(an_owner_on_credit())) as context:
        deliver(context, "checkout.session.completed", paid_session(context))
        deliver(context, "charge.dispute.funds_withdrawn", dispute(context))

        deliver(context, "charge.dispute.funds_reinstated", dispute(context, reinstated_cents=500))

        assert_that(ledger(context)[-1], equal_to((CreditGrantKind.ADJUSTMENT, Decimal(5))))
        assert_that(stored(context).llm_budget_usd, equal_to(15.0))


def test_a_reinstatement_before_its_withdrawal_still_nets_out():
    with given(_setup(an_owner_on_credit())) as context:
        deliver(context, "checkout.session.completed", paid_session(context))

        deliver(context, "charge.dispute.funds_reinstated", dispute(context, reinstated_cents=2000))
        deliver(context, "charge.dispute.funds_withdrawn", dispute(context))

        assert_that(stored(context).llm_budget_usd, equal_to(30.0))


def test_one_payment_delivered_twice_at_once_is_granted_once():
    with given(_setup(an_owner_on_credit())) as context:
        payload, signature = signed("checkout.session.completed", paid_session(context), event_id="evt_1")
        service = context.injector.get(BillingService)

        async def both():
            await asyncio.gather(*(service.handle_webhook(payload.encode(), signature) for _ in range(2)))

        asyncio.run(both())

        assert_that(stored(context).llm_budget_usd, equal_to(30.0))
        assert_that([kind for kind, _ in ledger(context)].count(CreditGrantKind.PURCHASE), equal_to(1))


def test_a_payment_for_an_organization_no_longer_on_credit_is_flagged_for_a_refund():
    with given(_setup(an_owner_on_credit())) as context:
        organizations = context.injector.get(OrganizationRepository)
        organization = organizations.get(context.organization.id)
        organization.llm_budget_duration = "30d"
        organizations.save(organization)

        response = deliver(context, "checkout.session.completed", paid_session(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        events = events_named(context, "platform.credit_purchase.unapplied")
        assert_that(events, has_length(1))
        assert_that(
            events[0].payload,
            has_entries(subject_display="Jane's Organization", payment_reference="pi_1", amount_paid_usd=20.0),
        )

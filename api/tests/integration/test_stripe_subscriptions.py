"""Tier subscriptions paid through Stripe (Tiers, slice 6).

Stripe's side is an in-memory fake of `StripeSubscriptions`; webhook signatures are real.
An event only names a subscription: Agent Barn reads the subscription as Stripe has it now
and brings its own copy in line, so delivering an event twice changes nothing.
"""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import status
from hamcrest import assert_that, contains_exactly, equal_to, has_entries, has_length, is_, none, not_none
from injector import Module, provider, singleton
from sqlmodel import Session

from api.domains.organizations.models import CreditGrantKind
from api.domains.rbac.catalog import OrganizationRole
from api.domains.subscriptions.models import OrganizationSubscription
from api.domains.subscriptions.service import SubscriptionService
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.stripe.subscriptions import (
    PaymentDeclined,
    StripePrice,
    StripeSubscriptions,
    StripeSubscriptionState,
)
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.integration.test_billing import WEBHOOK_SECRET, deliver, payments_are_on
from api.tests.integration.test_subscriptions import (
    TIER_IDS,
    auth,
    ledger,
    organization,
    someone_signed_up_on_free,
    subscribe,
    tiers_are_offered,
    url,
)
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.events import event_delivery_tables_are_clean
from api.tests.steps.google_sign_in import WEB_APP_URL, FakeGoogleIdentityModule
from api.tests.steps.onboarding import trial_settings_are_configured
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

PRICES = {
    "cloud_1": StripePrice(
        id="price_cloud_1", lookup_key="cloud_1", unit_amount=2000, currency="usd", interval="month"
    ),
    "cloud_2": StripePrice(
        id="price_cloud_2", lookup_key="cloud_2", unit_amount=10000, currency="usd", interval="month"
    ),
}
START = datetime(2026, 11, 1, tzinfo=UTC)
END = datetime(2026, 12, 1, tzinfo=UTC)
NEXT_END = datetime(2027, 1, 1, tzinfo=UTC)


class FakeStripe:
    """Stripe as it stands: subscriptions by id, and what Agent Barn asked of it."""

    def __init__(self) -> None:
        self.prices = dict(PRICES)
        self.subscriptions: dict[str, StripeSubscriptionState] = {}
        self.checkouts: list[dict] = []
        self.price_changes: list[str] = []
        self.scheduled: dict[str, str] = {}
        self.released: list[str] = []
        self.cancel_flags: list[bool] = []
        self.cancelled_now: list[str] = []
        self.decline = False

    def price_for(self, lookup_key: str) -> StripePrice | None:
        return self.prices.get(lookup_key)

    def customer(self, existing, *, organization_id, name, email) -> str:
        return existing or "cus_test"

    def checkout(self, **request) -> str:
        self.checkouts.append(request)
        return "https://checkout.stripe.test/c"

    def subscription(self, subscription_id: str) -> StripeSubscriptionState:
        return self.subscriptions[subscription_id]

    def change_price_now(self, state: StripeSubscriptionState, price_id: str) -> StripeSubscriptionState:
        if self.decline:
            raise PaymentDeclined("Your card was declined.")
        self.price_changes.append(price_id)
        price = next(p for p in self.prices.values() if p.id == price_id)
        self.subscriptions[state.id] = replace(state, price=price)
        return self.subscriptions[state.id]

    def schedule_price_change(self, state: StripeSubscriptionState, price_id: str) -> str:
        schedule_id = f"sub_sched_{state.id}"
        self.scheduled[schedule_id] = price_id
        self.subscriptions[state.id] = replace(state, schedule_id=schedule_id)
        return schedule_id

    def release_schedule(self, schedule_id: str) -> None:
        self.released.append(schedule_id)
        for key, state in self.subscriptions.items():
            if state.schedule_id == schedule_id:
                self.subscriptions[key] = replace(state, schedule_id=None)

    def set_cancel_at_period_end(self, subscription_id: str, cancel: bool) -> None:
        self.cancel_flags.append(cancel)
        self.subscriptions[subscription_id] = replace(self.subscriptions[subscription_id], cancel_at_period_end=cancel)

    def cancel_now(self, subscription_id: str) -> None:
        self.cancelled_now.append(subscription_id)
        self.subscriptions[subscription_id] = replace(self.subscriptions[subscription_id], status="canceled")

    def portal_url(self, customer_id: str, return_url: str) -> str:
        return f"https://billing.stripe.test/{customer_id}?return={return_url}"


class FakeStripeModule(Module):
    @provider
    @singleton
    def provide_stripe_subscriptions(self) -> StripeSubscriptions:
        return FakeStripe()  # ty: ignore[invalid-return-type]


def _setup(*steps):
    return [
        set_env_variable(
            {
                "WEB_APP_URL": WEB_APP_URL,
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
                "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
                "AGENTBARN_TELEGRAM_BOT_TOKEN": "424242:the-shared-bot-token",
                "AGENTBARN_TELEGRAM_BOT_USERNAME": "AgentBarnTestBot",
                "STRIPE_SECRET_KEY": "sk_test_x",
                "STRIPE_WEBHOOK_SECRET": WEBHOOK_SECRET,
                "TIERS_MOCK_PAYMENTS": "false",
            }
        ),
        prepare_injector(
            modules=[FakeGoogleIdentityModule(), MockK8sModule(), MockLiteLLMModule(), FakeStripeModule()]
        ),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        event_delivery_tables_are_clean(),
        payments_are_on(),
        trial_settings_are_configured(credit=10),
        tiers_are_offered("cloud_1", "cloud_2"),
        someone_signed_up_on_free,
        *steps,
    ]


def stripe(context) -> FakeStripe:
    return context.injector.get(StripeSubscriptions)


def stripe_has(context, *, tier="cloud_1", status_now="active", start=START, end=END, **changes) -> None:
    """Stripe's subscription `sub_1` for the Organization, as Stripe has it now."""
    current = stripe(context).subscriptions.get("sub_1")
    base = current or StripeSubscriptionState(
        id="sub_1",
        customer_id="cus_test",
        status=status_now,
        organization_id=context.organization.id,
        item_id="si_1",
        price=PRICES[tier],
        period_start=start,
        period_end=end,
        cancel_at_period_end=False,
        schedule_id=None,
    )
    stripe(context).subscriptions["sub_1"] = replace(
        base, status=status_now, price=PRICES[tier], period_start=start, period_end=end, **changes
    )


def checkout_completed(context):
    return deliver(
        context,
        "checkout.session.completed",
        {"id": "cs_1", "object": "checkout.session", "mode": "subscription", "subscription": "sub_1"},
    )


def subscription_event(context, event_type: str = "customer.subscription.updated"):
    return deliver(context, event_type, {"id": "sub_1", "object": "subscription"})


def invoice_event(context, event_type: str = "invoice.paid"):
    return deliver(
        context,
        event_type,
        {"id": "in_1", "object": "invoice", "parent": {"subscription_details": {"subscription": "sub_1"}}},
    )


def subscribed_through_stripe(tier: str = "cloud_1"):
    def step(context):
        response = subscribe(context, tier)
        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        stripe_has(context, tier=tier)
        assert_that(checkout_completed(context).status_code, equal_to(status.HTTP_200_OK))

    return step


def stored(context) -> OrganizationSubscription:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return session.exec(
            OrganizationSubscription.__table__.select().where(  # ty: ignore[unresolved-attribute]
                OrganizationSubscription.organization_id == context.organization.id
            )
        ).one()


def allowances(context) -> list[Decimal]:
    return [
        amount
        for kind, amount in ledger(context)
        if kind in (CreditGrantKind.ALLOWANCE, CreditGrantKind.ALLOWANCE_EXPIRY)
    ]


# --- subscribing -------------------------------------------------------------------------


def test_subscribing_sends_the_owner_to_stripe_and_waits_for_the_payment():
    with given(_setup()) as context:
        with when("the owner subscribes to Cloud Tier 1"):
            response = subscribe(context, "cloud_1")

        with then("they go to Stripe's Checkout with the tier's price, and nothing changes yet"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(response.json(), has_entries(outcome="redirect", redirect_url="https://checkout.stripe.test/c"))
            (checkout,) = stripe(context).checkouts
            assert_that(
                checkout,
                has_entries(
                    price_id="price_cloud_1",
                    organization_id=context.organization.id,
                    tier_key="cloud_1",
                    success_url=f"{WEB_APP_URL}/dashboard/{context.organization.id}/billing?subscription=started",
                ),
            )
            assert_that(organization(context).tier_id, equal_to(TIER_IDS["free"]))


def test_subscribing_from_onboarding_comes_back_to_onboarding():
    with given(_setup()) as context:
        response = context.client.post(
            url(context), json={"tier_key": "cloud_1", "return_to": "onboarding"}, headers=auth(context.owner_token)
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        (checkout,) = stripe(context).checkouts
        assert_that(checkout, has_entries(success_url=f"{WEB_APP_URL}/onboarding?subscription=started"))


def test_a_stripe_price_that_doesnt_match_the_tier_is_refused():
    with given(_setup()) as context:
        stripe(context).prices["cloud_1"] = replace(PRICES["cloud_1"], unit_amount=2500)

        response = subscribe(context, "cloud_1")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT), response.text)
        assert_that(stripe(context).checkouts, has_length(0))


def test_the_paid_checkout_starts_the_subscription_once_however_many_events_report_it():
    with given(_setup(subscribed_through_stripe("cloud_1"))) as context:
        with when("Stripe reports the same subscription again, by other events"):
            subscription_event(context, "customer.subscription.created")
            invoice_event(context)
            checkout_completed(context)

        with then("the Organization is on Cloud Tier 1 with Stripe's period and one month's usage"):
            assert_that(organization(context).tier_id, equal_to(TIER_IDS["cloud_1"]))
            subscription = stored(context)
            assert_that(
                (subscription.provider, subscription.provider_subscription_id, subscription.current_period_end),
                equal_to(("stripe", "sub_1", END)),
            )
            assert_that(
                ledger(context),
                contains_exactly((CreditGrantKind.TRIAL, Decimal(10)), (CreditGrantKind.ALLOWANCE, Decimal(20))),
            )
            read = context.client.get(url(context), headers=auth(context.owner_token)).json()
            assert_that(read, has_entries(provider="stripe", manageable=True))


def test_an_unpaid_checkout_starts_nothing():
    with given(_setup()) as context:
        subscribe(context, "cloud_1")
        stripe_has(context, status_now="incomplete")

        checkout_completed(context)

        assert_that(organization(context).tier_id, equal_to(TIER_IDS["free"]))


def test_events_for_subscriptions_that_arent_agent_barns_are_ignored():
    with given(_setup()) as context:
        stripe_has(context, organization_id=None)

        response = subscription_event(context, "customer.subscription.created")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(organization(context).tier_id, equal_to(TIER_IDS["free"]))


# --- renewing ------------------------------------------------------------------------------


def test_a_paid_renewal_expires_last_months_usage_and_grants_the_new_month():
    with given(_setup(subscribed_through_stripe("cloud_1"))) as context:
        stripe_has(context, start=END, end=NEXT_END)

        invoice_event(context)
        invoice_event(context)

        assert_that(stored(context).current_period_end, equal_to(NEXT_END))
        assert_that(allowances(context), equal_to([Decimal(20), Decimal(-20), Decimal(20)]))


def test_the_sweep_leaves_stripe_periods_to_stripe():
    with given(_setup(subscribed_through_stripe("cloud_1"))) as context:
        context.injector.get(SubscriptionService).sweep(now=END + timedelta(days=1))

        assert_that(stored(context).status, equal_to("active"))
        assert_that(organization(context).tier_id, equal_to(TIER_IDS["cloud_1"]))


# --- changing tier ---------------------------------------------------------------------------


def test_an_upgrade_is_charged_now_and_applies_at_once():
    with given(_setup(subscribed_through_stripe("cloud_1"))) as context:
        response = subscribe(context, "cloud_2")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(stripe(context).price_changes, equal_to(["price_cloud_2"]))
        assert_that(organization(context).tier_id, equal_to(TIER_IDS["cloud_2"]))
        assert_that(allowances(context), equal_to([Decimal(20), Decimal(80)]))


def test_a_declined_upgrade_changes_nothing():
    with given(_setup(subscribed_through_stripe("cloud_1"))) as context:
        stripe(context).decline = True

        response = subscribe(context, "cloud_2")

        assert_that(response.status_code, equal_to(status.HTTP_402_PAYMENT_REQUIRED), response.text)
        assert_that(response.json()["detail"], equal_to("Your card was declined."))
        assert_that(organization(context).tier_id, equal_to(TIER_IDS["cloud_1"]))


def test_a_downgrade_waits_for_the_renewal_then_applies():
    with given(_setup(subscribed_through_stripe("cloud_2"))) as context:
        with when("the owner moves to Cloud Tier 1"):
            response = subscribe(context, "cloud_1")

        with then("Stripe schedules it, and Cloud Tier 2 stays until the period ends"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(
                response.json()["subscription"],
                has_entries(tier=has_entries(key="cloud_2"), scheduled_tier=has_entries(key="cloud_1")),
            )
            assert_that(stripe(context).scheduled, equal_to({"sub_sched_sub_1": "price_cloud_1"}))
            assert_that(organization(context).tier_id, equal_to(TIER_IDS["cloud_2"]))

        with when("Stripe renews on the smaller price"):
            stripe_has(context, tier="cloud_1", start=END, end=NEXT_END)
            invoice_event(context)

        with then("the Organization is on Cloud Tier 1 with its usage"):
            assert_that(organization(context).tier_id, equal_to(TIER_IDS["cloud_1"]))
            assert_that(stored(context).scheduled_tier_id, is_(none()))
            assert_that(allowances(context), equal_to([Decimal(100), Decimal(-100), Decimal(20)]))


def test_keeping_the_current_tier_drops_a_scheduled_downgrade():
    with given(_setup(subscribed_through_stripe("cloud_2"))) as context:
        subscribe(context, "cloud_1")

        response = subscribe(context, "cloud_2")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(response.json()["subscription"], has_entries(scheduled_tier=None))
        assert_that(stripe(context).released, equal_to(["sub_sched_sub_1"]))


# --- failed payments ---------------------------------------------------------------------------


def test_a_failed_renewal_keeps_the_tier_without_new_usage_until_it_is_paid():
    with given(_setup(subscribed_through_stripe("cloud_1"))) as context:
        with when("the renewal payment fails"):
            stripe_has(context, status_now="past_due", start=END, end=NEXT_END)
            invoice_event(context, "invoice.payment_failed")

        with then("the subscription is past due, keeps its tier, and gets no new usage"):
            subscription = stored(context)
            assert_that(subscription.status, equal_to("past_due"))
            assert_that(subscription.past_due_since, is_(not_none()))
            assert_that(organization(context).tier_id, equal_to(TIER_IDS["cloud_1"]))
            assert_that(allowances(context), equal_to([Decimal(20), Decimal(-20)]))
            read = context.client.get(url(context), headers=auth(context.owner_token)).json()
            assert_that(read, has_entries(status="past_due", grace_ends_at=not_none()))

        with when("the card is updated and Stripe's retry pays it"):
            stripe_has(context, status_now="active", start=END, end=NEXT_END)
            invoice_event(context)

        with then("it is active again with this month's usage"):
            assert_that(stored(context).status, equal_to("active"))
            assert_that(allowances(context), equal_to([Decimal(20), Decimal(-20), Decimal(20)]))


def test_past_the_grace_period_the_subscription_ends_on_free():
    with given(_setup(subscribed_through_stripe("cloud_1"))) as context:
        stripe_has(context, status_now="past_due", start=END, end=NEXT_END)
        invoice_event(context, "invoice.payment_failed")
        subscription = stored(context)
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            row = session.get_one(OrganizationSubscription, subscription.id)
            row.past_due_since = datetime.now(UTC) - timedelta(days=8)
            session.add(row)
            session.commit()

        context.injector.get(SubscriptionService).sweep()

        assert_that(stripe(context).cancelled_now, equal_to(["sub_1"]))
        assert_that(stored(context).status, equal_to("canceled"))
        assert_that(organization(context).tier_id, equal_to(TIER_IDS["free"]))


# --- cancelling ---------------------------------------------------------------------------------


def test_cancelling_in_the_portal_shows_here_and_the_end_drops_to_free_with_the_credit():
    with given(_setup(subscribed_through_stripe("cloud_1"))) as context:
        stripe_has(context, cancel_at_period_end=True)
        subscription_event(context)
        assert_that(stored(context).cancel_at_period_end, is_(True))

        stripe_has(context, status_now="canceled")
        subscription_event(context, "customer.subscription.deleted")

        assert_that(stored(context).status, equal_to("canceled"))
        assert_that(organization(context).tier_id, equal_to(TIER_IDS["free"]))
        assert_that(
            [kind for kind, _ in ledger(context)],
            equal_to([CreditGrantKind.TRIAL, CreditGrantKind.ALLOWANCE, CreditGrantKind.ALLOWANCE_EXPIRY]),
        )


def test_cancelling_here_cancels_at_stripe_and_drops_a_scheduled_downgrade():
    with given(_setup(subscribed_through_stripe("cloud_2"))) as context:
        subscribe(context, "cloud_1")

        response = context.client.post(url(context, "/cancel"), headers=auth(context.owner_token))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(response.json(), has_entries(cancel_at_period_end=True, scheduled_tier=None))
        assert_that(stripe(context).released, equal_to(["sub_sched_sub_1"]))
        assert_that(stripe(context).cancel_flags, equal_to([True]))


# --- the portal and the platform -------------------------------------------------------------


def test_the_owner_opens_stripes_billing_page_and_a_member_cannot():
    with given(_setup(subscribed_through_stripe("cloud_1"))) as context:
        response = context.client.post(url(context, "/portal"), headers=auth(context.owner_token))
        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(
            response.json()["url"],
            equal_to(
                f"https://billing.stripe.test/cus_test?return={WEB_APP_URL}/dashboard/{context.organization.id}/billing"
            ),
        )

        there_is_a_user(email="member@example.com", role=OrganizationRole.MEMBER)(context)
        there_is_an_access_token_for_user()(context)
        member = context.client.post(url(context, "/portal"), headers=auth(context.access_token))
        assert_that(member.status_code, equal_to(status.HTTP_403_FORBIDDEN), member.text)


def test_ending_a_stripe_period_early_is_refused():
    with given(_setup(subscribed_through_stripe("cloud_1"))) as context:
        there_is_a_user(email="platform@example.com", is_platform_admin=True, role=OrganizationRole.MEMBER)(context)
        there_is_an_access_token_for_user()(context)

        response = context.client.post(
            f"/api/v1/platform/organizations/{context.organization.id}/subscription/end-period",
            headers=auth(context.access_token),
        )

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT), response.text)
        assert_that(stored(context).status, equal_to("active"))

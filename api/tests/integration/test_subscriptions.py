"""Subscriptions and a paid Tier's credit (Tiers, PR 5).

The mock provider takes the payment where the deployment turns it on. Activating puts the
Organization on the paid Tier, ends its trial, grants the Tier's one-time credit once per
Organization, and the period's allowance. A period's end expires what is left of its
allowance, spend counted against it first, then renews, or ends the subscription and drops
the Organization to Free with its credit kept and what Free doesn't cover held.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import status
from hamcrest import assert_that, contains_exactly, equal_to, has_entries, has_item, has_length, is_, not_none
from sqlalchemy import text
from sqlmodel import Session, col, select

from api.domains.organizations.models import CreditGrantKind, Organization, OrganizationCreditGrant
from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import OrganizationRole
from api.domains.subscriptions.models import OrganizationSubscription
from api.domains.subscriptions.repository import SubscriptionRepository
from api.domains.subscriptions.service import SubscriptionService
from api.domains.tiers.models import SEED_TIERS
from api.domains.tiers.repository import Actor, TierRepository
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.repository import UserRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.integration.test_agent_webhooks import _ensure_native_connection
from api.tests.integration.test_spend_limits import events_named
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, there_is_an_agent
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.events import event_delivery_tables_are_clean
from api.tests.steps.google_sign_in import GOOGLE_EMAIL, WEB_APP_URL, FakeGoogleIdentityModule, finish_google_sign_in
from api.tests.steps.onboarding import trial_settings_are_configured
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

TIER_IDS = {str(seed["key"]): UUID(str(seed["id"])) for seed in SEED_TIERS}


def _setup(*steps, mock_payments: bool = True):
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
                "TIERS_MOCK_PAYMENTS": "true" if mock_payments else "false",
            }
        ),
        prepare_injector(modules=[FakeGoogleIdentityModule(), MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        event_delivery_tables_are_clean(),
        trial_settings_are_configured(credit=10),
        tiers_are_offered("cloud_1", "cloud_2"),
        someone_signed_up_on_free,
        *steps,
    ]


def tiers_are_offered(*keys: str):
    def step(context):
        for key in keys:
            context.injector.get(TierRepository).update_with_events(
                TIER_IDS[key], {"enabled": True}, actor=Actor(user_id=TIER_IDS[key], display="Setup")
            )

    return step


def someone_signed_up_on_free(context):
    finish_google_sign_in(context)
    context.access_token = context.client.post("/api/v1/auth/refresh").json()["access_token"]
    context.owner_token = context.access_token
    user = context.injector.get(UserRepository).get_by_email(GOOGLE_EMAIL)
    (membership,) = context.injector.get(OrganizationUserRepository).get_by_user_id(user.id)
    context.organization = context.injector.get(OrganizationRepository).get(membership.organization_id)
    context.user = user


def spend_is(amount: float):
    def step(context):
        organizations = context.injector.get(OrganizationRepository)
        organization = organizations.get(context.organization.id)
        organization.llm_spend_usd = amount
        organization.llm_spend_observed_at = datetime.now(UTC)
        organizations.save(organization)

    return step


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def url(context, path: str = "") -> str:
    return f"/api/v1/organizations/{context.organization.id}/subscription{path}"


def subscribe(context, tier_key: str, token: str | None = None):
    return context.client.post(url(context), json={"tier_key": tier_key}, headers=auth(token or context.owner_token))


def organization(context) -> Organization:
    return context.injector.get(OrganizationRepository).get(context.organization.id)


def ledger(context) -> list[tuple[CreditGrantKind, Decimal]]:
    with Session(context.postgres_delegate.engine) as session:
        grants = session.exec(
            select(OrganizationCreditGrant)
            .where(OrganizationCreditGrant.organization_id == context.organization.id)
            .order_by(col(OrganizationCreditGrant.created_at))
        ).all()
        return [(grant.kind, grant.credit_usd.normalize()) for grant in grants]


def end_period_now(context):
    a_platform_administrator_is_signed_in(context)
    return context.client.post(
        f"/api/v1/platform/organizations/{context.organization.id}/subscription/end-period",
        headers=auth(context.access_token),
    )


def a_platform_administrator_is_signed_in(context):
    there_is_a_user(email="platform@example.com", is_platform_admin=True, role=OrganizationRole.MEMBER)(context)
    there_is_an_access_token_for_user()(context)


# --- subscribing ----------------------------------------------------------------------


def test_an_owner_on_free_subscribes_to_a_paid_tier():
    with given(_setup()) as context:
        with when("the owner subscribes to Cloud Tier 1"):
            response = subscribe(context, "cloud_1")

        with then("the Organization is on it, its trial is over, and the month's usage is granted"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(
                response.json(),
                has_entries(
                    outcome="active",
                    subscription=has_entries(
                        tier=has_entries(key="cloud_1"),
                        status="active",
                        provider="mock",
                        cancel_at_period_end=False,
                        allowance_usd=20.0,
                        allowance_remaining_usd=20.0,
                    ),
                ),
            )
            stored = organization(context)
            assert_that(
                (stored.tier_id, stored.tier_assigned_by_platform, stored.is_trial, stored.llm_budget_usd),
                equal_to((TIER_IDS["cloud_1"], False, False, 30.0)),
            )
            # Free's trial credit was its one-time credit; Cloud Tier 1 grants no second one.
            assert_that(
                ledger(context),
                contains_exactly((CreditGrantKind.TRIAL, Decimal(10)), (CreditGrantKind.ALLOWANCE, Decimal(20))),
            )
            assert_that(events_named(context, "organization.subscription.started"), has_length(1))
            (changed,) = events_named(context, "organization.tier.changed")
            assert_that(
                changed.payload, has_entries(tier_key="cloud_1", previous_tier_key="free", assigned_by_platform=False)
            )


def test_the_paid_tier_unlocks_what_free_left_out():
    with given(_setup()) as context:
        subscribe(context, "cloud_1")

        read = context.client.get(f"/api/v1/organizations/{context.organization.id}", headers=auth(context.owner_token))

        assert_that(read.json()["entitlements"]["features"], has_item("custom_agents"))


def test_an_organization_that_never_had_free_gets_the_tiers_one_time_credit():
    def it_never_had_a_trial(context):
        with Session(context.postgres_delegate.engine) as session:
            for grant in session.exec(
                select(OrganizationCreditGrant).where(
                    OrganizationCreditGrant.organization_id == context.organization.id
                )
            ).all():
                grant.kind = CreditGrantKind.ADJUSTMENT
                session.add(grant)
            session.commit()

    with given(_setup(it_never_had_a_trial)) as context:
        subscribe(context, "cloud_1")

        assert_that(ledger(context), has_item((CreditGrantKind.TIER_CREDIT, Decimal(10))))


def test_a_subscribers_next_organization_starts_on_no_tier_and_subscribes_on_its_own():
    with given(_setup()) as context:
        subscribe(context, "cloud_1")

        with when("the owner creates another Organization"):
            response = context.client.post(
                "/api/v1/organizations", json={"name": "Second Org"}, headers=auth(context.owner_token)
            )

        with then("it runs nothing until it has a Tier of its own"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)
            created = context.injector.get(OrganizationRepository).get(UUID(response.json()["id"]))
            assert created is not None
            assert_that(
                (created.tier_id, created.is_trial, created.llm_budget_usd),
                equal_to((TIER_IDS["none"], False, 0.0)),
            )
            read = context.client.get(f"/api/v1/organizations/{created.id}", headers=auth(context.owner_token))
            assert_that(
                read.json(),
                has_entries(tier=has_entries(key="none"), agent_limit=0, entitlements=has_entries(features=[])),
            )

        with when("the owner subscribes it to Cloud Tier 2"):
            context.organization = created
            subscribed = subscribe(context, "cloud_2")

        with then("it is on that Tier with the Tier's one-time credit, beside the first"):
            assert_that(subscribed.status_code, equal_to(status.HTTP_200_OK), subscribed.text)
            assert_that(organization(context).tier_id, equal_to(TIER_IDS["cloud_2"]))
            assert_that(
                ledger(context),
                contains_exactly(
                    (CreditGrantKind.ADJUSTMENT, Decimal(0)),
                    (CreditGrantKind.TIER_CREDIT, Decimal(10)),
                    (CreditGrantKind.ALLOWANCE, Decimal(100)),
                ),
            )
            assert_that(events_named(context, "organization.subscription.started"), has_length(2))


def test_without_a_paid_tier_to_buy_the_next_organization_has_no_tier():
    with given(_setup(mock_payments=False)) as context:
        a_platform_administrator_is_signed_in(context)
        ended = context.client.post(
            f"/api/v1/platform/organizations/{context.organization.id}/end-trial",
            json={"budget_usd": 50, "budget_duration": "30d"},
            headers=auth(context.access_token),
        )
        assert_that(ended.status_code, equal_to(status.HTTP_200_OK), ended.text)

        response = context.client.post(
            "/api/v1/organizations", json={"name": "Second Org"}, headers=auth(context.owner_token)
        )

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)
        created = context.injector.get(OrganizationRepository).get(UUID(response.json()["id"]))
        assert created is not None
        assert_that(created.tier_id, is_(None))


def test_subscribing_needs_the_mock_provider_turned_on():
    with given(_setup(mock_payments=False)) as context:
        response = subscribe(context, "cloud_1")

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(organization(context).tier_id, equal_to(TIER_IDS["free"]))


def test_a_tier_that_is_not_offered_or_not_paid_is_refused():
    with given(_setup()) as context:
        assert_that(subscribe(context, "pilot").status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(subscribe(context, "free").status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_only_the_owner_subscribes():
    def an_admin_is_signed_in(context):
        there_is_a_user(email="admin@example.com", role=OrganizationRole.ADMIN)(context)
        there_is_an_access_token_for_user()(context)

    with given(_setup(an_admin_is_signed_in)) as context:
        response = subscribe(context, "cloud_1", token=context.access_token)

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_tier_chosen_by_the_platform_is_not_replaced_by_a_subscription():
    def the_platform_chose_its_tier(context):
        organizations = context.injector.get(OrganizationRepository)
        stored = organizations.get(context.organization.id)
        stored.tier_assigned_by_platform = True
        organizations.save(stored)

    with given(_setup(the_platform_chose_its_tier)) as context:
        assert_that(subscribe(context, "cloud_1").status_code, equal_to(status.HTTP_409_CONFLICT))


def test_moving_to_a_bigger_tier_tops_the_months_usage_up():
    with given(_setup()) as context:
        subscribe(context, "cloud_1")

        response = subscribe(context, "cloud_2")

        assert_that(response.json()["subscription"], has_entries(tier=has_entries(key="cloud_2"), allowance_usd=100.0))
        assert_that(organization(context).tier_id, equal_to(TIER_IDS["cloud_2"]))
        assert_that(ledger(context)[-1], equal_to((CreditGrantKind.ALLOWANCE, Decimal(80))))


def test_subscribing_again_to_the_same_tier_is_refused():
    with given(_setup()) as context:
        subscribe(context, "cloud_1")

        assert_that(subscribe(context, "cloud_1").status_code, equal_to(status.HTTP_409_CONFLICT))


def test_a_preview_says_what_a_cancellation_would_put_on_hold():
    def two_agents_one_on_slack(context):
        there_is_an_agent(name="First")(context)
        _ensure_native_connection(context, "slack")
        there_is_an_agent(name="Second")(context)

    with given(_setup(two_agents_one_on_slack)) as context:
        subscribe(context, "cloud_2")

        response = context.client.get(url(context, "/preview?tier_key=free"), headers=auth(context.owner_token))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(
            response.json(),
            has_entries(
                tier="Free",
                agents=contains_exactly(has_entries(name="Second")),
                connections=contains_exactly(has_entries(platform_key="slack", agent_name="First")),
                webhooks=[],
                memory=[],
            ),
        )
        # A preview changes nothing.
        assert_that(organization(context).tier_id, equal_to(TIER_IDS["cloud_2"]))


def test_a_preview_names_a_tier_the_organization_could_move_to():
    with given(_setup()) as context:
        subscribe(context, "cloud_2")

        switch = context.client.get(url(context, "/preview?tier_key=cloud_1"), headers=auth(context.owner_token))
        pilot = context.client.get(url(context, "/preview?tier_key=pilot"), headers=auth(context.owner_token))

        assert_that(switch.status_code, equal_to(status.HTTP_200_OK), switch.text)
        assert_that(pilot.status_code, equal_to(status.HTTP_404_NOT_FOUND), pilot.text)


def test_a_cancellation_waits_for_the_period_and_can_be_taken_back():
    with given(_setup()) as context:
        subscribe(context, "cloud_1")

        cancelled = context.client.post(url(context, "/cancel"), headers=auth(context.owner_token))
        resumed = context.client.post(url(context, "/resume"), headers=auth(context.owner_token))

        assert_that(cancelled.json(), has_entries(cancel_at_period_end=True, status="active"))
        assert_that(resumed.json(), has_entries(cancel_at_period_end=False))
        assert_that(organization(context).tier_id, equal_to(TIER_IDS["cloud_1"]))


# --- each period's end ------------------------------------------------------------------


def test_a_periods_end_expires_unused_usage_and_renews():
    with given(_setup()) as context:
        subscribe(context, "cloud_1")
        spend_is(5)(context)

        with when("the period ends"):
            response = end_period_now(context)

        with then("the $15 left of the $20 expires and a fresh $20 is granted"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(response.json(), has_entries(allowance_usd=20.0, allowance_remaining_usd=20.0))
            assert_that(
                ledger(context)[-2:],
                contains_exactly(
                    (CreditGrantKind.ALLOWANCE_EXPIRY, Decimal(-15)), (CreditGrantKind.ALLOWANCE, Decimal(20))
                ),
            )
            # $10 trial + $20 - $15 + $20: the trial credit and the spent $5 are never taken.
            assert_that(organization(context).llm_budget_usd, equal_to(35.0))
            assert_that(events_named(context, "organization.subscription.renewed"), is_(not_none()))


def test_spend_beyond_the_allowance_expires_nothing():
    with given(_setup()) as context:
        subscribe(context, "cloud_1")
        spend_is(25)(context)

        end_period_now(context)

        assert_that(
            [kind for kind, _ in ledger(context)].count(CreditGrantKind.ALLOWANCE_EXPIRY),
            equal_to(0),
        )


def test_a_cancelled_subscription_ends_on_free_with_its_credit_and_holds():
    with given(_setup()) as context:
        subscribe(context, "cloud_2")
        there_is_an_agent(name="Oldest")(context)
        there_is_an_agent(name="Newest")(context)
        context.client.post(url(context, "/cancel"), headers=auth(context.owner_token))

        with when("the period ends"):
            response = end_period_now(context)

        with then("the Organization is on Free, keeps what it didn't use, and its newest Agent is held"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(response.json(), is_(None))
            stored = organization(context)
            assert_that((stored.tier_id, stored.tier_assigned_by_platform), equal_to((TIER_IDS["free"], False)))
            # $10 trial + $100 - $100 expired: the trial credit stays spendable on Free.
            assert_that(stored.llm_budget_usd, equal_to(10.0))
            assert_that(events_named(context, "organization.subscription.ended"), is_(not_none()))
            held = events_named(context, "organization.tier_holds.changed")
            assert_that(held[-1].payload, has_entries(reason="tier", held_agent_ids=[str(context.agent.id)]))


def test_the_sweep_renews_a_period_that_ran_out():
    with given(_setup()) as context:
        subscribe(context, "cloud_1")
        with Session(context.postgres_delegate.engine) as session:
            subscription = session.exec(select(OrganizationSubscription)).one()
            subscription.current_period_start -= timedelta(days=31)
            subscription.current_period_end = datetime.now(UTC) - timedelta(minutes=1)
            session.add(subscription)
            session.commit()

        context.injector.get(SubscriptionService).sweep()

        with Session(context.postgres_delegate.engine) as session:
            renewed = session.exec(select(OrganizationSubscription)).one()
        assert_that(renewed.current_period_end > datetime.now(UTC), is_(True))
        assert_that(ledger(context)[-1], equal_to((CreditGrantKind.ALLOWANCE, Decimal(20))))


def test_the_sweep_applies_holds_whose_choosing_time_is_up():
    with given(_setup()) as context:
        there_is_an_agent(name="Oldest")(context)
        there_is_an_agent(name="Newest")(context)
        organizations = context.injector.get(OrganizationRepository)
        stored = organizations.get(context.organization.id)
        stored.tier_holds_due_at = datetime.now(UTC) - timedelta(minutes=1)
        organizations.save(stored)

        context.injector.get(SubscriptionService).sweep()

        assert_that(organization(context).tier_holds_due_at, is_(None))
        (held,) = events_named(context, "organization.tier_holds.changed")
        assert_that(held.payload, has_entries(held_agent_ids=[str(context.agent.id)]))


def test_billing_reads_the_subscription():
    with given(_setup()) as context:
        subscribe(context, "cloud_1")

        billing = context.client.get(
            f"/api/v1/organizations/{context.organization.id}/billing", headers=auth(context.owner_token)
        )

        assert_that(
            billing.json(),
            has_entries(
                tier=has_entries(key="cloud_1"),
                upgrade_required=False,
                subscriptions_available=True,
                subscription=has_entries(tier=has_entries(key="cloud_1")),
            ),
        )


def test_the_public_catalog_lists_what_is_offered():
    with given(_setup()) as context:
        response = context.client.get("/api/v1/tiers")

        assert_that([tier["key"] for tier in response.json()], equal_to(["free", "cloud_1", "cloud_2"]))


# --- one change at a time --------------------------------------------------------------------


def test_an_organizations_subscription_lock_holds_others_off_and_can_be_taken_again():
    with given(_setup()) as context:
        repository = context.injector.get(SubscriptionRepository)
        key = {"key": f"subscription:{context.organization.id}"}

        def someone_else_could_take_it() -> bool:
            with context.postgres_delegate.engine.connect() as connection, connection.begin():
                return connection.execute(text("SELECT pg_try_advisory_xact_lock(hashtext(:key))"), key).scalar_one()

        with repository.organization_lock(context.organization.id):
            with repository.organization_lock(context.organization.id):
                assert_that(someone_else_could_take_it(), is_(False))
            assert_that(someone_else_could_take_it(), is_(False))

        assert_that(someone_else_could_take_it(), is_(True))

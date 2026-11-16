"""Free replaces the trial (Tiers, PR 4).

A sign-up from an inbox that never had Free lands on the Free Tier: the trial, with Free's
credit and Agent limit. One that can't have Free (the inbox had it, or the cap on active
trials is reached and it came for a paid Tier) lands on none when there is something it can
buy, and is refused as before otherwise. The Tier asked for on the pricing page rides the
sign-in to onboarding. Free and none can't buy credit; they subscribe first.
"""

from decimal import Decimal
from uuid import UUID

from fastapi import status
from hamcrest import assert_that, equal_to, has_entries
from sqlmodel import Session

from api.domains.onboarding.models import PlatformTrialSettings
from api.domains.onboarding.repository import TrialSettingsRepository
from api.domains.onboarding.settings_service import TrialSettingsService
from api.domains.organizations.models import CreditGrantKind, Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.tiers.models import SEED_TIERS
from api.domains.tiers.repository import Actor, TierRepository
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.repository import UserRepository
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.google_sign_in import (
    GOOGLE_EMAIL,
    WEB_APP_URL,
    FakeGoogleIdentityModule,
    finish_google_sign_in,
    google_identity,
    google_returns,
    redirect_target,
)
from api.tests.steps.onboarding import trial_settings_are_configured

TIER_IDS = {str(seed["key"]): UUID(str(seed["id"])) for seed in SEED_TIERS}


def _setup(*steps, mock_payments: bool = True, free_offered: bool = True):
    return [
        set_env_variable(
            {
                "WEB_APP_URL": WEB_APP_URL,
                "AGENTBARN_TELEGRAM_BOT_TOKEN": "424242:the-shared-bot-token",
                "AGENTBARN_TELEGRAM_BOT_USERNAME": "AgentBarnTestBot",
                "TIERS_MOCK_PAYMENTS": "true" if mock_payments else "false",
            }
        ),
        prepare_injector(modules=[FakeGoogleIdentityModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        trial_settings_are_configured(credit=12, agent_limit=1, free_offered=free_offered),
        tier_is_offered("cloud_1"),
        *steps,
    ]


def tier_is_offered(key: str):
    def step(context):
        context.injector.get(TierRepository).update_with_events(
            TIER_IDS[key], {"enabled": True}, actor=Actor(user_id=TIER_IDS[key], display="Setup")
        )

    return step


def the_inbox_had_free(context):
    with Session(context.postgres_delegate.engine) as session:
        context.injector.get(TrialSettingsRepository).record_grant(
            TrialSettingsService.email_hash(GOOGLE_EMAIL), session
        )
        session.commit()


def the_trials_are_full(context):
    """A cap of one, taken by someone else's trial."""
    with Session(context.postgres_delegate.engine) as session:
        settings = session.get_one(PlatformTrialSettings, 1)
        settings.max_active_trials = 1
        session.add(settings)
        session.add(Organization(name="Other trial", is_trial=True, allowed_models=[]))
        session.commit()


def the_organization(context):
    user = context.injector.get(UserRepository).get_by_email(GOOGLE_EMAIL)
    (membership,) = context.injector.get(OrganizationUserRepository).get_by_user_id(user.id)
    return context.injector.get(OrganizationRepository).get(membership.organization_id)


def test_a_new_inbox_signs_up_on_free_with_its_credit():
    with given(_setup()) as context:
        with when("someone signs up with Google"):
            response = finish_google_sign_in(context)

        with then("their trial is on Free, with Free's credit, and they go to onboarding"):
            assert_that(redirect_target(response), equal_to((f"{WEB_APP_URL}/onboarding", {})))
            organization = the_organization(context)
            assert_that(
                (organization.is_trial, organization.tier_id, organization.llm_budget_usd),
                equal_to((True, TIER_IDS["free"], 12.0)),
            )


def test_the_tier_asked_for_rides_the_sign_in_to_onboarding():
    with given(_setup()) as context:
        response = finish_google_sign_in(context, tier="cloud_1")

        assert_that(redirect_target(response), equal_to((f"{WEB_APP_URL}/onboarding", {"tier": "cloud_1"})))
        assert_that(the_organization(context).tier_id, equal_to(TIER_IDS["free"]))


def test_a_tier_that_is_not_offered_is_dropped():
    with given(_setup()) as context:
        response = finish_google_sign_in(context, tier="pilot_unknown")

        assert_that(redirect_target(response), equal_to((f"{WEB_APP_URL}/onboarding", {})))


def test_a_returning_inbox_lands_on_none_when_it_can_subscribe():
    with given(_setup(the_inbox_had_free)) as context:
        with when("the inbox that already had Free signs up again"):
            response = finish_google_sign_in(context)

        with then("it gets an Organization on none, on Credit from nothing, and may create others"):
            assert_that(redirect_target(response)[0], equal_to(f"{WEB_APP_URL}/onboarding"))
            organization = the_organization(context)
            assert_that(
                (organization.is_trial, organization.tier_id, organization.llm_budget_usd),
                equal_to((False, TIER_IDS["none"], 0.0)),
            )
            grants = context.injector.get(OrganizationRepository).list_credit_grants(organization.id)
            assert_that([(g.kind, g.credit_usd) for g in grants], equal_to([(CreditGrantKind.ADJUSTMENT, Decimal(0))]))
            user = context.injector.get(UserRepository).get_by_email(GOOGLE_EMAIL)
            assert_that(user.trial_ended_at is not None, equal_to(True))


def test_a_returning_inbox_is_refused_when_there_is_nothing_to_buy():
    with given(_setup(the_inbox_had_free, mock_payments=False)) as context:
        response = finish_google_sign_in(context)

        assert_that(redirect_target(response), equal_to((f"{WEB_APP_URL}/signup", {"error": "trial_used"})))


def test_with_trials_full_a_paid_sign_up_lands_on_none_and_a_free_one_is_refused():
    with given(_setup(the_trials_are_full)) as context:
        with when("someone comes for Free, then someone else for Cloud Tier 1"):
            free = finish_google_sign_in(context)
            google_returns(google_identity(sub="paid-sub", email="paid@example.com"))(context)
            paid = finish_google_sign_in(context, tier="cloud_1")

        with then("Free waits for a place; the paid sign-up starts on none"):
            assert_that(redirect_target(free), equal_to((f"{WEB_APP_URL}/signup", {"error": "trials_full"})))
            assert_that(redirect_target(paid), equal_to((f"{WEB_APP_URL}/onboarding", {"tier": "cloud_1"})))
            user = context.injector.get(UserRepository).get_by_email("paid@example.com")
            (membership,) = context.injector.get(OrganizationUserRepository).get_by_user_id(user.id)
            organization = context.injector.get(OrganizationRepository).get(membership.organization_id)
            assert_that(organization.tier_id, equal_to(TIER_IDS["none"]))


def test_signup_is_closed_while_free_is_not_offered():
    with given(_setup(free_offered=False, mock_payments=False)) as context:
        response = finish_google_sign_in(context)

        assert_that(redirect_target(response), equal_to((f"{WEB_APP_URL}/signup", {"error": "signup_closed"})))


def test_free_cannot_buy_credit():
    with given(_setup()) as context:
        finish_google_sign_in(context)
        organization = the_organization(context)
        token = context.client.post("/api/v1/auth/refresh").json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        with when("the owner reads billing and tries to buy credit"):
            billing = context.client.get(f"/api/v1/organizations/{organization.id}/billing", headers=headers)
            checkout = context.client.post(
                f"/api/v1/organizations/{organization.id}/billing/checkout",
                json={"credit_usd": "10"},
                headers=headers,
            )

        with then("billing says to subscribe first, and checkout refuses"):
            assert_that(
                billing.json(),
                has_entries(available=False, upgrade_required=True, subscriptions_available=True),
            )
            # Payments are off here, so checkout is refused before the Tier is considered.
            assert_that(checkout.status_code, equal_to(status.HTTP_404_NOT_FOUND))

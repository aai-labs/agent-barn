"""Signing in with Google (AF-368): a first sign-in creates the account and its trial
Organization; a returning one signs in; every failure lands back on the page it started
from with nothing created."""

import threading
from datetime import UTC, datetime

import pytest
from hamcrest import assert_that, empty, equal_to, has_entries, has_length, is_not, none, not_none

from api.domains.agent_settings.lookup import AgentSettingsLookupService
from api.domains.auth.google_sign_in import GoogleSignInService
from api.domains.auth.repository import PasswordResetTokenRepository
from api.domains.auth.service import AuthService
from api.domains.onboarding.repository import TrialSettingsRepository
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.repository import UserRepository
from api.infrastructure.google.identity import GoogleIdentityError, GoogleIdentityUnavailable
from api.infrastructure.litellm.client import ONE_OFF_BUDGET_WINDOW
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.google_sign_in import (
    GOOGLE_EMAIL,
    GOOGLE_SUB,
    WEB_APP_URL,
    FakeGoogleIdentityModule,
    fake_google,
    finish_google_sign_in,
    google_identity,
    google_returns,
    redirect_target,
    start_google_sign_in,
    state_from,
)
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import there_is_a_user

CALLBACK = f"{WEB_APP_URL}/api/v1/auth/google/callback"
ONBOARDING = f"{WEB_APP_URL}/onboarding"
DASHBOARD = f"{WEB_APP_URL}/dashboard"


def _setup(*steps, signup: str = "true"):
    return [
        set_env_variable(
            {
                "WEB_APP_URL": WEB_APP_URL,
                "SELF_SIGNUP_ENABLED": signup,
                "TRIAL_DEFAULT_CREDIT_USD": "7.5",
            }
        ),
        prepare_injector(modules=[FakeGoogleIdentityModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        *steps,
    ]


def _user(context, email: str = GOOGLE_EMAIL):
    return context.injector.get(UserRepository).get_by_email(email)


def _memberships(context, user_id):
    return context.injector.get(OrganizationUserRepository).get_by_user_id(user_id)


# --- starting --------------------------------------------------------------------


def test_starting_sends_the_browser_to_google_with_a_signed_state():
    with given(_setup()) as context:
        with when("someone starts signing in with Google"):
            response = start_google_sign_in(context)

        with then("they are sent to Google's consent screen, coming back to our callback"):
            assert_that(response.status_code, equal_to(302))
            target, query = redirect_target(response)
            assert_that(target, equal_to("https://accounts.google.com/o/oauth2/v2/auth"))
            assert_that(query, has_entries(redirect_uri=CALLBACK, scope="openid email profile"))
            assert_that(state_from(response), is_not(empty()))


def test_starting_without_a_configured_google_client_goes_back_with_an_error():
    with given(_setup()) as context:
        fake_google(context).is_configured = False

        with when("someone starts signing in with Google"):
            response = start_google_sign_in(context, origin="login")

        with then("they land back on the login page, told it is unavailable"):
            assert_that(redirect_target(response), equal_to((f"{WEB_APP_URL}/login", {"error": "unavailable"})))


# --- a first sign-in: the account and its trial ------------------------------------


def test_a_first_sign_in_creates_a_verified_account():
    with given(_setup()) as context:
        with when("someone new comes back from Google"):
            response = finish_google_sign_in(context)

        with then("they are sent on to onboarding"):
            assert_that(redirect_target(response), equal_to((ONBOARDING, {})))

        with then("their account exists, verified, linked to the Google account, and marked as self-signed-up"):
            user = _user(context)
            assert_that(user, not_none())
            assert_that(user.full_name, equal_to("Jane Doe"))
            assert_that(user.google_sub, equal_to(GOOGLE_SUB))
            assert_that(user.email_verified_at, not_none())
            assert_that(user.signed_up_at, not_none())
            assert_that(user.onboarding_completed_at, none())


def test_a_first_sign_in_creates_a_trial_organization_on_one_off_credit():
    with given(_setup()) as context:
        with when("someone new comes back from Google"):
            finish_google_sign_in(context)

        with then("they own one trial Organization whose limit is the trial credit, granted once"):
            memberships = _memberships(context, _user(context).id)
            assert_that(memberships, has_length(1))
            assert_that(memberships[0].role, equal_to(OrganizationRole.OWNER))
            organization = context.injector.get(OrganizationRepository).get(memberships[0].organization_id)
            assert_that(organization.is_trial, equal_to(True))
            assert_that(organization.created_by_user_id, equal_to(_user(context).id))
            assert_that(organization.name, equal_to("Jane's Organization"))
            assert_that(organization.llm_budget_usd, equal_to(7.5))
            assert_that(organization.llm_budget_duration, equal_to(ONE_OFF_BUDGET_WINDOW))


def test_the_trial_credit_is_the_one_platform_administrators_set():
    with given(_setup()) as context:
        _set_trial_credit(context, 12.0)

        with when("someone new comes back from Google"):
            finish_google_sign_in(context)

        with then("their trial starts with that credit"):
            organization_id = _memberships(context, _user(context).id)[0].organization_id
            organization = context.injector.get(OrganizationRepository).get(organization_id)
            assert_that(organization.llm_budget_usd, equal_to(12.0))


def test_a_trials_agents_can_spend_its_whole_credit():
    """An Agent's own limit defaults to the deployment's, which may be below the credit;
    a trial's agents default to the credit instead, so the one advertised is usable."""
    with given(_setup()) as context:
        _set_trial_credit(context, 30.0)

        with when("someone new signs up while the deployment's Agent default is lower"):
            finish_google_sign_in(context)

        with then("their trial's Agents default to the whole credit"):
            organization_id = _memberships(context, _user(context).id)[0].organization_id
            default = context.injector.get(AgentSettingsLookupService).resolve_default_agent_llm_budget(organization_id)
            assert_that(default, equal_to(30.0))


def test_signing_in_leaves_a_session_the_browser_can_refresh():
    with given(_setup()) as context:
        finish_google_sign_in(context)

        with when("the web app asks for an access token with the session cookie"):
            response = context.client.post("/api/v1/auth/refresh")

        with then("it gets one for the new account"):
            assert_that(response.status_code, equal_to(200), response.text)
            me = context.client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {response.json()['access_token']}"}
            )
            assert_that(me.json(), has_entries(email=GOOGLE_EMAIL))


def test_two_simultaneous_first_sign_ins_make_one_account():
    """Two tabs coming back from Google at once: the second insert collides with the
    first, and signs in to the account the first created."""
    with given(_setup()) as context:
        service = context.injector.get(GoogleSignInService)
        barrier = threading.Barrier(2)
        signed_in = []

        def sign_in() -> None:
            barrier.wait()
            signed_in.append(service._sign_in(google_identity()).id)

        with when("both callbacks are handled at the same moment"):
            threads = [threading.Thread(target=sign_in) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=30)

        with then("both land in the same, single account, with one trial"):
            assert_that(signed_in, has_length(2))
            assert_that(signed_in[0], equal_to(signed_in[1]))
            assert_that(_memberships(context, signed_in[0]), has_length(1))


# --- returning users ------------------------------------------------------------------


def test_a_returning_google_user_signs_in_without_a_second_trial():
    with given(_setup()) as context:
        finish_google_sign_in(context)

        with when("they sign in with Google again"):
            response = finish_google_sign_in(context)

        with then("they are signed in to the same account, still with one Organization, back to onboarding"):
            assert_that(redirect_target(response), equal_to((ONBOARDING, {})))
            assert_that(_memberships(context, _user(context).id), has_length(1))


def test_a_returning_user_who_finished_onboarding_goes_straight_to_the_dashboard():
    with given(_setup()) as context:
        finish_google_sign_in(context)
        users = context.injector.get(UserRepository)
        user = users.get_by_email(GOOGLE_EMAIL)
        user.onboarding_completed_at = datetime.now(UTC)
        users.save(user)

        with when("they sign in with Google again"):
            response = finish_google_sign_in(context)

        with then("they land on the dashboard"):
            assert_that(redirect_target(response), equal_to((DASHBOARD, {})))


def test_a_google_account_whose_address_changed_still_finds_its_user():
    with given(_setup()) as context:
        finish_google_sign_in(context)
        user_id = _user(context).id
        google_returns(google_identity(email="jane.doe@new-example.com"))(context)

        with when("they sign in after changing their Google address"):
            finish_google_sign_in(context)

        with then("the account is found by its Google id, and no other is created"):
            assert_that(_user(context, "jane.doe@new-example.com"), none())
            assert_that(context.injector.get(UserRepository).get(user_id).google_sub, equal_to(GOOGLE_SUB))


def test_an_existing_password_account_is_linked_rather_than_duplicated():
    with given(
        _setup(
            there_is_an_organization(name="Acme"),
            there_is_a_user(email="Jane@Example.com", role=OrganizationRole.MEMBER),
        )
    ) as context:
        existing = context.user

        with when("its owner signs in with the Google account for the same address"):
            response = finish_google_sign_in(context)

        with then("they are signed in to their account, which is now linked, with no trial added"):
            assert_that(redirect_target(response), equal_to((DASHBOARD, {})))
            user = context.injector.get(UserRepository).get(existing.id)
            assert_that(user.google_sub, equal_to(GOOGLE_SUB))
            assert_that(user.signed_up_at, none())
            assert_that(_memberships(context, existing.id), has_length(1))
            assert_that(_memberships(context, existing.id)[0].organization_id, equal_to(context.organization.id))


def test_an_invited_user_who_signs_in_with_google_is_enrolled_and_their_invite_retired():
    with given(
        _setup(
            there_is_an_organization(name="Acme"), there_is_a_user(role=OrganizationRole.MEMBER, email_verified=False)
        )
    ) as context:
        invited = context.user
        raw = _invite_token(context, invited.id)
        google_returns(google_identity(email=invited.email))(context)

        with when("they sign in with Google instead of following the invitation"):
            finish_google_sign_in(context)

        with then("they are verified, joined to the inviting Organization only, and the invitation link is spent"):
            user = context.injector.get(UserRepository).get(invited.id)
            assert_that(user.email_verified_at, not_none())
            assert_that(_memberships(context, invited.id), has_length(1))
            tokens = context.injector.get(PasswordResetTokenRepository)
            assert_that(tokens.get_unused_by_token_hash(raw), none())


# --- one trial per email address --------------------------------------------------------


def test_an_address_that_already_had_a_trial_gets_no_second_one():
    with given(_setup()) as context:
        finish_google_sign_in(context)
        _delete_account(context, _user(context))

        with when("the same address signs up again after its account was deleted"):
            response = finish_google_sign_in(context)

        with then("it is told it already had a trial, and nothing is created"):
            assert_that(redirect_target(response), equal_to((f"{WEB_APP_URL}/signup", {"error": "trial_used"})))
            assert_that(_user(context), none())


def test_the_same_address_in_another_case_counts_as_the_same_trial():
    with given(_setup()) as context:
        finish_google_sign_in(context)
        _delete_account(context, _user(context))
        google_returns(google_identity(sub="another-google-account", email="JANE@Example.com"))(context)

        response = finish_google_sign_in(context)

        assert_that(redirect_target(response)[1], equal_to({"error": "trial_used"}))


def test_another_address_still_gets_its_trial():
    with given(_setup()) as context:
        finish_google_sign_in(context)
        google_returns(google_identity(sub="another-google-account", email="someone.else@example.com"))(context)

        response = finish_google_sign_in(context)

        assert_that(redirect_target(response), equal_to((ONBOARDING, {})))


# --- failures: back where they started, nothing created ------------------------------


@pytest.mark.parametrize("origin,page", [("signup", "/signup"), ("login", "/login")])
def test_cancelling_at_google_creates_nothing(origin, page):
    with given(_setup()) as context:
        with when("someone cancels on Google's consent screen"):
            state = state_from(start_google_sign_in(context, origin))
            response = context.client.get(
                "/api/v1/auth/google/callback",
                params={"error": "access_denied", "state": state},
                follow_redirects=False,
            )

        with then("they land back where they started, told it was cancelled, and nothing exists"):
            assert_that(redirect_target(response), equal_to((f"{WEB_APP_URL}{page}", {"error": "cancelled"})))
            assert_that(_user(context), none())
            assert_that(fake_google(context).exchanges, empty())


def test_a_callback_this_browser_did_not_start_is_refused():
    """The state is bound to the browser that started, so nobody can sign someone else
    in by handing them a callback link."""
    with given(_setup()) as context:
        state = state_from(start_google_sign_in(context))
        context.client.cookies.clear()

        with when("the callback arrives in a browser without the matching cookie"):
            response = context.client.get(
                "/api/v1/auth/google/callback",
                params={"code": "the-code", "state": state},
                follow_redirects=False,
            )

        with then("sign-in fails and nothing is created"):
            assert_that(redirect_target(response)[1], equal_to({"error": "failed"}))
            assert_that(_user(context), none())


def test_a_forged_state_is_refused():
    with given(_setup()) as context:
        start_google_sign_in(context)

        with when("the callback carries a state we did not sign"):
            response = context.client.get(
                "/api/v1/auth/google/callback",
                params={"code": "the-code", "state": "forged"},
                follow_redirects=False,
            )

        with then("sign-in fails and nothing is created"):
            assert_that(redirect_target(response)[1], equal_to({"error": "failed"}))
            assert_that(_user(context), none())


@pytest.mark.parametrize(
    "result,error",
    [(GoogleIdentityError("refused"), "failed"), (GoogleIdentityUnavailable("down"), "unavailable")],
)
def test_a_failed_exchange_creates_nothing(result, error):
    with given(_setup(google_returns(result))) as context:
        with when("Google refuses the code or cannot be reached"):
            response = finish_google_sign_in(context)

        with then("sign-in fails and nothing is created"):
            assert_that(redirect_target(response)[1], equal_to({"error": error}))
            assert_that(_user(context), none())


def test_an_unverified_google_address_creates_nothing():
    with given(_setup(google_returns(google_identity(verified=False)))) as context:
        with when("Google has not verified the account's address"):
            response = finish_google_sign_in(context)

        with then("sign-in is refused and nothing is created"):
            assert_that(redirect_target(response)[1], equal_to({"error": "unverified"}))
            assert_that(_user(context), none())


def test_an_unverified_google_address_cannot_take_over_an_existing_account():
    with given(_setup(there_is_a_user(email=GOOGLE_EMAIL), google_returns(google_identity(verified=False)))) as context:
        response = finish_google_sign_in(context)

        assert_that(redirect_target(response)[1], equal_to({"error": "unverified"}))
        assert_that(_user(context).google_sub, none())


def test_with_signup_closed_new_accounts_are_turned_away():
    with given(_setup(signup="false")) as context:
        with when("someone new comes back from Google"):
            response = finish_google_sign_in(context)

        with then("they are told sign-up is closed and nothing is created"):
            assert_that(redirect_target(response)[1], equal_to({"error": "signup_closed"}))
            assert_that(_user(context), none())


def test_with_signup_closed_existing_users_still_sign_in_with_google():
    with given(_setup(there_is_a_user(email=GOOGLE_EMAIL), signup="false")) as context:
        response = finish_google_sign_in(context)

        assert_that(redirect_target(response), equal_to((DASHBOARD, {})))


def test_a_callback_cannot_be_replayed():
    with given(_setup()) as context:
        state = state_from(start_google_sign_in(context))
        params = {"code": "the-code", "state": state}
        context.client.get("/api/v1/auth/google/callback", params=params, follow_redirects=False)

        with when("the same callback is presented again"):
            response = context.client.get("/api/v1/auth/google/callback", params=params, follow_redirects=False)

        with then("it is refused: the browser's sign-in attempt was used up"):
            assert_that(redirect_target(response)[1], equal_to({"error": "failed"}))
            assert_that(fake_google(context).exchanges, has_length(1))


# --- helpers ------------------------------------------------------------------------


def _set_trial_credit(context, credit: float) -> None:
    there_is_a_user(email="platform-admin@example.com", is_platform_admin=True)(context)
    context.injector.get(TrialSettingsRepository).set_settings(
        {"credit_usd": credit}, 7.5, context.user.id, "Platform Admin"
    )


def _delete_account(context, user) -> None:
    for membership in _memberships(context, user.id):
        context.injector.get(OrganizationRepository).delete(membership.organization_id)
    context.injector.get(UserRepository).delete(user.id)


def _invite_token(context, user_id) -> str:
    raw = context.injector.get(AuthService).generate_password_reset_token(user_id)
    return AuthService._hash_reset_token(raw)


def test_the_current_user_says_they_signed_themselves_up():
    with given(_setup()) as context:
        finish_google_sign_in(context)
        token = context.client.post("/api/v1/auth/refresh").json()["access_token"]

        me = context.client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})

        assert_that(me.json(), has_entries(signed_up_at=not_none()))

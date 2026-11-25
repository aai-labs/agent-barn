from uuid import UUID, uuid7

import pytest
from fastapi import BackgroundTasks, status
from hamcrest import assert_that, equal_to
from sqlmodel import Session

from api.core.config import Config
from api.domains.auth.models import SignupRequest
from api.domains.auth.service import AuthService
from api.domains.llm_providers.models import (
    OPENROUTER_CONNECTION_ID,
    LlmProviderConnection,
    LlmProviderConnectionOrganization,
    OrganizationAccess,
)
from api.domains.organizations.models import Organization
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.repository import UserRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.integration.test_free_tier_signup import the_inbox_had_free, tier_is_offered
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.google_sign_in import GOOGLE_EMAIL, WEB_APP_URL, FakeGoogleIdentityModule, finish_google_sign_in
from api.tests.steps.onboarding import trial_settings_are_configured
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

SIGNUP_EMAIL = "signup-access@example.com"
INVITED_EMAIL = "invited-access@example.com"
ACCESS = [
    pytest.param(OrganizationAccess.ONLY, "other", False, id="closed_only_another"),
    pytest.param(OrganizationAccess.ALL_EXCEPT, "other", True, id="open_all_except_another"),
]


def _setup(access: OrganizationAccess, listed: str | None, *steps):
    return [
        set_env_variable(
            {
                "WEB_APP_URL": WEB_APP_URL,
                "AGENTBARN_TELEGRAM_BOT_TOKEN": "424242:the-shared-bot-token",
                "AGENTBARN_TELEGRAM_BOT_USERNAME": "AgentBarnTestBot",
                "TIERS_MOCK_PAYMENTS": "true",
            }
        ),
        prepare_injector(modules=[FakeGoogleIdentityModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        trial_settings_are_configured(credit=12, agent_limit=1),
        tier_is_offered("cloud_1"),
        openrouter_access(access, listed),
        *steps,
    ]


def openrouter_access(access: OrganizationAccess, listed: str | None):
    def step(context):
        with Session(_engine(context)) as session:
            connection = session.get_one(LlmProviderConnection, OPENROUTER_CONNECTION_ID)
            connection.organization_access = access
            session.add(connection)
            if listed == "other":
                other = Organization(name="Other Org")
                session.add(other)
                session.flush()
                session.add(LlmProviderConnectionOrganization(connection_id=connection.id, organization_id=other.id))
            session.commit()

    return step


def signed_in_user(*, platform_provisioned: bool):
    def step(context):
        user_id = uuid7()
        there_is_a_user(id=user_id, email=INVITED_EMAIL, platform_provisioned=platform_provisioned)(context)
        there_is_an_access_token_for_user(user_id=user_id)(context)

    return step


def platform_admin(context):
    user_id = uuid7()
    there_is_a_user(id=user_id, email="admin-access@example.com", is_platform_admin=True)(context)
    there_is_an_access_token_for_user(user_id=user_id)(context)


def _engine(context):
    return context.injector.get(PostgresRepositoryDelegate).engine


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _allowlist(context, organization_id: UUID | str) -> list[str]:
    with Session(_engine(context)) as session:
        return session.get_one(Organization, UUID(str(organization_id))).allowed_models


def _owned_allowlist(context, email: str) -> list[str]:
    user = context.injector.get(UserRepository).get_by_email(email)
    (membership,) = context.injector.get(OrganizationUserRepository).get_by_user_id(user.id)
    return _allowlist(context, membership.organization_id)


def _expected(context, seeded: bool) -> list[str]:
    return [context.injector.get(Config).agent_default_model.removeprefix("litellm/openrouter/")] if seeded else []


@pytest.mark.parametrize(("access", "listed", "seeded"), ACCESS)
def test_a_password_sign_up_seeds_the_allowlist_only_while_openrouter_is_open(access, listed, seeded):
    with given(_setup(access, listed)) as context:
        context.injector.get(AuthService).signup(
            SignupRequest(email=SIGNUP_EMAIL, password="StrongPass123!x", full_name="Sign Up"), BackgroundTasks()
        )

        assert_that(_owned_allowlist(context, SIGNUP_EMAIL), equal_to(_expected(context, seeded)))


@pytest.mark.parametrize(("access", "listed", "seeded"), ACCESS)
def test_a_google_sign_up_on_free_seeds_the_allowlist_only_while_openrouter_is_open(access, listed, seeded):
    with given(_setup(access, listed)) as context:
        finish_google_sign_in(context)

        assert_that(_owned_allowlist(context, GOOGLE_EMAIL), equal_to(_expected(context, seeded)))


@pytest.mark.parametrize(("access", "listed", "seeded"), ACCESS)
def test_a_google_sign_up_without_free_seeds_the_allowlist_only_while_openrouter_is_open(access, listed, seeded):
    with given(_setup(access, listed, the_inbox_had_free)) as context:
        finish_google_sign_in(context)

        assert_that(_owned_allowlist(context, GOOGLE_EMAIL), equal_to(_expected(context, seeded)))


@pytest.mark.parametrize(("access", "listed", "seeded"), ACCESS)
def test_a_user_set_up_by_a_platform_admin_gets_an_allowlist_only_while_openrouter_is_open(access, listed, seeded):
    with given(_setup(access, listed, platform_admin)) as context:
        response = context.client.post(
            "/api/v1/platform/users",
            json={"email": INVITED_EMAIL, "full_name": "Invited", "organization_name": "Invited Org"},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)
        assert_that(_allowlist(context, response.json()["organization"]["id"]), equal_to(_expected(context, seeded)))


@pytest.mark.parametrize("trial", [False, True])
@pytest.mark.parametrize(("access", "listed", "seeded"), ACCESS)
def test_an_organization_a_user_creates_gets_an_allowlist_only_while_openrouter_is_open(access, listed, seeded, trial):
    with given(_setup(access, listed, signed_in_user(platform_provisioned=not trial))) as context:
        response = context.client.post("/api/v1/organizations", json={"name": "Fresh Org"}, headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED), response.text)
        assert_that(response.json()["is_trial"], equal_to(trial))
        assert_that(_allowlist(context, response.json()["id"]), equal_to(_expected(context, seeded)))

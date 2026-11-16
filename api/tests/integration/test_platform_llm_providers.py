from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest
from hamcrest import assert_that, equal_to, has_entries, is_not, none
from sqlmodel import Session

from api.core.config import Config
from api.domains.llm_providers.lookup import OpenRouterKeyLookup
from api.domains.llm_providers.models import OPENROUTER_CONNECTION_ID, KeySource, LlmProviderConnection
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, use_org_for_auth
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

BASE = "/api/v1/platform/settings/llm-providers/openrouter"
STORED_KEY = "sk-or-v1-stored-key-a1b2"
ENV_KEY = "sk-or-v1-environment-key-9z8y"
ADMIN_NAME = "Platform Person"


def _setup(*steps):
    return [
        set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY, "SKIP_SLACK_TOKEN_VALIDATION": "true"}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        *steps,
    ]


def admin(context):
    organization = context.organization
    del context.organization
    try:
        user_id = uuid7()
        there_is_a_user(id=user_id, name=ADMIN_NAME, email=f"platform-{user_id}@example.com", is_platform_admin=True)(
            context
        )
        there_is_an_access_token_for_user(user_id)(context)
        context.admin_id = user_id
    finally:
        context.organization = organization


def env_key(value: str):
    def step(context):
        context.injector.get(Config).openrouter_api_key = value

    return step


def _store_key(context, key: str, source: KeySource, updated_by: UUID | None = None) -> None:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        row = session.get(LlmProviderConnection, OPENROUTER_CONNECTION_ID)
        assert row is not None
        row.api_key_encrypted = encrypt_token(key, TEST_ENCRYPTION_KEY)
        row.api_key_last4 = key[-4:]
        row.key_source = source
        row.updated_by = updated_by
        row.updated_at = datetime.now(UTC)
        session.add(row)
        session.commit()


def auth(context):
    return {"Authorization": f"Bearer {context.access_token}"}


def test_an_organization_owner_cannot_read_the_openrouter_key_status():
    with given(_setup()) as context:
        response = context.client.get(BASE, headers=auth(context))

        assert_that(response.status_code, equal_to(403))


def test_the_openrouter_key_status_needs_a_signed_in_user():
    with given(_setup()) as context:
        response = context.client.get(BASE)

        assert_that(response.status_code, equal_to(401))


def test_a_platform_admin_sees_that_no_key_is_set():
    with given(_setup(admin, env_key(""))) as context:
        response = context.client.get(BASE, headers=auth(context))

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            response.json(),
            equal_to(
                {
                    "has_api_key": False,
                    "api_key_last4": None,
                    "key_source": None,
                    "updated_at": None,
                    "updated_by": None,
                    "env_key_configured": False,
                }
            ),
        )


def test_a_platform_admin_sees_the_last_four_characters_and_who_set_the_key():
    with given(_setup(admin, env_key(""))) as context:
        _store_key(context, STORED_KEY, KeySource.ADMIN, context.admin_id)

        response = context.client.get(BASE, headers=auth(context))

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            response.json(),
            has_entries(
                has_api_key=True,
                api_key_last4="a1b2",
                key_source="admin",
                updated_by=ADMIN_NAME,
                env_key_configured=False,
            ),
        )
        assert_that(response.json()["updated_at"], is_not(none()))


def test_the_key_status_never_carries_the_key_or_its_ciphertext():
    with given(_setup(admin, env_key(ENV_KEY))) as context:
        _store_key(context, STORED_KEY, KeySource.ENVIRONMENT)
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            row = session.get(LlmProviderConnection, OPENROUTER_CONNECTION_ID)
            assert row is not None and row.api_key_encrypted is not None
            ciphertext = row.api_key_encrypted

        response = context.client.get(BASE, headers=auth(context))

        assert_that(response.json(), has_entries(key_source="environment", updated_by=None))
        for secret in (STORED_KEY, ciphertext, ENV_KEY):
            assert secret not in response.text


@pytest.mark.parametrize("value,configured", [(ENV_KEY, True), ("", False)])
def test_the_status_says_whether_the_environment_still_sets_a_key(value, configured):
    with given(_setup(admin, env_key(value))) as context:
        response = context.client.get(BASE, headers=auth(context))

        assert_that(response.json(), has_entries(env_key_configured=configured))


def test_the_lookup_prefers_the_stored_key_to_the_environment():
    with given(_setup(env_key(ENV_KEY))) as context:
        _store_key(context, STORED_KEY, KeySource.ADMIN)

        assert_that(context.injector.get(OpenRouterKeyLookup).api_key(), equal_to(STORED_KEY))


def test_the_lookup_falls_back_to_the_environment_key():
    with given(_setup(env_key(ENV_KEY))) as context:
        assert_that(context.injector.get(OpenRouterKeyLookup).api_key(), equal_to(ENV_KEY))


def test_the_lookup_finds_no_key_when_neither_is_set():
    with given(_setup(env_key(""))) as context:
        assert_that(context.injector.get(OpenRouterKeyLookup).api_key(), equal_to(""))

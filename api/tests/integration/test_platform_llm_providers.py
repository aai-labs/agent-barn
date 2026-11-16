from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID, uuid7

import pytest
from hamcrest import assert_that, equal_to, has_entries, has_length, is_not, none
from sqlmodel import Session, select

from api.core.config import Config
from api.domains.events.models import OutboxMessage
from api.domains.llm_providers.lookup import OpenRouterKeyLookup
from api.domains.llm_providers.models import OPENROUTER_CONNECTION_ID, KeySource, LlmProviderConnection
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError
from api.infrastructure.openrouter.client import OpenRouterClient, OpenRouterError
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


NEW_KEY = "sk-or-v1-replacement-key-c3d4"
CHANGED_EVENT = "platform.llm_provider.changed"
EXPECTED_ROUTE = {
    "model_name": "openrouter/*",
    "litellm_params": {
        "model": "openrouter/*",
        "api_key": NEW_KEY,
        "api_base": "https://openrouter.ai/api/v1",
        "order": 1,
    },
    "model_info": {"id": "agentbarn:openrouter", "disable_background_health_check": True},
}


def openrouter_answers(accepted: bool | Exception):
    def step(context):
        check = Mock(side_effect=accepted) if isinstance(accepted, Exception) else Mock(return_value=accepted)
        context.injector.get(OpenRouterClient).check_key = check
        context.check_key = check

    return step


def _litellm(context):
    return context.injector.get(LiteLLMClient)


def _row(context) -> LlmProviderConnection:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        row = session.get(LlmProviderConnection, OPENROUTER_CONNECTION_ID)
        assert row is not None
        return row


def _events(context) -> list[OutboxMessage]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(session.exec(select(OutboxMessage).where(OutboxMessage.event_name == CHANGED_EVENT)).all())


def _assert_nothing_changed(context, response) -> None:
    row = _row(context)
    assert row.api_key_encrypted is not None
    assert_that(decrypt_token(row.api_key_encrypted, TEST_ENCRYPTION_KEY), equal_to(STORED_KEY))
    assert_that(row.key_source, equal_to(KeySource.ENVIRONMENT))
    assert_that(_events(context), has_length(0))
    assert NEW_KEY not in response.text


def test_an_organization_owner_cannot_replace_the_openrouter_key():
    with given(_setup(openrouter_answers(True))) as context:
        response = context.client.put(BASE, headers=auth(context), json={"api_key": NEW_KEY})

        assert_that(response.status_code, equal_to(403))
        context.check_key.assert_not_called()
        _litellm(context).upsert_model_deployment.assert_not_called()


def test_a_read_only_api_key_cannot_replace_the_openrouter_key():
    with given(_setup(admin, openrouter_answers(True))) as context:
        created = context.client.post(
            "/api/v1/auth/me/api-keys", json={"name": "Automation", "access_mode": "READ_ONLY"}, headers=auth(context)
        )
        read_only = {"Authorization": f"Bearer {created.json()['token']}"}

        assert_that(context.client.get(BASE, headers=read_only).status_code, equal_to(200))
        response = context.client.put(BASE, headers=read_only, json={"api_key": NEW_KEY})

        assert_that(response.status_code, equal_to(403))
        context.check_key.assert_not_called()
        _litellm(context).upsert_model_deployment.assert_not_called()


def test_a_platform_admin_replaces_the_key_and_litellm_routes_with_it():
    with given(_setup(admin, env_key(""), openrouter_answers(True))) as context:
        _store_key(context, STORED_KEY, KeySource.ENVIRONMENT)

        response = context.client.put(BASE, headers=auth(context), json={"api_key": f"  {NEW_KEY}  "})

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            response.json(),
            has_entries(has_api_key=True, api_key_last4="c3d4", key_source="admin", updated_by=ADMIN_NAME),
        )
        assert NEW_KEY not in response.text
        context.check_key.assert_called_once_with(NEW_KEY)
        _litellm(context).upsert_model_deployment.assert_called_once_with(**EXPECTED_ROUTE)
        row = _row(context)
        assert row.api_key_encrypted is not None and NEW_KEY not in row.api_key_encrypted
        assert_that(decrypt_token(row.api_key_encrypted, TEST_ENCRYPTION_KEY), equal_to(NEW_KEY))
        assert_that(row.updated_by, equal_to(context.admin_id))
        assert_that(context.injector.get(OpenRouterKeyLookup).api_key(), equal_to(NEW_KEY))


def test_the_change_is_audited_with_no_key_in_the_event():
    with given(_setup(admin, openrouter_answers(True))) as context:
        _store_key(context, STORED_KEY, KeySource.ENVIRONMENT)

        context.client.put(BASE, headers=auth(context), json={"api_key": NEW_KEY})

        events = _events(context)
        assert_that(events, has_length(1))
        assert_that(
            events[0].payload,
            equal_to(
                {
                    "connection_id": str(OPENROUTER_CONNECTION_ID),
                    "slug": "openrouter",
                    "key_source": "admin",
                    "replaced_existing": True,
                    "actor_display": ADMIN_NAME,
                    "subject_display": "OpenRouter",
                }
            ),
        )
        for secret in (NEW_KEY, STORED_KEY, "c3d4", "a1b2"):
            assert secret not in str(events[0].payload)


def test_setting_the_first_key_records_that_none_was_replaced():
    with given(_setup(admin, openrouter_answers(True))) as context:
        context.client.put(BASE, headers=auth(context), json={"api_key": NEW_KEY})

        assert_that(_events(context)[0].payload, has_entries(replaced_existing=False))


def test_a_key_openrouter_refuses_changes_nothing():
    with given(_setup(admin, openrouter_answers(False))) as context:
        _store_key(context, STORED_KEY, KeySource.ENVIRONMENT)

        response = context.client.put(BASE, headers=auth(context), json={"api_key": NEW_KEY})

        assert_that(response.status_code, equal_to(422))
        _litellm(context).upsert_model_deployment.assert_not_called()
        _assert_nothing_changed(context, response)


def test_an_unreachable_openrouter_changes_nothing():
    with given(_setup(admin, openrouter_answers(OpenRouterError("unreachable")))) as context:
        _store_key(context, STORED_KEY, KeySource.ENVIRONMENT)

        response = context.client.put(BASE, headers=auth(context), json={"api_key": NEW_KEY})

        assert_that(response.status_code, equal_to(503))
        _litellm(context).upsert_model_deployment.assert_not_called()
        _assert_nothing_changed(context, response)


def test_a_litellm_failure_changes_nothing():
    with given(_setup(admin, openrouter_answers(True))) as context:
        _store_key(context, STORED_KEY, KeySource.ENVIRONMENT)
        _litellm(context).upsert_model_deployment.side_effect = LiteLLMError("Failed to write the model route")

        response = context.client.put(BASE, headers=auth(context), json={"api_key": NEW_KEY})

        assert_that(response.status_code, equal_to(503))
        _assert_nothing_changed(context, response)


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"api_key": ""},
        {"api_key": "   "},
        {"api_key": 12345},
        {"api_key": "x" * 513},
        {"api_key": NEW_KEY, "unexpected": NEW_KEY},
    ],
)
def test_a_malformed_request_is_refused_without_echoing_it(body):
    with given(_setup(admin, openrouter_answers(True))) as context:
        response = context.client.put(BASE, headers=auth(context), json=body)

        assert_that(response.status_code, equal_to(422))
        assert NEW_KEY not in response.text
        assert "x" * 513 not in response.text
        context.check_key.assert_not_called()
        _litellm(context).upsert_model_deployment.assert_not_called()

from datetime import UTC, datetime
from unittest.mock import Mock
from uuid import UUID, uuid7

import pytest
from hamcrest import assert_that, equal_to, has_entries, has_length, is_not, none
from sqlmodel import Session, col, select

from api.core.config import Config
from api.domains.events.models import OutboxMessage
from api.domains.llm_providers.models import OPENROUTER_CONNECTION_ID, LlmProviderConnection, ProviderType
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.litellm.client import LiteLLMClient
from api.infrastructure.llm_provider_keys.checker import LlmProviderKeyChecker, LlmProviderUnreachable
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, use_org_for_auth
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

BASE = "/api/v1/platform/settings/llm-providers"
OPENROUTER_KEY = "sk-or-v1-stored-key-a1b2"
ANTHROPIC_KEY = "sk-ant-stored-key-c3d4"
AZURE_KEY = "azure-stored-key-e5f6"
ENV_KEY = "sk-or-v1-environment-key-9z8y"
ADMIN_NAME = "Platform Person"
AZURE_BASE_URL = "https://contoso.openai.azure.com"
NEW_KEY = "sk-new-provider-key-g7h8"
CREATED_EVENT = "platform.llm_provider.created"
KNOWN_PROVIDERS = [
    (ProviderType.ANTHROPIC, "Anthropic"),
    (ProviderType.OPENAI, "OpenAI"),
    (ProviderType.GEMINI, "Gemini"),
    (ProviderType.XAI, "xAI"),
    (ProviderType.DEEPSEEK, "DeepSeek"),
    (ProviderType.FIREWORKS, "Fireworks"),
    (ProviderType.NOVITA, "Novita"),
]


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


def auth(context):
    return {"Authorization": f"Bearer {context.access_token}"}


def _session(context) -> Session:
    return Session(context.injector.get(PostgresRepositoryDelegate).engine)


def _store_openrouter_key(context, key: str, updated_by: UUID | None = None) -> str:
    with _session(context) as session:
        row = session.get(LlmProviderConnection, OPENROUTER_CONNECTION_ID)
        assert row is not None
        row.api_key_encrypted = encrypt_token(key, TEST_ENCRYPTION_KEY)
        row.api_key_last4 = key[-4:]
        row.updated_by = updated_by
        row.updated_at = datetime.now(UTC)
        session.add(row)
        session.commit()
        return row.api_key_encrypted


def _connection(context, slug: str, name: str, provider_type: ProviderType, **fields) -> LlmProviderConnection:
    row = LlmProviderConnection(slug=slug, name=name, provider_type=provider_type, **fields)
    with _session(context) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def _with_key(key: str, updated_by: UUID | None = None) -> dict:
    return {
        "api_key_encrypted": encrypt_token(key, TEST_ENCRYPTION_KEY),
        "api_key_last4": key[-4:],
        "updated_by": updated_by,
    }


def test_an_organization_owner_cannot_list_the_connections():
    with given(_setup()) as context:
        response = context.client.get(BASE, headers=auth(context))

        assert_that(response.status_code, equal_to(403))


def test_listing_the_connections_needs_a_signed_in_user():
    with given(_setup()) as context:
        response = context.client.get(BASE)

        assert_that(response.status_code, equal_to(401))


def test_a_read_only_api_key_of_a_platform_admin_can_list_the_connections():
    with given(_setup(admin)) as context:
        created = context.client.post(
            "/api/v1/auth/me/api-keys", json={"name": "Automation", "access_mode": "READ_ONLY"}, headers=auth(context)
        )
        read_only = {"Authorization": f"Bearer {created.json()['token']}"}

        response = context.client.get(BASE, headers=read_only)

        assert_that(response.status_code, equal_to(200), response.text)


def test_a_fresh_platform_lists_openrouter_alone_without_a_key():
    with given(_setup(admin, env_key(""))) as context:
        response = context.client.get(BASE, headers=auth(context))

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            response.json(),
            equal_to(
                [
                    {
                        "slug": "openrouter",
                        "name": "OpenRouter",
                        "provider_type": "openrouter",
                        "base_url": None,
                        "has_api_key": False,
                        "api_key_last4": None,
                        "updated_at": None,
                        "updated_by": None,
                        "env_key_configured": False,
                    }
                ]
            ),
        )


def test_the_list_shows_live_connections_with_openrouter_first_then_by_name():
    with given(_setup(admin, env_key(""))) as context:
        _connection(context, "anthropic", "Anthropic", ProviderType.ANTHROPIC, **_with_key(ANTHROPIC_KEY))
        _connection(context, "custom-lab", "Aardvark lab", ProviderType.CUSTOM, base_url="https://lab.example.com/v1")
        _connection(
            context,
            "azure-eu",
            "Bravo Azure",
            ProviderType.AZURE,
            base_url=AZURE_BASE_URL,
            **_with_key(AZURE_KEY, context.admin_id),
        )
        _connection(context, "deepseek", "DeepSeek", ProviderType.DEEPSEEK)
        _connection(context, "openai", "Able OpenAI", ProviderType.OPENAI, deleted_at=datetime.now(UTC))

        response = context.client.get(BASE, headers=auth(context))

        assert_that(response.status_code, equal_to(200), response.text)
        listed = response.json()
        assert_that(
            [item["slug"] for item in listed],
            equal_to(["openrouter", "custom-lab", "anthropic", "azure-eu", "deepseek"]),
        )
        azure = listed[3]
        assert_that(
            azure,
            has_entries(
                name="Bravo Azure",
                provider_type="azure",
                base_url=AZURE_BASE_URL,
                has_api_key=True,
                api_key_last4="e5f6",
                updated_by=ADMIN_NAME,
                env_key_configured=False,
            ),
        )
        assert_that(azure["updated_at"], is_not(none()))
        assert_that(listed[2], has_entries(provider_type="anthropic", base_url=None, updated_by=None))


def test_only_openrouter_reports_the_environment_key():
    with given(_setup(admin, env_key(ENV_KEY))) as context:
        _connection(context, "anthropic", "Anthropic", ProviderType.ANTHROPIC, **_with_key(ANTHROPIC_KEY))

        response = context.client.get(BASE, headers=auth(context))

        assert_that(
            [(item["slug"], item["env_key_configured"]) for item in response.json()],
            equal_to([("openrouter", True), ("anthropic", False)]),
        )


def test_the_list_never_carries_a_key_or_its_ciphertext():
    with given(_setup(admin, env_key(ENV_KEY))) as context:
        openrouter_ciphertext = _store_openrouter_key(context, OPENROUTER_KEY, context.admin_id)
        anthropic = _connection(context, "anthropic", "Anthropic", ProviderType.ANTHROPIC, **_with_key(ANTHROPIC_KEY))

        response = context.client.get(BASE, headers=auth(context))

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(response.json()[0], has_entries(has_api_key=True, api_key_last4="a1b2", updated_by=ADMIN_NAME))
        for secret in (OPENROUTER_KEY, openrouter_ciphertext, ANTHROPIC_KEY, anthropic.api_key_encrypted, ENV_KEY):
            assert secret not in response.text


def provider_answers(accepted: bool | Exception):
    def step(context):
        check = Mock(side_effect=accepted) if isinstance(accepted, Exception) else Mock(return_value=accepted)
        context.injector.get(LlmProviderKeyChecker).check = check
        context.check = check

    return step


def _rows(context, slug: str) -> list[LlmProviderConnection]:
    with _session(context) as session:
        return list(session.exec(select(LlmProviderConnection).where(LlmProviderConnection.slug == slug)).all())


def _events(context) -> list[OutboxMessage]:
    with _session(context) as session:
        return list(session.exec(select(OutboxMessage).where(col(OutboxMessage.event_name) == CREATED_EVENT)).all())


def _add(context, provider_type: str, key: str = NEW_KEY, headers: dict | None = None):
    return context.client.post(
        BASE, headers=headers or auth(context), json={"provider_type": provider_type, "api_key": key}
    )


def test_an_organization_owner_cannot_add_a_provider():
    with given(_setup(provider_answers(True))) as context:
        response = _add(context, "anthropic")

        assert_that(response.status_code, equal_to(403))
        context.check.assert_not_called()
        assert_that(_rows(context, "anthropic"), equal_to([]))


def test_a_read_only_api_key_cannot_add_a_provider():
    with given(_setup(admin, provider_answers(True))) as context:
        created = context.client.post(
            "/api/v1/auth/me/api-keys", json={"name": "Automation", "access_mode": "READ_ONLY"}, headers=auth(context)
        )
        read_only = {"Authorization": f"Bearer {created.json()['token']}"}

        response = _add(context, "anthropic", headers=read_only)

        assert_that(response.status_code, equal_to(403))
        context.check.assert_not_called()
        assert_that(_rows(context, "anthropic"), equal_to([]))


@pytest.mark.parametrize(("provider_type", "name"), KNOWN_PROVIDERS)
def test_a_platform_admin_adds_a_known_provider_with_a_key_it_accepts(provider_type, name):
    with given(_setup(admin, env_key(ENV_KEY), provider_answers(True))) as context:
        response = _add(context, provider_type.value, key=f"  {NEW_KEY}  ")

        assert_that(response.status_code, equal_to(201), response.text)
        assert_that(
            response.json(),
            has_entries(
                slug=provider_type.value,
                name=name,
                provider_type=provider_type.value,
                base_url=None,
                has_api_key=True,
                api_key_last4="g7h8",
                updated_by=ADMIN_NAME,
                env_key_configured=False,
            ),
        )
        assert NEW_KEY not in response.text
        context.check.assert_called_once_with(provider_type, NEW_KEY)
        context.injector.get(LiteLLMClient).upsert_model_deployment.assert_not_called()
        [row] = _rows(context, provider_type.value)
        assert row.api_key_encrypted is not None and NEW_KEY not in row.api_key_encrypted
        assert_that(decrypt_token(row.api_key_encrypted, TEST_ENCRYPTION_KEY), equal_to(NEW_KEY))
        assert_that(row.updated_by, equal_to(context.admin_id))
        listed = context.client.get(BASE, headers=auth(context)).json()
        assert_that([item["slug"] for item in listed], equal_to(["openrouter", provider_type.value]))


def test_adding_a_provider_is_audited_with_no_part_of_the_key():
    with given(_setup(admin, provider_answers(True))) as context:
        _add(context, "anthropic")

        [row] = _rows(context, "anthropic")
        events = _events(context)
        assert_that(events, has_length(1))
        assert_that(
            events[0].payload,
            equal_to(
                {
                    "connection_id": str(row.id),
                    "slug": "anthropic",
                    "provider_type": "anthropic",
                    "base_url": None,
                    "revived": False,
                    "actor_display": ADMIN_NAME,
                    "subject_display": "Anthropic",
                }
            ),
        )
        assert_that(events[0].subject, has_entries(type="SYSTEM", id=str(row.id)))
        for secret in (NEW_KEY, "g7h8"):
            assert secret not in str(events[0].payload)


def test_a_key_the_provider_refuses_stores_nothing():
    with given(_setup(admin, provider_answers(False))) as context:
        response = _add(context, "openai")

        assert_that(response.status_code, equal_to(422))
        assert NEW_KEY not in response.text
        assert_that(_rows(context, "openai"), equal_to([]))
        assert_that(_events(context), has_length(0))


def test_an_unreachable_provider_stores_nothing():
    with given(_setup(admin, provider_answers(LlmProviderUnreachable()))) as context:
        response = _add(context, "gemini")

        assert_that(response.status_code, equal_to(503))
        assert NEW_KEY not in response.text
        assert_that(_rows(context, "gemini"), equal_to([]))
        assert_that(_events(context), has_length(0))


def test_a_provider_already_connected_is_refused_without_checking_the_key():
    with given(_setup(admin, provider_answers(True))) as context:
        _connection(context, "anthropic", "Anthropic", ProviderType.ANTHROPIC, **_with_key(ANTHROPIC_KEY))

        response = _add(context, "anthropic")

        assert_that(response.status_code, equal_to(409))
        context.check.assert_not_called()
        [row] = _rows(context, "anthropic")
        assert row.api_key_encrypted is not None
        assert_that(decrypt_token(row.api_key_encrypted, TEST_ENCRYPTION_KEY), equal_to(ANTHROPIC_KEY))
        assert_that(_events(context), has_length(0))


def test_openrouter_cannot_be_added_again():
    with given(_setup(admin, provider_answers(True))) as context:
        response = _add(context, "openrouter")

        assert_that(response.status_code, equal_to(409))
        context.check.assert_not_called()
        assert_that(_rows(context, "openrouter"), has_length(1))
        assert_that(_events(context), has_length(0))


def test_a_deleted_provider_is_revived_with_its_new_key():
    with given(_setup(admin, provider_answers(True))) as context:
        deleted = _connection(context, "deepseek", "DeepSeek", ProviderType.DEEPSEEK, deleted_at=datetime.now(UTC))

        response = _add(context, "deepseek")

        assert_that(response.status_code, equal_to(201), response.text)
        [row] = _rows(context, "deepseek")
        assert_that(row.id, equal_to(deleted.id))
        assert_that(row.deleted_at, none())
        assert row.api_key_encrypted is not None
        assert_that(decrypt_token(row.api_key_encrypted, TEST_ENCRYPTION_KEY), equal_to(NEW_KEY))
        assert_that(_events(context)[0].payload, has_entries(connection_id=str(deleted.id), revived=True))


@pytest.mark.parametrize(
    "body",
    [
        {"provider_type": "anthropic"},
        {"provider_type": "anthropic", "api_key": "   "},
        {"provider_type": "anthropic", "api_key": NEW_KEY, "base_url": AZURE_BASE_URL},
        {"provider_type": "mistral", "api_key": NEW_KEY},
        {"provider_type": "azure", "api_key": NEW_KEY},
        {"provider_type": "custom", "api_key": NEW_KEY},
    ],
)
def test_a_malformed_request_is_refused_without_echoing_it(body):
    with given(_setup(admin, provider_answers(True))) as context:
        response = context.client.post(BASE, headers=auth(context), json=body)

        assert_that(response.status_code, equal_to(422))
        assert_that(response.json(), equal_to({"detail": "Invalid LLM provider key request"}))
        context.check.assert_not_called()

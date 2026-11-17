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
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError
from api.infrastructure.llm_provider_keys.checker import (
    BaseUrlNotAnApi,
    BaseUrlNotPublic,
    LlmProviderKeyChecker,
    LlmProviderUnreachable,
)
from api.infrastructure.openrouter.client import OpenRouterClient, OpenRouterError
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
        {"provider_type": "anthropic", "api_key": NEW_KEY, "slug": "anthropic-2"},
        {"provider_type": "anthropic", "api_key": NEW_KEY, "name": "Claude"},
        {"provider_type": "azure", "api_key": NEW_KEY, "name": "Azure", "base_url": AZURE_BASE_URL},
        {"provider_type": "azure", "api_key": NEW_KEY, "slug": "azure-eu", "base_url": AZURE_BASE_URL},
        {"provider_type": "custom", "api_key": NEW_KEY, "slug": "lab", "name": "Lab"},
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


SLUG_FORMAT = "The slug must be at most 32 lowercase letters, digits and single hyphens."
SLUG_IS_A_PROVIDER = "The slug can't be a provider's name."
SLUG_TAKEN = "That slug is in use or was used before. Choose another."
NAME_FORMAT = "Enter a name of at most 64 characters."
NOT_PUBLIC = "The base URL must be a public HTTPS address. Nothing was saved."
URL_EXTRAS = "The base URL can't contain credentials, a query or a fragment. Nothing was saved."
NOT_AN_API = "The base URL did not answer like a model API. Nothing was saved."


def _add_own(
    context,
    provider_type: str,
    slug: str = "azure-eu",
    name: str = "Azure Europe",
    base_url: str = AZURE_BASE_URL,
    key: str = NEW_KEY,
):
    return context.client.post(
        BASE,
        headers=auth(context),
        json={"provider_type": provider_type, "slug": slug, "name": name, "base_url": base_url, "api_key": key},
    )


def _assert_refused(context, response, status_code: int, detail: str, slug: str = "azure-eu") -> None:
    assert_that(response.status_code, equal_to(status_code), response.text)
    assert_that(response.json(), equal_to({"detail": detail}))
    assert NEW_KEY not in response.text
    stored_keys = [
        decrypt_token(row.api_key_encrypted, TEST_ENCRYPTION_KEY)
        for row in _rows(context, slug)
        if row.api_key_encrypted is not None
    ]
    assert NEW_KEY not in stored_keys
    assert_that(_events(context), has_length(0))


@pytest.mark.parametrize("provider_type", [ProviderType.AZURE, ProviderType.CUSTOM])
def test_a_platform_admin_adds_an_azure_or_custom_connection(provider_type):
    with given(_setup(admin, provider_answers(True))) as context:
        response = _add_own(
            context, provider_type.value, slug="eu-models", name="  EU models  ", base_url=f"{AZURE_BASE_URL}//"
        )

        assert_that(response.status_code, equal_to(201), response.text)
        assert_that(
            response.json(),
            has_entries(
                slug="eu-models",
                name="EU models",
                provider_type=provider_type.value,
                base_url=AZURE_BASE_URL,
                has_api_key=True,
                api_key_last4="g7h8",
                updated_by=ADMIN_NAME,
            ),
        )
        context.check.assert_called_once_with(provider_type, NEW_KEY, AZURE_BASE_URL)
        [row] = _rows(context, "eu-models")
        assert_that(row.base_url, equal_to(AZURE_BASE_URL))
        assert_that(
            _events(context)[0].payload,
            has_entries(slug="eu-models", provider_type=provider_type.value, base_url=AZURE_BASE_URL, revived=False),
        )


def test_several_azure_connections_can_be_added():
    with given(_setup(admin, provider_answers(True))) as context:
        first = _add_own(context, "azure", slug="azure-eu", name="Azure Europe")
        second = _add_own(
            context, "azure", slug="azure-us", name="Azure US", base_url="https://fabrikam.openai.azure.com"
        )

        assert_that((first.status_code, second.status_code), equal_to((201, 201)))
        listed = context.client.get(BASE, headers=auth(context)).json()
        assert_that([item["slug"] for item in listed], equal_to(["openrouter", "azure-eu", "azure-us"]))


@pytest.mark.parametrize(
    ("slug", "detail"),
    [
        ("Azure-EU", SLUG_FORMAT),
        ("-azure", SLUG_FORMAT),
        ("azure--eu", SLUG_FORMAT),
        ("azure/eu", SLUG_FORMAT),
        ("", SLUG_FORMAT),
        ("a" * 33, SLUG_FORMAT),
        ("openai", SLUG_IS_A_PROVIDER),
        ("openrouter", SLUG_IS_A_PROVIDER),
        ("azure", SLUG_IS_A_PROVIDER),
        ("custom", SLUG_IS_A_PROVIDER),
    ],
)
def test_a_slug_that_breaks_the_rules_is_refused_before_the_key_is_checked(slug, detail):
    with given(_setup(admin, provider_answers(True))) as context:
        response = _add_own(context, "custom", slug=slug)

        _assert_refused(context, response, 422, detail, slug=slug)
        context.check.assert_not_called()


@pytest.mark.parametrize("deleted", [False, True])
def test_a_slug_already_used_is_refused_before_the_key_is_checked(deleted):
    with given(_setup(admin, provider_answers(True))) as context:
        _connection(
            context,
            "azure-eu",
            "Azure Europe",
            ProviderType.AZURE,
            base_url=AZURE_BASE_URL,
            deleted_at=datetime.now(UTC) if deleted else None,
        )

        response = _add_own(context, "custom", slug="azure-eu", base_url="https://lab.example.com/v1")

        _assert_refused(context, response, 409, SLUG_TAKEN)
        context.check.assert_not_called()
        [row] = _rows(context, "azure-eu")
        assert_that(row.provider_type, equal_to(ProviderType.AZURE))


def test_a_slug_used_while_the_key_was_checked_is_refused():
    with given(_setup(admin)) as context:

        def check_while_another_admin_adds_the_slug(*_):
            _connection(
                context, "azure-eu", "Other", ProviderType.AZURE, base_url=AZURE_BASE_URL, deleted_at=datetime.now(UTC)
            )
            return True

        context.injector.get(LlmProviderKeyChecker).check = Mock(side_effect=check_while_another_admin_adds_the_slug)

        response = _add_own(context, "azure")

        _assert_refused(context, response, 409, SLUG_TAKEN)
        [row] = _rows(context, "azure-eu")
        assert_that((row.name, row.api_key_encrypted, row.deleted_at is None), equal_to(("Other", None, False)))


@pytest.mark.parametrize("name", ["", "   ", "n" * 65])
def test_a_name_that_breaks_the_rules_is_refused(name):
    with given(_setup(admin, provider_answers(True))) as context:
        response = _add_own(context, "azure", name=name)

        _assert_refused(context, response, 422, NAME_FORMAT)
        context.check.assert_not_called()


@pytest.mark.parametrize(
    ("base_url", "detail"),
    [
        ("http://models.example.com/v1", NOT_PUBLIC),
        ("ftp://models.example.com/v1", NOT_PUBLIC),
        ("models.example.com/v1", NOT_PUBLIC),
        ("https:///v1", NOT_PUBLIC),
        ("https://models.example.com:99999/v1", NOT_PUBLIC),
        ("https://models.example.com:0/v1", NOT_PUBLIC),
        ("https://[2001:db8::1/v1", NOT_PUBLIC),
        ("https://models.example.com/v 1", NOT_PUBLIC),
        pytest.param(f"https://models.example.com/{'v' * 2048}", NOT_PUBLIC, id="too-long"),
        ("https://admin:hunter2@models.example.com/v1", URL_EXTRAS),
        ("https://models.example.com/v1?api-version=v1", URL_EXTRAS),
        ("https://models.example.com/v1?", URL_EXTRAS),
        ("https://models.example.com/v1#models", URL_EXTRAS),
    ],
)
def test_a_base_url_that_breaks_the_rules_is_refused_before_the_key_is_checked(base_url, detail):
    with given(_setup(admin, provider_answers(True))) as context:
        response = _add_own(context, "custom", base_url=base_url)

        _assert_refused(context, response, 422, detail)
        assert "hunter2" not in response.text
        context.check.assert_not_called()


def test_a_base_url_at_a_private_address_is_refused():
    with given(_setup(admin, provider_answers(BaseUrlNotPublic()))) as context:
        response = _add_own(context, "custom", base_url="https://internal.example.com/v1")

        _assert_refused(context, response, 422, NOT_PUBLIC)


def test_a_custom_server_that_is_not_an_api_is_refused():
    with given(_setup(admin, provider_answers(BaseUrlNotAnApi()))) as context:
        response = _add_own(context, "custom", base_url="https://www.example.com")

        _assert_refused(context, response, 422, NOT_AN_API)


@pytest.mark.parametrize(("answer", "status_code"), [(False, 422), (LlmProviderUnreachable(), 503)])
def test_an_azure_key_that_is_refused_or_unchecked_stores_nothing(answer, status_code):
    with given(_setup(admin, provider_answers(answer))) as context:
        response = _add_own(context, "azure")

        assert_that(response.status_code, equal_to(status_code))
        assert NEW_KEY not in response.text
        assert_that(_rows(context, "azure-eu"), equal_to([]))
        assert_that(_events(context), has_length(0))


CHANGED_EVENT = "platform.llm_provider.changed"
REPLACED_KEY = "sk-replacement-key-k9l0"
FABRIKAM_BASE_URL = "https://fabrikam.openai.azure.com"
NOT_FOUND = "That connection does not exist."
BASE_URL_NOT_TAKEN = "Only Azure and Custom connections take a base URL."
CHANGED_WHILE_CHECKING = "The connection changed while the key was checked. Nothing was saved."
OPENROUTER_ROUTE = {
    "model_name": "openrouter/*",
    "litellm_params": {
        "model": "openrouter/*",
        "api_key": REPLACED_KEY,
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


def anthropic_connected(context):
    context.connection = _connection(
        context, "anthropic", "Anthropic", ProviderType.ANTHROPIC, **_with_key(ANTHROPIC_KEY)
    )


def azure_connected(context):
    context.connection = _connection(
        context, "azure-eu", "Azure Europe", ProviderType.AZURE, base_url=AZURE_BASE_URL, **_with_key(AZURE_KEY)
    )


def _replace(context, slug: str, key: str = REPLACED_KEY, headers: dict | None = None, **fields):
    return context.client.put(f"{BASE}/{slug}/key", headers=headers or auth(context), json={"api_key": key, **fields})


def _changed_events(context) -> list[OutboxMessage]:
    with _session(context) as session:
        return list(session.exec(select(OutboxMessage).where(col(OutboxMessage.event_name) == CHANGED_EVENT)).all())


def _stored(context, slug: str) -> tuple[str | None, str | None]:
    [row] = _rows(context, slug)
    key = decrypt_token(row.api_key_encrypted, TEST_ENCRYPTION_KEY) if row.api_key_encrypted else None
    return key, row.base_url


def _assert_unchanged(context, response, slug: str, key: str, base_url: str | None) -> None:
    assert REPLACED_KEY not in response.text
    assert_that(_stored(context, slug), equal_to((key, base_url)))
    assert_that(_changed_events(context), has_length(0))


def test_an_organization_owner_cannot_replace_a_key():
    with given(_setup(provider_answers(True), anthropic_connected)) as context:
        response = _replace(context, "anthropic")

        assert_that(response.status_code, equal_to(403))
        context.check.assert_not_called()
        _assert_unchanged(context, response, "anthropic", ANTHROPIC_KEY, None)


def test_a_read_only_api_key_cannot_replace_a_key():
    with given(_setup(admin, provider_answers(True), anthropic_connected)) as context:
        created = context.client.post(
            "/api/v1/auth/me/api-keys", json={"name": "Automation", "access_mode": "READ_ONLY"}, headers=auth(context)
        )
        read_only = {"Authorization": f"Bearer {created.json()['token']}"}

        response = _replace(context, "anthropic", headers=read_only)

        assert_that(response.status_code, equal_to(403))
        context.check.assert_not_called()
        _assert_unchanged(context, response, "anthropic", ANTHROPIC_KEY, None)


def test_the_openrouter_key_is_routed_in_litellm_before_it_is_stored():
    with given(_setup(admin, env_key(""), openrouter_answers(True), provider_answers(True))) as context:
        _store_openrouter_key(context, OPENROUTER_KEY)
        stored_while_routing = []
        litellm = context.injector.get(LiteLLMClient)
        litellm.upsert_model_deployment.side_effect = lambda **_: stored_while_routing.append(
            _stored(context, "openrouter")[0]
        )

        response = _replace(context, "openrouter", key=f"  {REPLACED_KEY}  ")

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            response.json(),
            has_entries(slug="openrouter", has_api_key=True, api_key_last4="k9l0", updated_by=ADMIN_NAME),
        )
        context.check_key.assert_called_once_with(REPLACED_KEY)
        context.check.assert_not_called()
        litellm.upsert_model_deployment.assert_called_once_with(**OPENROUTER_ROUTE)
        assert_that(stored_while_routing, equal_to([OPENROUTER_KEY]))
        assert_that(_stored(context, "openrouter"), equal_to((REPLACED_KEY, None)))


def test_a_litellm_failure_leaves_the_openrouter_key_unchanged():
    with given(_setup(admin, openrouter_answers(True))) as context:
        _store_openrouter_key(context, OPENROUTER_KEY)
        context.injector.get(LiteLLMClient).upsert_model_deployment.side_effect = LiteLLMError("route not written")

        response = _replace(context, "openrouter")

        assert_that(response.status_code, equal_to(503))
        _assert_unchanged(context, response, "openrouter", OPENROUTER_KEY, None)


@pytest.mark.parametrize(("answer", "status_code"), [(False, 422), (OpenRouterError("unreachable"), 503)])
def test_an_openrouter_key_that_is_refused_or_unchecked_changes_nothing(answer, status_code):
    with given(_setup(admin, openrouter_answers(answer))) as context:
        _store_openrouter_key(context, OPENROUTER_KEY)

        response = _replace(context, "openrouter")

        assert_that(response.status_code, equal_to(status_code))
        context.injector.get(LiteLLMClient).upsert_model_deployment.assert_not_called()
        _assert_unchanged(context, response, "openrouter", OPENROUTER_KEY, None)


def test_a_known_provider_key_is_checked_and_stored_without_a_litellm_route():
    with given(_setup(admin, provider_answers(True), anthropic_connected)) as context:
        response = _replace(context, "anthropic")

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            response.json(),
            has_entries(slug="anthropic", base_url=None, api_key_last4="k9l0", updated_by=ADMIN_NAME),
        )
        context.check.assert_called_once_with(ProviderType.ANTHROPIC, REPLACED_KEY)
        context.injector.get(LiteLLMClient).upsert_model_deployment.assert_not_called()
        assert_that(_stored(context, "anthropic"), equal_to((REPLACED_KEY, None)))
        [row] = _rows(context, "anthropic")
        assert_that(row.updated_by, equal_to(context.admin_id))


def test_replacing_a_key_is_audited_with_no_part_of_either_key():
    with given(_setup(admin, provider_answers(True), anthropic_connected)) as context:
        _replace(context, "anthropic")

        events = _changed_events(context)
        assert_that(events, has_length(1))
        assert_that(
            events[0].payload,
            equal_to(
                {
                    "connection_id": str(context.connection.id),
                    "slug": "anthropic",
                    "replaced_existing": True,
                    "provider_type": "anthropic",
                    "previous_base_url": None,
                    "base_url": None,
                    "actor_display": ADMIN_NAME,
                    "subject_display": "Anthropic",
                }
            ),
        )
        assert_that(events[0].subject, has_entries(type="SYSTEM", id=str(context.connection.id)))
        for secret in (REPLACED_KEY, ANTHROPIC_KEY, "k9l0", "c3d4"):
            assert secret not in str(events[0].payload)


def test_a_first_key_for_a_known_provider_records_that_none_was_replaced():
    with given(_setup(admin, provider_answers(True))) as context:
        _connection(context, "deepseek", "DeepSeek", ProviderType.DEEPSEEK)

        response = _replace(context, "deepseek")

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(_changed_events(context)[0].payload, has_entries(replaced_existing=False))


def test_an_azure_key_is_checked_at_the_stored_base_url_when_none_is_given():
    with given(_setup(admin, provider_answers(True), azure_connected)) as context:
        response = _replace(context, "azure-eu")

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(response.json(), has_entries(base_url=AZURE_BASE_URL, api_key_last4="k9l0"))
        context.check.assert_called_once_with(ProviderType.AZURE, REPLACED_KEY, AZURE_BASE_URL)
        assert_that(_stored(context, "azure-eu"), equal_to((REPLACED_KEY, AZURE_BASE_URL)))
        assert_that(
            _changed_events(context)[0].payload,
            has_entries(provider_type="azure", previous_base_url=AZURE_BASE_URL, base_url=AZURE_BASE_URL),
        )


@pytest.mark.parametrize("provider_type", [ProviderType.AZURE, ProviderType.CUSTOM])
def test_a_new_base_url_is_checked_and_stored_with_the_new_key(provider_type):
    with given(_setup(admin, provider_answers(True))) as context:
        _connection(context, "eu-models", "EU models", provider_type, base_url=AZURE_BASE_URL, **_with_key(AZURE_KEY))

        response = _replace(context, "eu-models", base_url=f" {FABRIKAM_BASE_URL}/ ")

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(response.json(), has_entries(base_url=FABRIKAM_BASE_URL))
        context.check.assert_called_once_with(provider_type, REPLACED_KEY, FABRIKAM_BASE_URL)
        assert_that(_stored(context, "eu-models"), equal_to((REPLACED_KEY, FABRIKAM_BASE_URL)))
        assert_that(
            _changed_events(context)[0].payload,
            has_entries(
                provider_type=provider_type.value, previous_base_url=AZURE_BASE_URL, base_url=FABRIKAM_BASE_URL
            ),
        )


@pytest.mark.parametrize(("slug", "key"), [("anthropic", ANTHROPIC_KEY), ("openrouter", OPENROUTER_KEY)])
def test_a_base_url_for_a_provider_without_one_is_refused(slug, key):
    with given(_setup(admin, provider_answers(True), openrouter_answers(True), anthropic_connected)) as context:
        _store_openrouter_key(context, OPENROUTER_KEY)

        response = _replace(context, slug, base_url=AZURE_BASE_URL)

        assert_that(response.status_code, equal_to(422))
        assert_that(response.json(), equal_to({"detail": BASE_URL_NOT_TAKEN}))
        context.check.assert_not_called()
        context.check_key.assert_not_called()
        _assert_unchanged(context, response, slug, key, None)


@pytest.mark.parametrize(
    ("base_url", "detail"),
    [
        ("http://fabrikam.openai.azure.com", NOT_PUBLIC),
        ("https:///openai", NOT_PUBLIC),
        ("https://admin:hunter2@fabrikam.openai.azure.com", URL_EXTRAS),
        ("https://fabrikam.openai.azure.com?api-version=1", URL_EXTRAS),
    ],
)
def test_a_new_base_url_that_breaks_the_rules_is_refused_before_the_key_is_checked(base_url, detail):
    with given(_setup(admin, provider_answers(True), azure_connected)) as context:
        response = _replace(context, "azure-eu", base_url=base_url)

        assert_that(response.status_code, equal_to(422))
        assert_that(response.json(), equal_to({"detail": detail}))
        assert "hunter2" not in response.text
        context.check.assert_not_called()
        _assert_unchanged(context, response, "azure-eu", AZURE_KEY, AZURE_BASE_URL)


@pytest.mark.parametrize(
    ("answer", "status_code", "detail"),
    [
        (False, 422, "Azure Europe did not accept this key. Nothing was saved."),
        (LlmProviderUnreachable(), 503, "Azure Europe could not be reached to check the key. Nothing was saved."),
        (BaseUrlNotPublic(), 422, NOT_PUBLIC),
        (BaseUrlNotAnApi(), 422, NOT_AN_API),
    ],
)
def test_a_key_or_base_url_the_check_does_not_accept_changes_nothing(answer, status_code, detail):
    with given(_setup(admin, provider_answers(answer), azure_connected)) as context:
        response = _replace(context, "azure-eu", base_url=FABRIKAM_BASE_URL)

        assert_that(response.status_code, equal_to(status_code))
        assert_that(response.json(), equal_to({"detail": detail}))
        _assert_unchanged(context, response, "azure-eu", AZURE_KEY, AZURE_BASE_URL)


@pytest.mark.parametrize("deleted", [False, True])
def test_a_missing_connection_is_not_found(deleted):
    with given(_setup(admin, provider_answers(True))) as context:
        if deleted:
            _connection(context, "xai", "xAI", ProviderType.XAI, deleted_at=datetime.now(UTC))

        response = _replace(context, "xai")

        assert_that(response.status_code, equal_to(404))
        assert_that(response.json(), equal_to({"detail": NOT_FOUND}))
        context.check.assert_not_called()
        assert_that(_changed_events(context), has_length(0))


def _while_checking(context, change):
    def check(*_):
        with _session(context) as session:
            [row] = session.exec(select(LlmProviderConnection).where(LlmProviderConnection.slug == "azure-eu")).all()
            change(row)
            session.add(row)
            session.commit()
        return True

    context.injector.get(LlmProviderKeyChecker).check = Mock(side_effect=check)


def test_a_base_url_changed_while_the_key_was_checked_is_not_overwritten():
    with given(_setup(admin, azure_connected)) as context:
        _while_checking(context, lambda row: setattr(row, "base_url", FABRIKAM_BASE_URL))

        response = _replace(context, "azure-eu")

        assert_that(response.status_code, equal_to(409))
        assert_that(response.json(), equal_to({"detail": CHANGED_WHILE_CHECKING}))
        _assert_unchanged(context, response, "azure-eu", AZURE_KEY, FABRIKAM_BASE_URL)


def test_a_connection_deleted_while_the_key_was_checked_is_not_found():
    with given(_setup(admin, azure_connected)) as context:
        _while_checking(context, lambda row: setattr(row, "deleted_at", datetime.now(UTC)))

        response = _replace(context, "azure-eu")

        assert_that(response.status_code, equal_to(404))
        assert_that(response.json(), equal_to({"detail": NOT_FOUND}))
        assert_that(_changed_events(context), has_length(0))


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"api_key": "   "},
        {"api_key": "x" * 513},
        {"api_key": REPLACED_KEY, "unexpected": REPLACED_KEY},
        {"api_key": REPLACED_KEY, "slug": "other"},
    ],
)
def test_a_malformed_key_replacement_is_refused_without_echoing_it(body):
    with given(_setup(admin, provider_answers(True), anthropic_connected)) as context:
        response = context.client.put(f"{BASE}/anthropic/key", headers=auth(context), json=body)

        assert_that(response.status_code, equal_to(422))
        assert_that(response.json(), equal_to({"detail": "Invalid LLM provider key request"}))
        context.check.assert_not_called()
        _assert_unchanged(context, response, "anthropic", ANTHROPIC_KEY, None)

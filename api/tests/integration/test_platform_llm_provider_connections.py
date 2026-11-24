from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import Mock
from uuid import UUID, uuid5, uuid7

import pytest
from hamcrest import assert_that, equal_to, has_entries, has_length, is_not, none
from sqlmodel import Session, col, select

from api.core.config import Config
from api.domains.events.models import OutboxMessage
from api.domains.llm_providers.models import (
    OPENROUTER_CONNECTION_ID,
    LlmProviderConnection,
    LlmProviderModel,
    PriceSource,
    ProviderType,
)
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError, LiteLLMModelPrice
from api.infrastructure.llm_provider_catalogue.catalogue import (
    LlmProviderCatalogue,
    ProviderListBusy,
    ProviderListRefused,
    ProviderListUnreachable,
    ProviderListUnreadable,
)
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
ENV_KEY_LAST4 = "9z8y"
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
ROUTED_MODELS = ["gpt-4o", "gpt-4o-mini"]
ROUTE_PRICES = {
    "input_cost_per_token": 2.5e-06,
    "output_cost_per_token": 1e-05,
    "cache_read_input_token_cost": 1.25e-06,
    "cache_creation_input_token_cost": 0.0,
}
OTHER_ROUTE_ID = "agentbarn:model:0190a1b2-0000-7000-8000-000000000009:0190a1b2-0000-7000-8000-000000000010"
OTHER_ROUTE = {
    "model_name": "anthropic/claude-sonnet-4-5",
    "litellm_params": {"model": "anthropic/claude-sonnet-4-5", "api_key": ANTHROPIC_KEY},
    "model_info": {"id": OTHER_ROUTE_ID, "disable_background_health_check": True},
}
MODELS_NOT_STORED = "OpenRouter's models are not stored."
CUSTOM_KEY = "custom-stored-key-m1n2"
CUSTOM_BASE_URL = "https://lab.example.com/v1"
AZURE_DEPLOYMENT_FORMAT = "A deployment name must be 1 to 64 letters, digits or . _ - characters. Nothing was saved."
RUNS_MODEL_MISSING = "Say which model each deployment priced from LiteLLM runs. Nothing was saved."
RUNS_MODEL_NOT_TAKEN = "Only an Azure deployment priced from LiteLLM takes the model it runs. Nothing was saved."
EU_GPT4O_LISTED = ("0.00000275", "0.000011", "0.000001375", "0.00000275")
GPT4O_LISTED = ("0.0000025", "0.00001", "0.00000125", "0.0000025")
ANTHROPIC_HAS_NO_KEY = "Anthropic has no key."
ANTHROPIC_REFUSED_STORED_KEY = "Anthropic did not accept the stored key. Replace the key, then try again."
ANTHROPIC_LIST_UNREACHABLE = "Anthropic could not be reached to list its models."
ANTHROPIC_LIST_BUSY = "Anthropic is limiting requests. Try again in a minute."
ANTHROPIC_LIST_UNREADABLE = "Anthropic's model list could not be read."
PRICE_LIST_UNREADABLE = "The model proxy's price list could not be read."
MODELS_CHANGED_EVENT = "platform.llm_provider.models_changed"
SAVE_LISTED = ["claude-haiku-4-5", "claude-opus-4-1", "claude-sonnet-4-5"]
SONNET_LISTED = ("0.000003", "0.000015", "0.0000003", "0.00000375")
SONNET_STORED = ("0.0000025", "0.00001", "0.00000125", "0")
HAIKU_LISTED = ("0.000001", "0.000005", "0.0000001", "0.00000125")
TOO_MANY_MODELS = "A connection can have at most 50 models. Nothing was saved."
MODEL_REPEATED = "A model can be listed only once. Nothing was saved."
MODEL_ID_FORMAT = "A model id must be 1 to 200 letters, digits or . _ : / - characters. Nothing was saved."
PRICE_CHOICE = 'Each model takes "litellm", "stored" or its four prices. Nothing was saved.'
PRICE_FORMAT = "Each price must be a number below 1,000,000 with at most 18 decimal places. Nothing was saved."
PRICE_RANGE = "Input and output prices must be above 0, and cache prices 0 or more. Nothing was saved."
ANTHROPIC_NOT_LISTED = "Anthropic does not list one of these models. Nothing was saved."
NO_CHAT_PRICE = "LiteLLM has no chat price for one of these models; type its prices. Nothing was saved."
PRICES_NOT_STORED = "Only a stored model can keep its stored prices. Nothing was saved."
MODELS_CHANGED_WHILE_READING = "The connection changed while its models were read. Nothing was saved."
MODELS_NOT_ROUTED = "The model proxy could not be updated. Your models were not changed."
NO_PRICES = {
    "litellm_price_key": None,
    "input_cost_per_token": None,
    "output_cost_per_token": None,
    "cache_read_input_token_cost": None,
    "cache_creation_input_token_cost": None,
}
KEY_NOT_ROUTED = "The model proxy could not be updated. Your key was not changed."
ROUTES_NOT_REMOVED = "The model proxy could not be updated. Nothing was deleted."


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
                        "env_key_last4": None,
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


def test_only_openrouter_reports_the_environment_keys_last_four():
    with given(_setup(admin, env_key(ENV_KEY))) as context:
        _connection(context, "anthropic", "Anthropic", ProviderType.ANTHROPIC, **_with_key(ANTHROPIC_KEY))

        response = context.client.get(BASE, headers=auth(context))

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            [(item["slug"], item["env_key_last4"]) for item in response.json()],
            equal_to([("openrouter", ENV_KEY_LAST4), ("anthropic", None)]),
        )


def test_the_environment_keys_last_four_are_null_without_the_variable():
    with given(_setup(admin, env_key(""))) as context:
        response = context.client.get(BASE, headers=auth(context))

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(response.json()[0], has_entries(slug="openrouter", env_key_last4=None))


def test_only_env_key_last4_carries_the_end_of_the_environment_key():
    with given(_setup(admin, env_key(ENV_KEY))) as context:
        _store_openrouter_key(context, OPENROUTER_KEY, context.admin_id)
        _connection(context, "anthropic", "Anthropic", ProviderType.ANTHROPIC, **_with_key(ANTHROPIC_KEY))

        response = context.client.get(BASE, headers=auth(context))

        assert_that(response.status_code, equal_to(200), response.text)
        assert ENV_KEY not in response.text
        carriers = [
            (item["slug"], field)
            for item in response.json()
            for field, value in item.items()
            if isinstance(value, str) and ENV_KEY_LAST4 in value
        ]
        assert_that(carriers, equal_to([("openrouter", "env_key_last4")]))
        assert_that(response.text.count(ENV_KEY_LAST4), equal_to(1))


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


DELETED_EVENT = "platform.llm_provider.deleted"
OPENROUTER_FIXED = "OpenRouter can't be deleted."


def _delete(context, slug: str, headers: dict | None = None):
    return context.client.delete(f"{BASE}/{slug}", headers=headers or auth(context))


def _deleted_events(context) -> list[OutboxMessage]:
    with _session(context) as session:
        return list(session.exec(select(OutboxMessage).where(col(OutboxMessage.event_name) == DELETED_EVENT)).all())


def test_an_organization_owner_cannot_delete_a_connection():
    with given(_setup(anthropic_connected)) as context:
        response = _delete(context, "anthropic")

        assert_that(response.status_code, equal_to(403))
        assert_that(_stored(context, "anthropic"), equal_to((ANTHROPIC_KEY, None)))
        assert_that(_deleted_events(context), has_length(0))


def test_a_read_only_api_key_cannot_delete_a_connection():
    with given(_setup(admin, anthropic_connected)) as context:
        created = context.client.post(
            "/api/v1/auth/me/api-keys", json={"name": "Automation", "access_mode": "READ_ONLY"}, headers=auth(context)
        )
        read_only = {"Authorization": f"Bearer {created.json()['token']}"}

        response = _delete(context, "anthropic", headers=read_only)

        assert_that(response.status_code, equal_to(403))
        assert_that(_stored(context, "anthropic"), equal_to((ANTHROPIC_KEY, None)))
        assert_that(_deleted_events(context), has_length(0))


def test_a_platform_admin_deletes_a_connection_and_its_key_is_purged():
    with given(_setup(admin, azure_connected)) as context:
        response = _delete(context, "azure-eu")

        assert_that(response.status_code, equal_to(204), response.text)
        assert_that(response.content, equal_to(b""))
        [row] = _rows(context, "azure-eu")
        assert_that(row.deleted_at, is_not(none()))
        assert_that((row.api_key_encrypted, row.api_key_last4), equal_to((None, None)))
        assert_that(row.base_url, equal_to(AZURE_BASE_URL))
        listed = context.client.get(BASE, headers=auth(context)).json()
        assert_that([item["slug"] for item in listed], equal_to(["openrouter"]))


def test_deleting_a_connection_is_audited_with_no_part_of_its_key():
    with given(_setup(admin, azure_connected)) as context:
        _delete(context, "azure-eu")

        events = _deleted_events(context)
        assert_that(events, has_length(1))
        assert_that(
            events[0].payload,
            equal_to(
                {
                    "connection_id": str(context.connection.id),
                    "slug": "azure-eu",
                    "provider_type": "azure",
                    "base_url": AZURE_BASE_URL,
                    "key_purged": True,
                    "actor_display": ADMIN_NAME,
                    "subject_display": "Azure Europe",
                }
            ),
        )
        assert_that(events[0].subject, has_entries(type="SYSTEM", id=str(context.connection.id)))
        for secret in (AZURE_KEY, "e5f6"):
            assert secret not in str(events[0].payload)


def test_deleting_a_connection_without_a_key_records_that_none_was_purged():
    with given(_setup(admin)) as context:
        _connection(context, "deepseek", "DeepSeek", ProviderType.DEEPSEEK)

        response = _delete(context, "deepseek")

        assert_that(response.status_code, equal_to(204), response.text)
        assert_that(
            _deleted_events(context)[0].payload, has_entries(provider_type="deepseek", base_url=None, key_purged=False)
        )


def test_openrouter_cannot_be_deleted():
    with given(_setup(admin)) as context:
        _store_openrouter_key(context, OPENROUTER_KEY)

        response = _delete(context, "openrouter")

        assert_that(response.status_code, equal_to(409))
        assert_that(response.json(), equal_to({"detail": OPENROUTER_FIXED}))
        [row] = _rows(context, "openrouter")
        assert_that(row.deleted_at, none())
        assert_that(_stored(context, "openrouter"), equal_to((OPENROUTER_KEY, None)))
        assert_that(_deleted_events(context), has_length(0))


@pytest.mark.parametrize("deleted", [False, True])
def test_deleting_a_missing_connection_is_not_found(deleted):
    with given(_setup(admin)) as context:
        if deleted:
            _connection(context, "xai", "xAI", ProviderType.XAI, deleted_at=datetime.now(UTC))

        response = _delete(context, "xai")

        assert_that(response.status_code, equal_to(404))
        assert_that(response.json(), equal_to({"detail": NOT_FOUND}))
        assert_that(_deleted_events(context), has_length(0))


def test_a_deleted_azure_slug_cannot_be_used_again():
    with given(_setup(admin, provider_answers(True), azure_connected)) as context:
        _delete(context, "azure-eu")

        response = _add_own(context, "custom", slug="azure-eu", base_url="https://lab.example.com/v1")

        assert_that(response.status_code, equal_to(409))
        assert_that(response.json(), equal_to({"detail": SLUG_TAKEN}))
        context.check.assert_not_called()


def test_a_deleted_known_provider_can_be_added_again_with_a_new_key():
    with given(_setup(admin, provider_answers(True), anthropic_connected)) as context:
        _delete(context, "anthropic")

        response = _add(context, "anthropic")

        assert_that(response.status_code, equal_to(201), response.text)
        [row] = _rows(context, "anthropic")
        assert_that(row.id, equal_to(context.connection.id))
        assert_that(_stored(context, "anthropic"), equal_to((NEW_KEY, None)))


def test_a_deleted_connection_has_no_key_to_replace():
    with given(_setup(admin, provider_answers(True), anthropic_connected)) as context:
        _delete(context, "anthropic")

        response = _replace(context, "anthropic")

        assert_that(response.status_code, equal_to(404))
        context.check.assert_not_called()


def _model(context, connection: LlmProviderConnection, model_id: str, **fields) -> LlmProviderModel:
    row = LlmProviderModel(
        connection_id=connection.id,
        model_id=model_id,
        input_cost_per_token=fields.get("input_cost_per_token", Decimal("0.0000025")),
        output_cost_per_token=fields.get("output_cost_per_token", Decimal("0.00001")),
        cache_read_input_token_cost=fields.get("cache_read_input_token_cost", Decimal("0.00000125")),
        cache_creation_input_token_cost=fields.get("cache_creation_input_token_cost", Decimal(0)),
        price_source=fields.get("price_source", PriceSource.MANUAL),
        litellm_price_key=fields.get("litellm_price_key"),
    )
    with _session(context) as session:
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def _models(context, connection: LlmProviderConnection) -> list[LlmProviderModel]:
    with _session(context) as session:
        return list(session.exec(select(LlmProviderModel).where(LlmProviderModel.connection_id == connection.id)))


def _route_id(connection: LlmProviderConnection, model: LlmProviderModel) -> str:
    return f"agentbarn:model:{connection.id}:{model.id}"


def _other_routes() -> dict[str, dict]:
    return {"agentbarn:openrouter": OPENROUTER_ROUTE, OTHER_ROUTE_ID: OTHER_ROUTE}


def _azure_routes(context, key: str, base_url: str) -> dict[str, dict]:
    return {
        _route_id(context.connection, model): {
            "model_name": f"azure-eu/{model.model_id}",
            "litellm_params": {
                "model": f"azure/{model.model_id}",
                "api_base": base_url,
                "api_version": "v1",
                "api_key": key,
                **ROUTE_PRICES,
            },
            "model_info": {"id": _route_id(context.connection, model), "disable_background_health_check": True},
        }
        for model in context.models
    }


def azure_with_routed_models(context):
    routes: dict[str, dict] = {}
    litellm = context.injector.get(LiteLLMClient)
    litellm.list_model_deployments.side_effect = lambda id_prefix: [
        route for route_id, route in routes.items() if route_id.startswith(id_prefix)
    ]
    litellm.upsert_model_deployment.side_effect = lambda **route: routes.update({route["model_info"]["id"]: route})
    litellm.delete_model_deployment.side_effect = lambda model_id: routes.pop(model_id, None) is not None
    context.routes = routes
    azure_connected(context)
    context.models = [_model(context, context.connection, model_id) for model_id in ROUTED_MODELS]
    routes.update({**_other_routes(), **_azure_routes(context, AZURE_KEY, AZURE_BASE_URL)})


def test_a_new_key_is_routed_for_every_model_before_it_is_stored():
    with given(_setup(admin, provider_answers(True), azure_with_routed_models)) as context:
        stored_while_routing = []
        upsert = context.injector.get(LiteLLMClient).upsert_model_deployment
        write = upsert.side_effect

        def record(**route):
            stored_while_routing.append(_stored(context, "azure-eu")[0])
            write(**route)

        upsert.side_effect = record

        response = _replace(context, "azure-eu")

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(stored_while_routing, equal_to([AZURE_KEY, AZURE_KEY]))
        assert_that(
            context.routes, equal_to({**_other_routes(), **_azure_routes(context, REPLACED_KEY, AZURE_BASE_URL)})
        )
        assert_that(_stored(context, "azure-eu"), equal_to((REPLACED_KEY, AZURE_BASE_URL)))


def test_a_new_base_url_is_routed_for_every_model():
    with given(_setup(admin, provider_answers(True), azure_with_routed_models)) as context:
        response = _replace(context, "azure-eu", base_url=FABRIKAM_BASE_URL)

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            context.routes, equal_to({**_other_routes(), **_azure_routes(context, REPLACED_KEY, FABRIKAM_BASE_URL)})
        )
        assert_that(_stored(context, "azure-eu"), equal_to((REPLACED_KEY, FABRIKAM_BASE_URL)))


def test_a_route_failure_part_way_keeps_the_key_and_a_retry_leaves_one_route_per_model():
    with given(_setup(admin, provider_answers(True), azure_with_routed_models)) as context:
        leftover_id = f"agentbarn:model:{context.connection.id}:{uuid7()}"
        context.routes[leftover_id] = {**OTHER_ROUTE, "model_info": {"id": leftover_id}}
        upsert = context.injector.get(LiteLLMClient).upsert_model_deployment
        write = upsert.side_effect
        written = []

        def fail_second(**route):
            written.append(route)
            if len(written) == 2:
                raise LiteLLMError("route not written")
            write(**route)

        upsert.side_effect = fail_second

        failed = _replace(context, "azure-eu")

        assert_that(failed.status_code, equal_to(503))
        assert_that(failed.json(), equal_to({"detail": KEY_NOT_ROUTED}))
        _assert_unchanged(context, failed, "azure-eu", AZURE_KEY, AZURE_BASE_URL)

        upsert.side_effect = write
        retried = _replace(context, "azure-eu")

        assert_that(retried.status_code, equal_to(200), retried.text)
        assert_that(
            context.routes, equal_to({**_other_routes(), **_azure_routes(context, REPLACED_KEY, AZURE_BASE_URL)})
        )


def test_a_route_failure_part_way_puts_the_stored_key_and_base_url_back_on_every_route():
    with given(_setup(admin, provider_answers(True), azure_with_routed_models)) as context:
        upsert = context.injector.get(LiteLLMClient).upsert_model_deployment
        write = upsert.side_effect
        written = []

        def fail_second(**route):
            written.append(route)
            if len(written) == 2:
                raise LiteLLMError("route not written")
            write(**route)

        upsert.side_effect = fail_second

        failed = _replace(context, "azure-eu", base_url=FABRIKAM_BASE_URL)

        assert_that(failed.status_code, equal_to(503))
        assert_that(failed.json(), equal_to({"detail": KEY_NOT_ROUTED}))
        _assert_unchanged(context, failed, "azure-eu", AZURE_KEY, AZURE_BASE_URL)
        assert_that(context.routes, equal_to({**_other_routes(), **_azure_routes(context, AZURE_KEY, AZURE_BASE_URL)}))


def test_a_route_failure_that_also_fails_to_restore_still_stores_nothing():
    with given(_setup(admin, provider_answers(True), azure_with_routed_models)) as context:
        upsert = context.injector.get(LiteLLMClient).upsert_model_deployment
        write = upsert.side_effect
        written = []

        def fail_after_first(**route):
            written.append(route)
            if len(written) > 1:
                raise LiteLLMError("route not written")
            write(**route)

        upsert.side_effect = fail_after_first

        failed = _replace(context, "azure-eu")

        assert_that(failed.status_code, equal_to(503))
        assert_that(failed.json(), equal_to({"detail": KEY_NOT_ROUTED}))
        _assert_unchanged(context, failed, "azure-eu", AZURE_KEY, AZURE_BASE_URL)


def test_deleting_a_connection_removes_its_routes_before_its_models():
    with given(_setup(admin, azure_with_routed_models)) as context:
        models_while_removing = []
        delete = context.injector.get(LiteLLMClient).delete_model_deployment
        remove = delete.side_effect

        def record(model_id):
            models_while_removing.append(len(_models(context, context.connection)))
            return remove(model_id)

        delete.side_effect = record

        response = _delete(context, "azure-eu")

        assert_that(response.status_code, equal_to(204), response.text)
        assert_that(models_while_removing, equal_to([2, 2]))
        assert_that(context.routes, equal_to(_other_routes()))
        assert_that(_models(context, context.connection), has_length(0))
        [row] = _rows(context, "azure-eu")
        assert_that(row.deleted_at, is_not(none()))


@pytest.mark.parametrize("failing", ["list_model_deployments", "delete_model_deployment"])
def test_a_route_removal_failure_deletes_nothing(failing):
    with given(_setup(admin, azure_with_routed_models)) as context:
        getattr(context.injector.get(LiteLLMClient), failing).side_effect = LiteLLMError("proxy down")

        response = _delete(context, "azure-eu")

        assert_that(response.status_code, equal_to(503))
        assert_that(response.json(), equal_to({"detail": ROUTES_NOT_REMOVED}))
        [row] = _rows(context, "azure-eu")
        assert_that(row.deleted_at, none())
        assert_that(_stored(context, "azure-eu"), equal_to((AZURE_KEY, AZURE_BASE_URL)))
        assert_that(_models(context, context.connection), has_length(2))
        assert_that(_deleted_events(context), has_length(0))


def test_a_key_replaced_while_the_connection_is_deleted_routes_nothing():
    with given(_setup(admin, azure_with_routed_models)) as context:

        def delete_while_checking(*_):
            assert_that(_delete(context, "azure-eu").status_code, equal_to(204))
            return True

        context.injector.get(LlmProviderKeyChecker).check = Mock(side_effect=delete_while_checking)

        response = _replace(context, "azure-eu")

        assert_that(response.status_code, equal_to(404))
        assert_that(response.json(), equal_to({"detail": NOT_FOUND}))
        assert_that(context.routes, equal_to(_other_routes()))
        assert_that(_changed_events(context), has_length(0))


def _list_models(context, slug: str, headers: dict | None = None):
    return context.client.get(f"{BASE}/{slug}/models", headers=headers or auth(context))


def test_an_organization_owner_cannot_list_a_connections_models():
    with given(_setup(anthropic_connected)) as context:
        response = _list_models(context, "anthropic")

        assert_that(response.status_code, equal_to(403))


def test_listing_a_connections_models_needs_a_signed_in_user():
    with given(_setup(anthropic_connected)) as context:
        response = context.client.get(f"{BASE}/anthropic/models")

        assert_that(response.status_code, equal_to(401))


def test_a_read_only_api_key_of_a_platform_admin_can_list_a_connections_models():
    with given(_setup(admin, anthropic_connected)) as context:
        created = context.client.post(
            "/api/v1/auth/me/api-keys", json={"name": "Automation", "access_mode": "READ_ONLY"}, headers=auth(context)
        )
        read_only = {"Authorization": f"Bearer {created.json()['token']}"}

        response = _list_models(context, "anthropic", headers=read_only)

        assert_that(response.status_code, equal_to(200), response.text)


def test_a_connections_models_are_listed_by_id_with_exact_prices():
    with given(_setup(admin, anthropic_connected)) as context:
        _model(context, context.connection, "claude-sonnet-4-5")
        _model(
            context,
            context.connection,
            "claude-haiku-4-5",
            input_cost_per_token=Decimal("0.000001"),
            output_cost_per_token=Decimal("0.000005"),
            cache_read_input_token_cost=Decimal("0.0000001"),
            cache_creation_input_token_cost=Decimal("0.00000125"),
            price_source=PriceSource.LITELLM,
            litellm_price_key="claude-haiku-4-5",
        )
        other = _connection(context, "openai", "OpenAI", ProviderType.OPENAI, **_with_key(NEW_KEY))
        _model(context, other, "gpt-4o")

        response = _list_models(context, "anthropic")

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            response.json(),
            equal_to(
                [
                    {
                        "model_id": "claude-haiku-4-5",
                        "input_cost_per_token": "0.000001000000000000",
                        "output_cost_per_token": "0.000005000000000000",
                        "cache_read_input_token_cost": "0.000000100000000000",
                        "cache_creation_input_token_cost": "0.000001250000000000",
                        "price_source": "litellm",
                        "litellm_price_key": "claude-haiku-4-5",
                    },
                    {
                        "model_id": "claude-sonnet-4-5",
                        "input_cost_per_token": "0.000002500000000000",
                        "output_cost_per_token": "0.000010000000000000",
                        "cache_read_input_token_cost": "0.000001250000000000",
                        "cache_creation_input_token_cost": "0.000000000000000000",
                        "price_source": "manual",
                        "litellm_price_key": None,
                    },
                ]
            ),
        )


def test_a_connection_without_models_lists_none():
    with given(_setup(admin, azure_connected)) as context:
        response = _list_models(context, "azure-eu")

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(response.json(), equal_to([]))


@pytest.mark.parametrize("deleted", [False, True])
def test_the_models_of_a_missing_connection_are_not_found(deleted):
    with given(_setup(admin)) as context:
        if deleted:
            _connection(context, "xai", "xAI", ProviderType.XAI, deleted_at=datetime.now(UTC))

        response = _list_models(context, "xai")

        assert_that(response.status_code, equal_to(404))
        assert_that(response.json(), equal_to({"detail": NOT_FOUND}))


def test_openrouter_has_no_stored_models():
    with given(_setup(admin)) as context:
        response = _list_models(context, "openrouter")

        assert_that(response.status_code, equal_to(409))
        assert_that(response.json(), equal_to({"detail": MODELS_NOT_STORED}))


def provider_lists(answer: list[str] | Exception):
    def step(context):
        listing = Mock(side_effect=answer) if isinstance(answer, Exception) else Mock(return_value=answer)
        context.injector.get(LlmProviderCatalogue).list_models = listing
        context.list_models = listing

    return step


def litellm_prices(*prices: LiteLLMModelPrice):
    def step(context):
        context.injector.get(LiteLLMClient).get_model_prices.return_value = {price.key: price for price in prices}

    return step


def _price(
    key: str,
    input_price: str,
    output_price: str,
    cache_read: str | None = None,
    cache_creation: str | None = None,
    mode: str | None = "chat",
) -> LiteLLMModelPrice:
    return LiteLLMModelPrice(
        key=key,
        mode=mode,
        input_cost_per_token=Decimal(input_price),
        output_cost_per_token=Decimal(output_price),
        cache_read_input_token_cost=None if cache_read is None else Decimal(cache_read),
        cache_creation_input_token_cost=None if cache_creation is None else Decimal(cache_creation),
    )


def _catalogue(context, slug: str, headers: dict | None = None):
    return context.client.get(f"{BASE}/{slug}/model-catalogue", headers=headers or auth(context))


def test_an_organization_owner_cannot_read_a_connections_model_catalogue():
    with given(_setup(anthropic_connected, provider_lists([]), litellm_prices())) as context:
        response = _catalogue(context, "anthropic")

        assert_that(response.status_code, equal_to(403))
        context.list_models.assert_not_called()


def test_reading_a_connections_model_catalogue_needs_a_signed_in_user():
    with given(_setup(anthropic_connected, provider_lists([]), litellm_prices())) as context:
        response = context.client.get(f"{BASE}/anthropic/model-catalogue")

        assert_that(response.status_code, equal_to(401))
        context.list_models.assert_not_called()


def test_a_read_only_api_key_of_a_platform_admin_can_read_a_connections_model_catalogue():
    with given(_setup(admin, anthropic_connected, provider_lists([]), litellm_prices())) as context:
        created = context.client.post(
            "/api/v1/auth/me/api-keys", json={"name": "Automation", "access_mode": "READ_ONLY"}, headers=auth(context)
        )
        read_only = {"Authorization": f"Bearer {created.json()['token']}"}

        response = _catalogue(context, "anthropic", headers=read_only)

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(response.json(), equal_to([]))


def test_the_catalogue_lists_the_providers_models_with_litellms_chat_prices():
    listed = ["claude-3-embed", "claude-haiku-4-5", "claude-opus-4-1", "claude-sonnet-4-5", "claude-unknown"]
    prices = litellm_prices(
        _price("claude-3-embed", "0.0000001", "0.0000001", mode="embedding"),
        _price("claude-haiku-4-5", "0.000001", "0.000005", "0.0000001", "0.00000125"),
        _price("claude-opus-4-1", "0.0000150000000000005", "0.000075"),
        _price("claude-sonnet-4-5", "0.000003", "0.000015", "0.0000003", "0.00000375"),
        _price("gpt-4o", "0.0000025", "0.00001"),
    )
    with given(_setup(admin, anthropic_connected, provider_lists(listed), prices)) as context:
        _model(context, context.connection, "claude-3-embed")
        _model(
            context,
            context.connection,
            "claude-haiku-4-5",
            input_cost_per_token=Decimal("0.000001"),
            output_cost_per_token=Decimal("0.000005"),
            cache_read_input_token_cost=Decimal("0.0000001"),
            cache_creation_input_token_cost=Decimal("0.00000125"),
            price_source=PriceSource.LITELLM,
            litellm_price_key="claude-haiku-4-5",
        )
        _model(
            context,
            context.connection,
            "claude-opus-4-1",
            input_cost_per_token=Decimal("0.000015000000000001"),
            output_cost_per_token=Decimal("0.000075"),
            cache_read_input_token_cost=Decimal("0.000015000000000001"),
            cache_creation_input_token_cost=Decimal("0.000015000000000001"),
        )
        _model(context, context.connection, "claude-sonnet-4-5")
        other = _connection(context, "openai", "OpenAI", ProviderType.OPENAI, **_with_key(NEW_KEY))
        _model(context, other, "claude-unknown")

        response = _catalogue(context, "anthropic")

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            response.json(),
            equal_to(
                [
                    {"model_id": "claude-3-embed", "stored": True, **NO_PRICES, "prices_differ": False},
                    {
                        "model_id": "claude-haiku-4-5",
                        "stored": True,
                        "litellm_price_key": "claude-haiku-4-5",
                        "input_cost_per_token": "0.000001000000000000",
                        "output_cost_per_token": "0.000005000000000000",
                        "cache_read_input_token_cost": "0.000000100000000000",
                        "cache_creation_input_token_cost": "0.000001250000000000",
                        "prices_differ": False,
                    },
                    {
                        "model_id": "claude-opus-4-1",
                        "stored": True,
                        "litellm_price_key": "claude-opus-4-1",
                        "input_cost_per_token": "0.000015000000000001",
                        "output_cost_per_token": "0.000075000000000000",
                        "cache_read_input_token_cost": "0.000015000000000001",
                        "cache_creation_input_token_cost": "0.000015000000000001",
                        "prices_differ": False,
                    },
                    {
                        "model_id": "claude-sonnet-4-5",
                        "stored": True,
                        "litellm_price_key": "claude-sonnet-4-5",
                        "input_cost_per_token": "0.000003000000000000",
                        "output_cost_per_token": "0.000015000000000000",
                        "cache_read_input_token_cost": "0.000000300000000000",
                        "cache_creation_input_token_cost": "0.000003750000000000",
                        "prices_differ": True,
                    },
                    {"model_id": "claude-unknown", "stored": False, **NO_PRICES, "prices_differ": False},
                ]
            ),
        )
        context.list_models.assert_called_once_with(ProviderType.ANTHROPIC, ANTHROPIC_KEY)


@pytest.mark.parametrize(
    "field",
    [
        "input_cost_per_token",
        "output_cost_per_token",
        "cache_read_input_token_cost",
        "cache_creation_input_token_cost",
    ],
)
def test_a_stored_model_differing_in_any_one_price_is_marked(field):
    stored = {
        "input_cost_per_token": Decimal("0.000003"),
        "output_cost_per_token": Decimal("0.000015"),
        "cache_read_input_token_cost": Decimal("0.0000003"),
        "cache_creation_input_token_cost": Decimal("0.00000375"),
    }
    stored[field] += Decimal("0.000000000000000001")
    prices = litellm_prices(_price("claude-sonnet-4-5", "0.000003", "0.000015", "0.0000003", "0.00000375"))
    with given(_setup(admin, anthropic_connected, provider_lists(["claude-sonnet-4-5"]), prices)) as context:
        _model(context, context.connection, "claude-sonnet-4-5", **stored)

        response = _catalogue(context, "anthropic")

        assert_that(response.status_code, equal_to(200), response.text)
        [entry] = response.json()
        assert_that(entry, has_entries(stored=True, prices_differ=True))


def test_a_custom_connection_is_listed_at_its_base_url_without_prices():
    prices = litellm_prices(_price("llama-3", "0.000001", "0.000002"), _price("openai/llama-3", "0.000001", "0.000002"))
    with given(_setup(admin, provider_lists(["llama-3"]), prices)) as context:
        _connection(
            context,
            "custom-lab",
            "Aardvark lab",
            ProviderType.CUSTOM,
            base_url=CUSTOM_BASE_URL,
            **_with_key(CUSTOM_KEY),
        )

        response = _catalogue(context, "custom-lab")

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            response.json(), equal_to([{"model_id": "llama-3", "stored": False, **NO_PRICES, "prices_differ": False}])
        )
        context.list_models.assert_called_once_with(ProviderType.CUSTOM, CUSTOM_KEY, CUSTOM_BASE_URL)


@pytest.mark.parametrize(
    ("failure", "status_code", "detail"),
    [
        (ProviderListRefused(), 409, ANTHROPIC_REFUSED_STORED_KEY),
        (ProviderListUnreachable(), 503, ANTHROPIC_LIST_UNREACHABLE),
        (ProviderListBusy(), 503, ANTHROPIC_LIST_BUSY),
        (ProviderListUnreadable(), 502, ANTHROPIC_LIST_UNREADABLE),
    ],
)
def test_a_provider_list_that_fails_gives_its_status(failure, status_code, detail):
    with given(_setup(admin, anthropic_connected, provider_lists(failure), litellm_prices())) as context:
        response = _catalogue(context, "anthropic")

        assert_that(response.status_code, equal_to(status_code))
        assert_that(response.json(), equal_to({"detail": detail}))


def test_a_price_list_litellm_cannot_give_is_unavailable():
    with given(_setup(admin, anthropic_connected, provider_lists(["claude-sonnet-4-5"]))) as context:
        context.injector.get(LiteLLMClient).get_model_prices.side_effect = LiteLLMError("proxy down")

        response = _catalogue(context, "anthropic")

        assert_that(response.status_code, equal_to(503))
        assert_that(response.json(), equal_to({"detail": PRICE_LIST_UNREADABLE}))


@pytest.mark.parametrize("deleted", [False, True])
def test_the_catalogue_of_a_missing_connection_is_not_found(deleted):
    with given(_setup(admin, provider_lists([]), litellm_prices())) as context:
        if deleted:
            _connection(context, "xai", "xAI", ProviderType.XAI, deleted_at=datetime.now(UTC))

        response = _catalogue(context, "xai")

        assert_that(response.status_code, equal_to(404))
        assert_that(response.json(), equal_to({"detail": NOT_FOUND}))
        context.list_models.assert_not_called()


@pytest.mark.parametrize(
    ("slug", "detail"),
    [("openrouter", MODELS_NOT_STORED), ("anthropic", ANTHROPIC_HAS_NO_KEY)],
)
def test_a_connection_whose_models_are_not_listed_is_refused_before_the_provider_is_asked(slug, detail):
    with given(_setup(admin, azure_connected, provider_lists([]), litellm_prices())) as context:
        _connection(context, "anthropic", "Anthropic", ProviderType.ANTHROPIC)

        response = _catalogue(context, slug)

        assert_that(response.status_code, equal_to(409))
        assert_that(response.json(), equal_to({"detail": detail}))
        context.list_models.assert_not_called()


def _claude_prices():
    return litellm_prices(
        _price("claude-haiku-4-5", "0.000001", "0.000005", "0.0000001", "0.00000125"),
        _price("claude-opus-4-1", "0.000015", "0.000075"),
        _price("claude-sonnet-4-5", "0.000003", "0.000015", "0.0000003", "0.00000375"),
        _price("claude-3-embed", "0.0000001", "0.0000001", mode="embedding"),
    )


def _without_key(route: dict) -> dict:
    return {**route, "litellm_params": {k: v for k, v in route["litellm_params"].items() if k != "api_key"}}


def _route_store(context) -> None:
    routes: dict[str, dict] = dict(_other_routes())
    litellm = context.injector.get(LiteLLMClient)
    litellm.list_model_deployments.side_effect = lambda id_prefix: [
        _without_key(route) for route_id, route in routes.items() if route_id.startswith(id_prefix)
    ]
    litellm.upsert_model_deployment.side_effect = lambda **route: routes.update({route["model_info"]["id"]: route})
    litellm.delete_model_deployment.side_effect = lambda model_id: routes.pop(model_id, None) is not None
    context.routes = routes


def anthropic_with_routes(context):
    _route_store(context)
    anthropic_connected(context)


def azure_with_routes(context):
    _route_store(context)
    azure_connected(context)


def _claude_route(context, model_id: str, row_id: UUID, prices: tuple[str, str, str, str]) -> dict[str, dict]:
    route_id = f"agentbarn:model:{context.connection.id}:{row_id}"
    return {
        route_id: {
            "model_name": f"anthropic/{model_id}",
            "litellm_params": {
                "model": f"anthropic/{model_id}",
                "api_key": ANTHROPIC_KEY,
                "input_cost_per_token": float(prices[0]),
                "output_cost_per_token": float(prices[1]),
                "cache_read_input_token_cost": float(prices[2]),
                "cache_creation_input_token_cost": float(prices[3]),
            },
            "model_info": {"id": route_id, "disable_background_health_check": True},
        }
    }


def _stored_claude(context, model_id: str, prices: tuple[str, str, str, str], **fields) -> LlmProviderModel:
    model = _model(
        context,
        context.connection,
        model_id,
        input_cost_per_token=Decimal(prices[0]),
        output_cost_per_token=Decimal(prices[1]),
        cache_read_input_token_cost=Decimal(prices[2]),
        cache_creation_input_token_cost=Decimal(prices[3]),
        **fields,
    )
    context.routes.update(_claude_route(context, model_id, model.id, prices))
    return model


def _typed(input_price: str, output_price: str, cache_read: str, cache_creation: str) -> dict:
    return {
        "input_cost_per_token": input_price,
        "output_cost_per_token": output_price,
        "cache_read_input_token_cost": cache_read,
        "cache_creation_input_token_cost": cache_creation,
    }


def _save(context, slug: str, models: list[dict], headers: dict | None = None):
    return context.client.put(f"{BASE}/{slug}/models", headers=headers or auth(context), json={"models": models})


def _models_changed_events(context) -> list[OutboxMessage]:
    with _session(context) as session:
        return list(
            session.exec(select(OutboxMessage).where(col(OutboxMessage.event_name) == MODELS_CHANGED_EVENT)).all()
        )


def _stored_prices(context) -> dict[str, tuple]:
    return {
        model.model_id: (
            model.input_cost_per_token,
            model.output_cost_per_token,
            model.cache_read_input_token_cost,
            model.cache_creation_input_token_cost,
            model.price_source,
            model.litellm_price_key,
        )
        for model in _models(context, context.connection)
    }


def _assert_nothing_saved(context, before: dict[str, tuple], routes_before: dict[str, dict]) -> None:
    assert_that(_stored_prices(context), equal_to(before))
    assert_that(context.routes, equal_to(routes_before))
    assert_that(_models_changed_events(context), has_length(0))


def test_an_organization_owner_cannot_save_a_connections_models():
    with given(_setup(anthropic_with_routes, provider_lists(SAVE_LISTED), _claude_prices())) as context:
        response = _save(context, "anthropic", [{"model_id": "claude-sonnet-4-5", "price": "litellm"}])

        assert_that(response.status_code, equal_to(403))
        context.list_models.assert_not_called()
        _assert_nothing_saved(context, {}, _other_routes())


def test_a_read_only_api_key_cannot_save_a_connections_models():
    with given(_setup(admin, anthropic_with_routes, provider_lists(SAVE_LISTED), _claude_prices())) as context:
        created = context.client.post(
            "/api/v1/auth/me/api-keys", json={"name": "Automation", "access_mode": "READ_ONLY"}, headers=auth(context)
        )
        read_only = {"Authorization": f"Bearer {created.json()['token']}"}

        response = _save(context, "anthropic", [{"model_id": "claude-sonnet-4-5", "price": "litellm"}], read_only)

        assert_that(response.status_code, equal_to(403))
        context.list_models.assert_not_called()
        _assert_nothing_saved(context, {}, _other_routes())


def test_saved_models_are_stored_routed_and_audited():
    with given(_setup(admin, anthropic_with_routes, provider_lists(SAVE_LISTED), _claude_prices())) as context:
        response = _save(
            context,
            "anthropic",
            [
                {"model_id": "claude-sonnet-4-5", "price": "litellm"},
                {"model_id": "claude-opus-4-1", "price": "litellm"},
                {"model_id": "claude-haiku-4-5", "price": _typed("0.0000012", "0.000006", "0.00000012", "0")},
            ],
        )

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            response.json(),
            equal_to(
                [
                    {
                        "model_id": "claude-haiku-4-5",
                        "input_cost_per_token": "0.000001200000000000",
                        "output_cost_per_token": "0.000006000000000000",
                        "cache_read_input_token_cost": "0.000000120000000000",
                        "cache_creation_input_token_cost": "0.000000000000000000",
                        "price_source": "manual",
                        "litellm_price_key": None,
                    },
                    {
                        "model_id": "claude-opus-4-1",
                        "input_cost_per_token": "0.000015000000000000",
                        "output_cost_per_token": "0.000075000000000000",
                        "cache_read_input_token_cost": "0.000015000000000000",
                        "cache_creation_input_token_cost": "0.000015000000000000",
                        "price_source": "litellm",
                        "litellm_price_key": "claude-opus-4-1",
                    },
                    {
                        "model_id": "claude-sonnet-4-5",
                        "input_cost_per_token": "0.000003000000000000",
                        "output_cost_per_token": "0.000015000000000000",
                        "cache_read_input_token_cost": "0.000000300000000000",
                        "cache_creation_input_token_cost": "0.000003750000000000",
                        "price_source": "litellm",
                        "litellm_price_key": "claude-sonnet-4-5",
                    },
                ]
            ),
        )
        connection_id = context.connection.id
        assert_that(
            context.routes,
            equal_to(
                {
                    **_other_routes(),
                    **_claude_route(
                        context,
                        "claude-haiku-4-5",
                        uuid5(connection_id, "claude-haiku-4-5"),
                        ("0.0000012", "0.000006", "0.00000012", "0"),
                    ),
                    **_claude_route(
                        context,
                        "claude-opus-4-1",
                        uuid5(connection_id, "claude-opus-4-1"),
                        ("0.000015", "0.000075", "0.000015", "0.000015"),
                    ),
                    **_claude_route(
                        context,
                        "claude-sonnet-4-5",
                        uuid5(connection_id, "claude-sonnet-4-5"),
                        ("0.000003", "0.000015", "0.0000003", "0.00000375"),
                    ),
                }
            ),
        )
        [event] = _models_changed_events(context)
        assert_that(
            event.payload,
            equal_to(
                {
                    "connection_id": str(connection_id),
                    "slug": "anthropic",
                    "provider_type": "anthropic",
                    "added_count": 3,
                    "removed_count": 0,
                    "repriced_count": 0,
                    "added_model_ids": ["claude-haiku-4-5", "claude-opus-4-1", "claude-sonnet-4-5"],
                    "removed_model_ids": [],
                    "repriced_model_ids": [],
                    "model_ids_truncated": False,
                    "actor_display": ADMIN_NAME,
                    "subject_display": "Anthropic",
                }
            ),
        )
        assert_that(event.subject, has_entries(type="SYSTEM", id=str(connection_id)))
        assert ANTHROPIC_KEY not in str(event.payload)
        context.list_models.assert_called_once_with(ProviderType.ANTHROPIC, ANTHROPIC_KEY)


def test_a_model_left_out_is_removed_with_its_route():
    with given(_setup(admin, anthropic_with_routes, provider_lists(SAVE_LISTED), _claude_prices())) as context:
        _stored_claude(context, "claude-sonnet-4-5", SONNET_STORED)
        haiku = _stored_claude(context, "claude-haiku-4-5", HAIKU_LISTED)
        routes_before = dict(context.routes)
        upsert = context.injector.get(LiteLLMClient).upsert_model_deployment

        response = _save(context, "anthropic", [{"model_id": "claude-sonnet-4-5", "price": "stored"}])

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that([model["model_id"] for model in response.json()], equal_to(["claude-sonnet-4-5"]))
        assert_that(list(_stored_prices(context)), equal_to(["claude-sonnet-4-5"]))
        haiku_route = _route_id(context.connection, haiku)
        assert_that(context.routes, equal_to({k: v for k, v in routes_before.items() if k != haiku_route}))
        upsert.assert_not_called()
        context.injector.get(LiteLLMClient).get_model_prices.assert_not_called()
        [event] = _models_changed_events(context)
        assert_that(
            event.payload,
            has_entries(
                added_count=0,
                removed_count=1,
                repriced_count=0,
                added_model_ids=[],
                removed_model_ids=["claude-haiku-4-5"],
                repriced_model_ids=[],
                model_ids_truncated=False,
            ),
        )


def test_only_the_routes_that_differ_are_written():
    with given(_setup(admin, anthropic_with_routes, provider_lists(SAVE_LISTED), _claude_prices())) as context:
        sonnet = _stored_claude(context, "claude-sonnet-4-5", SONNET_STORED)
        _stored_claude(context, "claude-haiku-4-5", HAIKU_LISTED)
        upsert = context.injector.get(LiteLLMClient).upsert_model_deployment

        response = _save(
            context,
            "anthropic",
            [
                {"model_id": "claude-sonnet-4-5", "price": "litellm"},
                {"model_id": "claude-haiku-4-5", "price": "stored"},
            ],
        )

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(upsert.call_count, equal_to(1))
        assert_that(upsert.call_args.kwargs["model_info"]["id"], equal_to(_route_id(context.connection, sonnet)))
        assert_that(
            context.routes[_route_id(context.connection, sonnet)],
            equal_to(
                _claude_route(context, "claude-sonnet-4-5", sonnet.id, SONNET_LISTED)[
                    _route_id(context.connection, sonnet)
                ]
            ),
        )
        assert_that(
            _stored_prices(context)["claude-sonnet-4-5"],
            equal_to((*(Decimal(price) for price in SONNET_LISTED), PriceSource.LITELLM, "claude-sonnet-4-5")),
        )
        [event] = _models_changed_events(context)
        assert_that(
            event.payload,
            has_entries(added_count=0, removed_count=0, repriced_count=1, repriced_model_ids=["claude-sonnet-4-5"]),
        )


def test_a_price_source_change_alone_is_audited_without_writing_the_route():
    with given(_setup(admin, anthropic_with_routes, provider_lists(SAVE_LISTED), _claude_prices())) as context:
        _stored_claude(context, "claude-sonnet-4-5", SONNET_LISTED)
        upsert = context.injector.get(LiteLLMClient).upsert_model_deployment

        response = _save(context, "anthropic", [{"model_id": "claude-sonnet-4-5", "price": "litellm"}])

        assert_that(response.status_code, equal_to(200), response.text)
        upsert.assert_not_called()
        assert_that(
            _stored_prices(context)["claude-sonnet-4-5"][4:], equal_to((PriceSource.LITELLM, "claude-sonnet-4-5"))
        )
        [event] = _models_changed_events(context)
        assert_that(event.payload, has_entries(repriced_count=1, repriced_model_ids=["claude-sonnet-4-5"]))


def test_a_save_that_changes_nothing_records_nothing():
    with given(_setup(admin, anthropic_with_routes, provider_lists(SAVE_LISTED), _claude_prices())) as context:
        _stored_claude(context, "claude-sonnet-4-5", SONNET_STORED)
        before, routes_before = _stored_prices(context), dict(context.routes)
        litellm = context.injector.get(LiteLLMClient)

        response = _save(context, "anthropic", [{"model_id": "claude-sonnet-4-5", "price": "stored"}])

        assert_that(response.status_code, equal_to(200), response.text)
        litellm.upsert_model_deployment.assert_not_called()
        litellm.delete_model_deployment.assert_not_called()
        _assert_nothing_saved(context, before, routes_before)


def test_a_save_that_changes_nothing_still_restores_a_missing_route():
    with given(_setup(admin, anthropic_with_routes, provider_lists(SAVE_LISTED), _claude_prices())) as context:
        sonnet = _stored_claude(context, "claude-sonnet-4-5", SONNET_STORED)
        route_id = _route_id(context.connection, sonnet)
        expected = dict(context.routes)
        del context.routes[route_id]

        response = _save(context, "anthropic", [{"model_id": "claude-sonnet-4-5", "price": "stored"}])

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(context.routes, equal_to(expected))
        assert_that(_models_changed_events(context), has_length(0))


def test_the_audited_ids_are_cut_to_twenty_each():
    model_ids = [f"model-{number:02d}" for number in range(21)]
    with given(_setup(admin, anthropic_with_routes, provider_lists(model_ids), litellm_prices())) as context:
        response = _save(
            context,
            "anthropic",
            [{"model_id": model_id, "price": _typed("0.000001", "0.000002", "0", "0")} for model_id in model_ids],
        )

        assert_that(response.status_code, equal_to(200), response.text)
        [event] = _models_changed_events(context)
        assert_that(
            event.payload,
            has_entries(added_count=21, added_model_ids=model_ids[:20], model_ids_truncated=True),
        )


def _many(count: int) -> list[dict]:
    return [
        {"model_id": f"model-{number:02d}", "price": _typed("0.000001", "0.000002", "0", "0")}
        for number in range(count)
    ]


@pytest.mark.parametrize(
    ("models", "detail"),
    [
        (_many(51), TOO_MANY_MODELS),
        ([{"model_id": "claude-sonnet-4-5", "price": "litellm"}] * 2, MODEL_REPEATED),
        ([{"model_id": "claude sonnet", "price": "litellm"}], MODEL_ID_FORMAT),
        ([{"model_id": "", "price": "litellm"}], MODEL_ID_FORMAT),
        ([{"model_id": "m" * 201, "price": "litellm"}], MODEL_ID_FORMAT),
        ([{"model_id": "claude-sonnet-4-5", "price": "cheapest"}], PRICE_CHOICE),
        ([{"model_id": "claude-sonnet-4-5", "price": {"input_cost_per_token": "0.000001"}}], PRICE_FORMAT),
        ([{"model_id": "claude-sonnet-4-5", "price": _typed("abc", "0.000002", "0", "0")}], PRICE_FORMAT),
        ([{"model_id": "claude-sonnet-4-5", "price": _typed("NaN", "0.000002", "0", "0")}], PRICE_FORMAT),
        (
            [{"model_id": "claude-sonnet-4-5", "price": _typed("0.0000010000000000001", "0.000002", "0", "0")}],
            PRICE_FORMAT,
        ),
        ([{"model_id": "claude-sonnet-4-5", "price": _typed("1000000", "0.000002", "0", "0")}], PRICE_FORMAT),
        ([{"model_id": "claude-sonnet-4-5", "price": _typed("0", "0.000002", "0", "0")}], PRICE_RANGE),
        ([{"model_id": "claude-sonnet-4-5", "price": _typed("0.000001", "-0.000002", "0", "0")}], PRICE_RANGE),
        ([{"model_id": "claude-sonnet-4-5", "price": _typed("0.000001", "0.000002", "-0.1", "0")}], PRICE_RANGE),
        ([{"model_id": "claude-sonnet-4-5", "price": _typed("0.000001", "0.000002", "0", "-0.1")}], PRICE_RANGE),
    ],
)
def test_a_body_that_breaks_a_rule_is_refused_before_the_provider_is_asked(models, detail):
    with given(_setup(admin, anthropic_with_routes, provider_lists(SAVE_LISTED), _claude_prices())) as context:
        _stored_claude(context, "claude-haiku-4-5", HAIKU_LISTED)
        before, routes_before = _stored_prices(context), dict(context.routes)

        response = _save(context, "anthropic", models)

        assert_that(response.status_code, equal_to(422))
        assert_that(response.json(), equal_to({"detail": detail}))
        context.list_models.assert_not_called()
        _assert_nothing_saved(context, before, routes_before)


@pytest.mark.parametrize(
    ("models", "detail"),
    [
        ([{"model_id": "claude-unlisted", "price": _typed("0.000001", "0.000002", "0", "0")}], ANTHROPIC_NOT_LISTED),
        ([{"model_id": "claude-unpriced", "price": "litellm"}], NO_CHAT_PRICE),
        ([{"model_id": "claude-3-embed", "price": "litellm"}], NO_CHAT_PRICE),
        ([{"model_id": "claude-sonnet-4-5", "price": "stored"}], PRICES_NOT_STORED),
    ],
)
def test_a_model_the_provider_or_litellm_cannot_back_is_refused(models, detail):
    listed = [*SAVE_LISTED, "claude-3-embed", "claude-unpriced"]
    with given(_setup(admin, anthropic_with_routes, provider_lists(listed), _claude_prices())) as context:
        _stored_claude(context, "claude-haiku-4-5", HAIKU_LISTED)
        before, routes_before = _stored_prices(context), dict(context.routes)

        response = _save(context, "anthropic", models)

        assert_that(response.status_code, equal_to(422))
        assert_that(response.json(), equal_to({"detail": detail}))
        _assert_nothing_saved(context, before, routes_before)


@pytest.mark.parametrize(
    ("failure", "status_code", "detail"),
    [
        (ProviderListRefused(), 409, ANTHROPIC_REFUSED_STORED_KEY),
        (ProviderListUnreachable(), 503, ANTHROPIC_LIST_UNREACHABLE),
        (ProviderListBusy(), 503, ANTHROPIC_LIST_BUSY),
        (ProviderListUnreadable(), 502, ANTHROPIC_LIST_UNREADABLE),
    ],
)
def test_a_provider_list_that_fails_saves_nothing(failure, status_code, detail):
    with given(_setup(admin, anthropic_with_routes, provider_lists(failure), _claude_prices())) as context:
        response = _save(context, "anthropic", [{"model_id": "claude-sonnet-4-5", "price": "litellm"}])

        assert_that(response.status_code, equal_to(status_code))
        assert_that(response.json(), equal_to({"detail": detail}))
        _assert_nothing_saved(context, {}, _other_routes())


def test_a_price_list_litellm_cannot_give_saves_nothing():
    with given(_setup(admin, anthropic_with_routes, provider_lists(SAVE_LISTED))) as context:
        context.injector.get(LiteLLMClient).get_model_prices.side_effect = LiteLLMError("proxy down")

        response = _save(context, "anthropic", [{"model_id": "claude-sonnet-4-5", "price": "litellm"}])

        assert_that(response.status_code, equal_to(503))
        assert_that(response.json(), equal_to({"detail": PRICE_LIST_UNREADABLE}))
        _assert_nothing_saved(context, {}, _other_routes())


def test_a_litellm_failure_part_way_leaves_the_models_unchanged_and_a_retry_repairs_the_routes():
    with given(_setup(admin, anthropic_with_routes, provider_lists(SAVE_LISTED), _claude_prices())) as context:
        _stored_claude(context, "claude-haiku-4-5", HAIKU_LISTED)
        before = _stored_prices(context)
        upsert = context.injector.get(LiteLLMClient).upsert_model_deployment
        write = upsert.side_effect

        def fail_after_the_first_write(**route):
            if upsert.call_count > 1:
                raise LiteLLMError("proxy down")
            write(**route)

        upsert.side_effect = fail_after_the_first_write
        models = [
            {"model_id": "claude-opus-4-1", "price": "litellm"},
            {"model_id": "claude-sonnet-4-5", "price": "litellm"},
        ]

        failed = _save(context, "anthropic", models)

        assert_that(failed.status_code, equal_to(503))
        assert_that(failed.json(), equal_to({"detail": MODELS_NOT_ROUTED}))
        assert_that(_stored_prices(context), equal_to(before))
        assert_that(_models_changed_events(context), has_length(0))

        upsert.side_effect = write
        retried = _save(context, "anthropic", models)

        assert_that(retried.status_code, equal_to(200), retried.text)
        connection_id = context.connection.id
        assert_that(
            context.routes,
            equal_to(
                {
                    **_other_routes(),
                    **_claude_route(
                        context,
                        "claude-opus-4-1",
                        uuid5(connection_id, "claude-opus-4-1"),
                        ("0.000015", "0.000075", "0.000015", "0.000015"),
                    ),
                    **_claude_route(
                        context, "claude-sonnet-4-5", uuid5(connection_id, "claude-sonnet-4-5"), SONNET_LISTED
                    ),
                }
            ),
        )


@pytest.mark.parametrize("deleted", [False, True])
def test_saving_the_models_of_a_missing_connection_is_not_found(deleted):
    with given(_setup(admin, provider_lists([]), litellm_prices())) as context:
        if deleted:
            _connection(context, "xai", "xAI", ProviderType.XAI, deleted_at=datetime.now(UTC))

        response = _save(context, "xai", [])

        assert_that(response.status_code, equal_to(404))
        assert_that(response.json(), equal_to({"detail": NOT_FOUND}))
        context.list_models.assert_not_called()


@pytest.mark.parametrize(
    ("slug", "detail"),
    [("openrouter", MODELS_NOT_STORED), ("anthropic", ANTHROPIC_HAS_NO_KEY)],
)
def test_a_connection_whose_models_are_not_listed_cannot_save_them(slug, detail):
    with given(_setup(admin, azure_connected, provider_lists([]), litellm_prices())) as context:
        _connection(context, "anthropic", "Anthropic", ProviderType.ANTHROPIC)

        response = _save(context, slug, [])

        assert_that(response.status_code, equal_to(409))
        assert_that(response.json(), equal_to({"detail": detail}))
        context.list_models.assert_not_called()


def test_a_key_replaced_while_the_models_were_listed_saves_nothing():
    with given(_setup(admin, anthropic_with_routes, _claude_prices())) as context:

        def replace_key_while_listing(provider_type, api_key):
            with _session(context) as session:
                row = session.get(LlmProviderConnection, context.connection.id)
                assert row is not None
                row.api_key_encrypted = encrypt_token(REPLACED_KEY, TEST_ENCRYPTION_KEY)
                row.api_key_last4 = REPLACED_KEY[-4:]
                session.add(row)
                session.commit()
            return SAVE_LISTED

        context.injector.get(LlmProviderCatalogue).list_models = Mock(side_effect=replace_key_while_listing)

        response = _save(context, "anthropic", [{"model_id": "claude-sonnet-4-5", "price": "litellm"}])

        assert_that(response.status_code, equal_to(409))
        assert_that(response.json(), equal_to({"detail": MODELS_CHANGED_WHILE_READING}))
        _assert_nothing_saved(context, {}, _other_routes())


def test_a_stored_model_removed_while_the_models_were_listed_saves_nothing():
    with given(_setup(admin, anthropic_with_routes, _claude_prices())) as context:
        sonnet = _stored_claude(context, "claude-sonnet-4-5", SONNET_STORED)

        def remove_model_while_listing(provider_type, api_key):
            with _session(context) as session:
                session.delete(session.get(LlmProviderModel, sonnet.id))
                session.commit()
            return SAVE_LISTED

        context.injector.get(LlmProviderCatalogue).list_models = Mock(side_effect=remove_model_while_listing)
        routes_before = dict(context.routes)

        response = _save(context, "anthropic", [{"model_id": "claude-sonnet-4-5", "price": "stored"}])

        assert_that(response.status_code, equal_to(409))
        assert_that(response.json(), equal_to({"detail": MODELS_CHANGED_WHILE_READING}))
        _assert_nothing_saved(context, {}, routes_before)


def test_a_connection_deleted_while_the_models_were_listed_saves_nothing():
    with given(_setup(admin, anthropic_with_routes, _claude_prices())) as context:

        def delete_while_listing(provider_type, api_key):
            assert_that(context.client.delete(f"{BASE}/anthropic", headers=auth(context)).status_code, equal_to(204))
            return SAVE_LISTED

        context.injector.get(LlmProviderCatalogue).list_models = Mock(side_effect=delete_while_listing)

        response = _save(context, "anthropic", [{"model_id": "claude-sonnet-4-5", "price": "litellm"}])

        assert_that(response.status_code, equal_to(404))
        assert_that(response.json(), equal_to({"detail": NOT_FOUND}))
        assert_that(context.routes, equal_to(_other_routes()))
        assert_that(_models(context, context.connection), has_length(0))
        assert_that(_models_changed_events(context), has_length(0))


def test_a_custom_connection_saves_typed_prices_routed_at_its_base_url():
    with given(_setup(admin, anthropic_with_routes, provider_lists(["llama-3"]), litellm_prices())) as context:
        custom = _connection(
            context,
            "custom-lab",
            "Aardvark lab",
            ProviderType.CUSTOM,
            base_url=CUSTOM_BASE_URL,
            **_with_key(CUSTOM_KEY),
        )

        response = _save(
            context, "custom-lab", [{"model_id": "llama-3", "price": _typed("0.000001", "0.000002", "0", "0")}]
        )

        assert_that(response.status_code, equal_to(200), response.text)
        route_id = f"agentbarn:model:{custom.id}:{uuid5(custom.id, 'llama-3')}"
        assert_that(
            context.routes[route_id],
            equal_to(
                {
                    "model_name": "custom-lab/llama-3",
                    "litellm_params": {
                        "model": "openai/llama-3",
                        "api_base": CUSTOM_BASE_URL,
                        "api_key": CUSTOM_KEY,
                        "input_cost_per_token": 1e-06,
                        "output_cost_per_token": 2e-06,
                        "cache_read_input_token_cost": 0.0,
                        "cache_creation_input_token_cost": 0.0,
                    },
                    "model_info": {"id": route_id, "disable_background_health_check": True},
                }
            ),
        )
        context.list_models.assert_called_once_with(ProviderType.CUSTOM, CUSTOM_KEY, CUSTOM_BASE_URL)


def test_a_custom_model_cannot_take_litellms_price():
    with given(
        _setup(admin, provider_lists(["llama-3"]), litellm_prices(_price("openai/llama-3", "0.000001", "0.000002")))
    ) as context:
        _connection(
            context,
            "custom-lab",
            "Aardvark lab",
            ProviderType.CUSTOM,
            base_url=CUSTOM_BASE_URL,
            **_with_key(CUSTOM_KEY),
        )

        response = _save(context, "custom-lab", [{"model_id": "llama-3", "price": "litellm"}])

        assert_that(response.status_code, equal_to(422))
        assert_that(response.json(), equal_to({"detail": NO_CHAT_PRICE}))


def _azure_prices():
    return litellm_prices(
        _price("azure/eu/gpt-4o", "0.00000275", "0.000011", "0.000001375"),
        _price("azure/global/gpt-5", "0.00000125", "0.00001", "0.000000125", "0.00000125"),
        _price("azure/gpt-4o", "0.0000025", "0.00001", "0.00000125"),
        _price("azure/text-embedding-3-small", "0.00000002", "0.00000002", mode="embedding"),
        _price("claude-sonnet-4-5", *SONNET_LISTED),
    )


def _azure_route(context, deployment: str, row_id: UUID, prices: tuple[str, str, str, str]) -> dict[str, dict]:
    route_id = f"agentbarn:model:{context.connection.id}:{row_id}"
    return {
        route_id: {
            "model_name": f"azure-eu/{deployment}",
            "litellm_params": {
                "model": f"azure/{deployment}",
                "api_base": AZURE_BASE_URL,
                "api_version": "v1",
                "api_key": AZURE_KEY,
                "input_cost_per_token": float(prices[0]),
                "output_cost_per_token": float(prices[1]),
                "cache_read_input_token_cost": float(prices[2]),
                "cache_creation_input_token_cost": float(prices[3]),
            },
            "model_info": {"id": route_id, "disable_background_health_check": True},
        }
    }


def _stored_deployment(context, deployment: str, prices: tuple[str, str, str, str], **fields) -> LlmProviderModel:
    model = _model(
        context,
        context.connection,
        deployment,
        input_cost_per_token=Decimal(prices[0]),
        output_cost_per_token=Decimal(prices[1]),
        cache_read_input_token_cost=Decimal(prices[2]),
        cache_creation_input_token_cost=Decimal(prices[3]),
        **fields,
    )
    context.routes.update(_azure_route(context, deployment, model.id, prices))
    return model


def test_an_azure_deployment_is_priced_from_the_model_it_runs():
    with given(_setup(admin, azure_with_routes, provider_lists([]), _azure_prices())) as context:
        response = _save(
            context,
            "azure-eu",
            [
                {"model_id": "prod-gpt4o", "price": "litellm", "runs_model": "eu/gpt-4o"},
                {"model_id": "lab.mini_2", "price": _typed("0.000001", "0.000002", "0", "0")},
            ],
        )

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            response.json(),
            equal_to(
                [
                    {
                        "model_id": "lab.mini_2",
                        "input_cost_per_token": "0.000001000000000000",
                        "output_cost_per_token": "0.000002000000000000",
                        "cache_read_input_token_cost": "0.000000000000000000",
                        "cache_creation_input_token_cost": "0.000000000000000000",
                        "price_source": "manual",
                        "litellm_price_key": None,
                    },
                    {
                        "model_id": "prod-gpt4o",
                        "input_cost_per_token": "0.000002750000000000",
                        "output_cost_per_token": "0.000011000000000000",
                        "cache_read_input_token_cost": "0.000001375000000000",
                        "cache_creation_input_token_cost": "0.000002750000000000",
                        "price_source": "litellm",
                        "litellm_price_key": "azure/eu/gpt-4o",
                    },
                ]
            ),
        )
        connection_id = context.connection.id
        assert_that(
            context.routes,
            equal_to(
                {
                    **_other_routes(),
                    **_azure_route(
                        context,
                        "lab.mini_2",
                        uuid5(connection_id, "lab.mini_2"),
                        ("0.000001", "0.000002", "0", "0"),
                    ),
                    **_azure_route(context, "prod-gpt4o", uuid5(connection_id, "prod-gpt4o"), EU_GPT4O_LISTED),
                }
            ),
        )
        [event] = _models_changed_events(context)
        assert_that(event.payload, has_entries(added_count=2, added_model_ids=["lab.mini_2", "prod-gpt4o"]))
        context.list_models.assert_not_called()


def test_switching_the_model_a_deployment_runs_reprices_it():
    with given(_setup(admin, azure_with_routes, provider_lists([]), _azure_prices())) as context:
        prod = _stored_deployment(
            context,
            "prod-gpt4o",
            EU_GPT4O_LISTED,
            price_source=PriceSource.LITELLM,
            litellm_price_key="azure/eu/gpt-4o",
        )
        _stored_deployment(context, "lab-mini", ("0.000001", "0.000002", "0", "0"))
        upsert = context.injector.get(LiteLLMClient).upsert_model_deployment

        response = _save(
            context,
            "azure-eu",
            [
                {"model_id": "prod-gpt4o", "price": "litellm", "runs_model": "gpt-4o"},
                {"model_id": "lab-mini", "price": "stored"},
            ],
        )

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            _stored_prices(context)["prod-gpt4o"],
            equal_to((*(Decimal(price) for price in GPT4O_LISTED), PriceSource.LITELLM, "azure/gpt-4o")),
        )
        assert_that(upsert.call_count, equal_to(1))
        route_id = _route_id(context.connection, prod)
        assert_that(
            context.routes[route_id], equal_to(_azure_route(context, "prod-gpt4o", prod.id, GPT4O_LISTED)[route_id])
        )
        [event] = _models_changed_events(context)
        assert_that(event.payload, has_entries(repriced_count=1, repriced_model_ids=["prod-gpt4o"]))


@pytest.mark.parametrize(
    ("model", "detail"),
    [
        ({"model_id": "prod gpt4o", "price": "litellm", "runs_model": "gpt-4o"}, AZURE_DEPLOYMENT_FORMAT),
        ({"model_id": "prod:gpt4o", "price": "litellm", "runs_model": "gpt-4o"}, AZURE_DEPLOYMENT_FORMAT),
        ({"model_id": "eu/prod", "price": "litellm", "runs_model": "gpt-4o"}, AZURE_DEPLOYMENT_FORMAT),
        ({"model_id": "d" * 65, "price": "litellm", "runs_model": "gpt-4o"}, AZURE_DEPLOYMENT_FORMAT),
        ({"model_id": "", "price": "litellm", "runs_model": "gpt-4o"}, AZURE_DEPLOYMENT_FORMAT),
        ({"model_id": "prod-gpt4o", "price": "litellm"}, RUNS_MODEL_MISSING),
        (
            {"model_id": "prod-gpt4o", "price": _typed("0.000001", "0.000002", "0", "0"), "runs_model": "gpt-4o"},
            RUNS_MODEL_NOT_TAKEN,
        ),
        ({"model_id": "lab-mini", "price": "stored", "runs_model": "gpt-4o"}, RUNS_MODEL_NOT_TAKEN),
        ({"model_id": "prod-gpt4o", "price": "litellm", "runs_model": "eu/gpt-9"}, NO_CHAT_PRICE),
        ({"model_id": "prod-gpt4o", "price": "litellm", "runs_model": "text-embedding-3-small"}, NO_CHAT_PRICE),
        ({"model_id": "prod-gpt4o", "price": "litellm", "runs_model": ""}, NO_CHAT_PRICE),
    ],
)
def test_an_azure_deployment_that_breaks_a_rule_is_refused(model, detail):
    with given(_setup(admin, azure_with_routes, provider_lists([]), _azure_prices())) as context:
        _stored_deployment(context, "lab-mini", ("0.000001", "0.000002", "0", "0"))
        before, routes_before = _stored_prices(context), dict(context.routes)

        response = _save(context, "azure-eu", [model])

        assert_that(response.status_code, equal_to(422))
        assert_that(response.json(), equal_to({"detail": detail}))
        context.list_models.assert_not_called()
        _assert_nothing_saved(context, before, routes_before)


def test_only_an_azure_deployment_takes_the_model_it_runs():
    with given(_setup(admin, anthropic_with_routes, provider_lists(SAVE_LISTED), _claude_prices())) as context:
        response = _save(
            context, "anthropic", [{"model_id": "claude-sonnet-4-5", "price": "litellm", "runs_model": "x"}]
        )

        assert_that(response.status_code, equal_to(422))
        assert_that(response.json(), equal_to({"detail": RUNS_MODEL_NOT_TAKEN}))
        context.list_models.assert_not_called()
        _assert_nothing_saved(context, {}, _other_routes())


def test_the_azure_catalogue_lists_litellms_azure_chat_models():
    with given(_setup(admin, azure_with_routes, provider_lists([]), _azure_prices())) as context:
        _stored_deployment(
            context,
            "prod-gpt4o",
            EU_GPT4O_LISTED,
            price_source=PriceSource.LITELLM,
            litellm_price_key="azure/eu/gpt-4o",
        )
        _stored_deployment(
            context,
            "old-gpt4o",
            ("0.000002", "0.000008", "0.000001", "0.000002"),
            price_source=PriceSource.LITELLM,
            litellm_price_key="azure/gpt-4o",
        )
        _stored_deployment(context, "lab-mini", GPT4O_LISTED)

        response = _catalogue(context, "azure-eu")

        assert_that(response.status_code, equal_to(200), response.text)
        assert_that(
            response.json(),
            equal_to(
                [
                    {
                        "model_id": "eu/gpt-4o",
                        "stored": True,
                        "litellm_price_key": "azure/eu/gpt-4o",
                        "input_cost_per_token": "0.000002750000000000",
                        "output_cost_per_token": "0.000011000000000000",
                        "cache_read_input_token_cost": "0.000001375000000000",
                        "cache_creation_input_token_cost": "0.000002750000000000",
                        "prices_differ": False,
                    },
                    {
                        "model_id": "global/gpt-5",
                        "stored": False,
                        "litellm_price_key": "azure/global/gpt-5",
                        "input_cost_per_token": "0.000001250000000000",
                        "output_cost_per_token": "0.000010000000000000",
                        "cache_read_input_token_cost": "0.000000125000000000",
                        "cache_creation_input_token_cost": "0.000001250000000000",
                        "prices_differ": False,
                    },
                    {
                        "model_id": "gpt-4o",
                        "stored": True,
                        "litellm_price_key": "azure/gpt-4o",
                        "input_cost_per_token": "0.000002500000000000",
                        "output_cost_per_token": "0.000010000000000000",
                        "cache_read_input_token_cost": "0.000001250000000000",
                        "cache_creation_input_token_cost": "0.000002500000000000",
                        "prices_differ": True,
                    },
                ]
            ),
        )
        context.list_models.assert_not_called()

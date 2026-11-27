from decimal import Decimal
from unittest.mock import Mock
from uuid import uuid7

import httpx
import pytest
from hamcrest import assert_that, close_to, equal_to, has_entry, has_key, is_in, is_not
from sqlmodel import Session

from api.core.config import Config
from api.domains.llm_providers.models import LlmProviderConnection, ProviderType
from api.domains.llm_providers.service import PlatformLlmProviderService
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.litellm.client import LiteLLMClient
from api.infrastructure.llm_provider_catalogue.catalogue import LlmProviderCatalogue
from api.infrastructure.llm_provider_keys.checker import LlmProviderKeyChecker
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.helpers.litellm_model_store import (
    COMPLETION,
    MASTER_KEY,
    chat_stub_is_running,
    pinned_litellm_runs_the_repository_config,
)
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

pytestmark = pytest.mark.xdist_group("heavy_containers")

BASE = "/api/v1/platform/settings/llm-providers"
ENV_KEY = "sk-or-v1-environment-key-0e0e"
FIRST_KEY = "lab-first-key-a1a1"
SECOND_KEY = "lab-second-key-b2b2"
OTHER_KEY = "lab-other-key-c3c3"
MODEL = "gpt-4o"
UNTICKED_MODEL = "gpt-4o-mini"
LISTED = [MODEL, UNTICKED_MODEL]
RAW_MODEL = f"openai/{MODEL}"
PRICES = ("0.000001", "0.000002", "0.0000005", "0.000001")
CLEARED_CACHE_PRICES = ("0.000001", "0.000002", "0", "0.000001")
OTHER_PRICES = ("0.000003", "0.000004", "0", "0")
USAGE = {
    "prompt_tokens": 1000,
    "completion_tokens": 100,
    "total_tokens": 1100,
    "prompt_tokens_details": {"cached_tokens": 400},
}
STORED_COST = 600 * 1e-06 + 400 * 5e-07 + 100 * 2e-06
CLEARED_CACHE_COST = 600 * 1e-06 + 100 * 2e-06
OTHER_COST = 600 * 3e-06 + 100 * 4e-06
BUILT_IN_PRIORITY_COST = 600 * 4.25e-06 + 400 * 2.125e-06 + 100 * 1.7e-05
BUILT_IN_INPUT_PRICE = Decimal("0.0000025")
COST_DIGITS = 12
REFUSED_STATUS = 400
SESSION_ID = "hermes-session-contract"
OPENROUTER_MODEL = "openrouter/z-ai/glm-5.2"


def platform_admin(context):
    user_id = uuid7()
    there_is_a_user(id=user_id, email=f"platform-{user_id}@example.com", is_platform_admin=True)(context)
    there_is_an_access_token_for_user(user_id)(context)


def the_api_routes_through_the_pinned_litellm(monkeypatch):
    def step(context):
        config = context.injector.get(Config)
        config.litellm_base_url = context.litellm_url
        client = LiteLLMClient(context.injector.get(KubernetesClient), config)
        monkeypatch.setattr(client, "_master_key", lambda: MASTER_KEY)
        context.upsert = Mock(wraps=client.upsert_model_deployment)
        monkeypatch.setattr(client, "upsert_model_deployment", context.upsert)
        monkeypatch.setattr(context.injector.get(PlatformLlmProviderService), "litellm", client)
        context.litellm = client
        context.injector.get(LlmProviderCatalogue).list_models = Mock(return_value=LISTED)
        context.injector.get(LlmProviderKeyChecker).check = Mock(return_value=True)
        context.chat_stub.reply = {**COMPLETION, "model": MODEL, "usage": USAGE}

    return step


def lab_connection(slug: str, key: str):
    def step(context):
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            session.add(
                LlmProviderConnection(
                    slug=slug,
                    name=slug,
                    provider_type=ProviderType.CUSTOM,
                    base_url=context.chat_stub.url,
                    api_key_encrypted=encrypt_token(key, TEST_ENCRYPTION_KEY),
                    api_key_last4=key[-4:],
                )
            )
            session.commit()

    return step


def _setup(monkeypatch, *connections):
    return [
        set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY, "SKIP_SLACK_TOKEN_VALIDATION": "true"}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        platform_admin,
        chat_stub_is_running(),
        pinned_litellm_runs_the_repository_config(openrouter_api_key=ENV_KEY),
        the_api_routes_through_the_pinned_litellm(monkeypatch),
        *connections,
    ]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _save(context, slug: str, *models: tuple[str, tuple[str, str, str, str]]) -> None:
    body = {
        "models": [
            {
                "model_id": model_id,
                "price": {
                    "input_cost_per_token": prices[0],
                    "output_cost_per_token": prices[1],
                    "cache_read_input_token_cost": prices[2],
                    "cache_creation_input_token_cost": prices[3],
                },
            }
            for model_id, prices in models
        ]
    }
    response = context.client.put(f"{BASE}/{slug}/models", headers=_auth(context), json=body)
    assert_that(response.status_code, equal_to(200), response.text)


def _chat(context, model: str, **extra) -> httpx.Response:
    return httpx.post(
        f"{context.litellm_url}/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": "hello"}], **extra},
        headers={"Authorization": f"Bearer {MASTER_KEY}"},
        timeout=30,
    )


def _cost(context, model: str) -> float:
    response = _chat(context, model)
    assert_that(response.status_code, equal_to(200), response.text)
    return float(response.headers["x-litellm-response-cost"])


def _assert_refused(context, model: str) -> None:
    sent = len(context.chat_stub.keys)
    response = _chat(context, model)
    assert_that(response.status_code, equal_to(REFUSED_STATUS), response.text)
    assert_that(len(context.chat_stub.keys), equal_to(sent))


def test_a_saved_model_serves_with_its_connection_key_at_its_stored_prices(monkeypatch):
    with given(_setup(monkeypatch, lab_connection("lab", FIRST_KEY))) as context:
        with when("a Platform Administrator saves a model with typed prices"):
            _save(context, "lab", (MODEL, PRICES))

        with then("its route serves with the connection's key at the stored prices, not LiteLLM's"):
            assert_that(_cost(context, f"lab/{MODEL}"), close_to(STORED_COST, STORED_COST * 1e-9))
            assert_that(context.chat_stub.keys[-1], equal_to(FIRST_KEY))
            assert_that(context.chat_stub.models[-1], equal_to(MODEL))

        with when("the same model is saved again unchanged"):
            context.upsert.reset_mock()
            _save(context, "lab", (MODEL, PRICES))

        with then("no route is written"):
            context.upsert.assert_not_called()

        with when("its cache price is set to 0"):
            _save(context, "lab", (MODEL, CLEARED_CACHE_PRICES))

        with then("only its route is rewritten and cached tokens cost nothing"):
            context.upsert.assert_called_once()
            assert_that(_cost(context, f"lab/{MODEL}"), close_to(CLEARED_CACHE_COST, CLEARED_CACHE_COST * 1e-9))

        with then("a request served at the priority tier is billed at LiteLLM's built-in priority rates"):
            context.chat_stub.reply = {**context.chat_stub.reply, "service_tier": "priority"}
            assert_that(_cost(context, f"lab/{MODEL}"), close_to(BUILT_IN_PRIORITY_COST, BUILT_IN_PRIORITY_COST * 1e-9))
            context.chat_stub.reply = {**COMPLETION, "model": MODEL, "usage": USAGE}

        with when("the connection's key is replaced"):
            replaced = context.client.put(f"{BASE}/lab/key", headers=_auth(context), json={"api_key": SECOND_KEY})

        with then("the route uses the new key at once"):
            assert_that(replaced.status_code, equal_to(200), replaced.text)
            _cost(context, f"lab/{MODEL}")
            assert_that(context.chat_stub.keys[-1], equal_to(SECOND_KEY))

        with then("a listed model that was not ticked, and an unknown one, are refused"):
            _assert_refused(context, f"lab/{UNTICKED_MODEL}")
            _assert_refused(context, "lab/unknown-model")

        with when("the model is removed by a later save"):
            _save(context, "lab", (UNTICKED_MODEL, PRICES))

        with then("it is refused and the newly saved model serves"):
            _assert_refused(context, f"lab/{MODEL}")
            _cost(context, f"lab/{UNTICKED_MODEL}")
            assert_that(context.chat_stub.models[-1], equal_to(UNTICKED_MODEL))


def test_connections_sharing_a_model_string_keep_their_own_routes(monkeypatch):
    with given(_setup(monkeypatch, lab_connection("lab-a", FIRST_KEY), lab_connection("lab-b", OTHER_KEY))) as context:
        with when("two connections save the same model at different prices"):
            _save(context, "lab-a", (MODEL, PRICES))
            _save(context, "lab-b", (MODEL, OTHER_PRICES))

        with then("each route serves with its own connection's key and price"):
            assert_that(_cost(context, f"lab-a/{MODEL}"), close_to(STORED_COST, STORED_COST * 1e-9))
            assert_that(context.chat_stub.keys[-1], equal_to(FIRST_KEY))
            assert_that(_cost(context, f"lab-b/{MODEL}"), close_to(OTHER_COST, OTHER_COST * 1e-9))
            assert_that(context.chat_stub.keys[-1], equal_to(OTHER_KEY))

        with then("a request for the raw model string is served by one of them, at that one's price"):
            cost = round(_cost(context, RAW_MODEL), COST_DIGITS)
            served = (context.chat_stub.keys[-1], cost)
            assert_that(
                served,
                is_in([(FIRST_KEY, round(STORED_COST, COST_DIGITS)), (OTHER_KEY, round(OTHER_COST, COST_DIGITS))]),
            )

        with then("LiteLLM's price list still gives its own price for the model"):
            listed = context.litellm.get_model_prices()[MODEL]
            assert_that(listed.input_cost_per_token, equal_to(BUILT_IN_INPUT_PRICE))


def test_a_model_route_drops_openrouters_session_id_and_openrouter_keeps_it(monkeypatch):
    with given(_setup(monkeypatch, lab_connection("lab", FIRST_KEY))) as context:
        with when("a model is saved and a request carrying OpenRouter's session_id is sent to its route"):
            _save(context, "lab", (MODEL, PRICES))
            served = _chat(context, f"lab/{MODEL}", session_id=SESSION_ID)

        with then("the provider receives the request without session_id"):
            assert_that(served.status_code, equal_to(200), served.text)
            assert_that(context.chat_stub.bodies[-1], has_entry("model", MODEL))
            assert_that(context.chat_stub.bodies[-1], is_not(has_key("session_id")))

        with when("the same request is sent to OpenRouter"):
            forwarded = _chat(context, OPENROUTER_MODEL, session_id=SESSION_ID)

        with then("OpenRouter receives session_id"):
            assert_that(forwarded.status_code, equal_to(200), forwarded.text)
            assert_that(context.chat_stub.keys[-1], equal_to(ENV_KEY))
            assert_that(context.chat_stub.bodies[-1], has_entry("session_id", SESSION_ID))

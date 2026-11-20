from decimal import Decimal
from uuid import UUID

import pytest

from api.domains.llm_providers.litellm_deployments import (
    LiteLLMDeployment,
    build_model_deployment,
    model_route_id,
    model_route_prefix,
)
from api.domains.llm_providers.models import LlmProviderConnection, LlmProviderModel, PriceSource, ProviderType

CONNECTION_ID = UUID("0190a1b2-0000-7000-8000-000000000001")
OTHER_CONNECTION_ID = UUID("0190a1b2-0000-7000-8000-000000000009")
MODEL_ROW_ID = UUID("0190a1b2-0000-5000-8000-000000000002")
API_KEY = "sk-provider-secret"
ROUTE_ID = f"agentbarn:model:{CONNECTION_ID}:{MODEL_ROW_ID}"
PRICES = {
    "input_cost_per_token": 3e-06,
    "output_cost_per_token": 1.5e-05,
    "cache_read_input_token_cost": 3e-07,
    "cache_creation_input_token_cost": 3.75e-06,
}
MODEL_INFO = {"id": ROUTE_ID, "disable_background_health_check": True}


def _connection(provider_type: ProviderType, slug: str | None = None, base_url: str | None = None):
    return LlmProviderConnection(
        id=CONNECTION_ID,
        slug=slug or provider_type.value,
        name=provider_type.value,
        provider_type=provider_type,
        base_url=base_url,
    )


def _model(model_id: str, connection_id: UUID = CONNECTION_ID) -> LlmProviderModel:
    return LlmProviderModel(
        id=MODEL_ROW_ID,
        connection_id=connection_id,
        model_id=model_id,
        input_cost_per_token=Decimal("0.000003"),
        output_cost_per_token=Decimal("0.000015"),
        cache_read_input_token_cost=Decimal("0.0000003"),
        cache_creation_input_token_cost=Decimal("0.00000375"),
        price_source=PriceSource.MANUAL,
    )


@pytest.mark.parametrize(
    ("connection", "model_id", "model_name", "provider_params"),
    [
        (_connection(ProviderType.OPENAI), "gpt-4o", "openai/gpt-4o", {"model": "openai/gpt-4o"}),
        (
            _connection(ProviderType.ANTHROPIC),
            "claude-sonnet-4-5",
            "anthropic/claude-sonnet-4-5",
            {"model": "anthropic/claude-sonnet-4-5"},
        ),
        (
            _connection(ProviderType.GEMINI),
            "gemini-2.5-pro",
            "gemini/gemini-2.5-pro",
            {"model": "gemini/gemini-2.5-pro"},
        ),
        (_connection(ProviderType.XAI), "grok-4.3", "xai/grok-4.3", {"model": "xai/grok-4.3"}),
        (
            _connection(ProviderType.DEEPSEEK),
            "deepseek-chat",
            "deepseek/deepseek-chat",
            {"model": "deepseek/deepseek-chat", "api_base": "https://api.deepseek.com"},
        ),
        (
            _connection(ProviderType.FIREWORKS),
            "accounts/fireworks/models/llama-v3p1-8b-instruct",
            "fireworks/accounts/fireworks/models/llama-v3p1-8b-instruct",
            {"model": "fireworks_ai/accounts/fireworks/models/llama-v3p1-8b-instruct"},
        ),
        (
            _connection(ProviderType.NOVITA),
            "deepseek/deepseek-r1",
            "novita/deepseek/deepseek-r1",
            {"model": "novita/deepseek/deepseek-r1", "api_base": "https://api.novita.ai/openai"},
        ),
        (
            _connection(ProviderType.AZURE, slug="azure-eu", base_url="https://eu-resource.openai.azure.com"),
            "gpt-4o-eu",
            "azure-eu/gpt-4o-eu",
            {
                "model": "azure/gpt-4o-eu",
                "api_base": "https://eu-resource.openai.azure.com",
                "api_version": "v1",
            },
        ),
        (
            _connection(ProviderType.CUSTOM, slug="custom-lab", base_url="https://models.example.com/api/v1"),
            "llama-3",
            "custom-lab/llama-3",
            {"model": "openai/llama-3", "api_base": "https://models.example.com/api/v1"},
        ),
    ],
)
def test_build_model_deployment_gives_each_provider_its_full_route(connection, model_id, model_name, provider_params):
    deployment = build_model_deployment(connection, _model(model_id), API_KEY)

    assert deployment == LiteLLMDeployment(
        model_name=model_name,
        litellm_params={**provider_params, "api_key": API_KEY, **PRICES},
        model_info=MODEL_INFO,
    )


def test_build_model_deployment_always_sends_a_zero_cache_price():
    model = _model("gpt-4o")
    model.cache_read_input_token_cost = Decimal(0)
    model.cache_creation_input_token_cost = Decimal(0)

    deployment = build_model_deployment(_connection(ProviderType.OPENAI), model, API_KEY)

    assert deployment.litellm_params["cache_read_input_token_cost"] == 0.0
    assert deployment.litellm_params["cache_creation_input_token_cost"] == 0.0


def test_build_model_deployment_sends_prices_as_floats():
    deployment = build_model_deployment(_connection(ProviderType.OPENAI), _model("gpt-4o"), API_KEY)

    assert all(type(deployment.litellm_params[name]) is float for name in PRICES)


def test_model_route_id_starts_with_its_connections_prefix():
    assert model_route_prefix(CONNECTION_ID) == f"agentbarn:model:{CONNECTION_ID}:"
    assert model_route_id(CONNECTION_ID, MODEL_ROW_ID) == ROUTE_ID
    assert model_route_id(CONNECTION_ID, MODEL_ROW_ID).startswith(model_route_prefix(CONNECTION_ID))


def test_build_model_deployment_refuses_openrouter():
    with pytest.raises(ValueError):
        build_model_deployment(_connection(ProviderType.OPENROUTER), _model("openai/gpt-4o"), API_KEY)


def test_build_model_deployment_refuses_a_model_of_another_connection():
    with pytest.raises(ValueError):
        build_model_deployment(
            _connection(ProviderType.OPENAI), _model("gpt-4o", connection_id=OTHER_CONNECTION_ID), API_KEY
        )

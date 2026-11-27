import hashlib
from dataclasses import dataclass
from uuid import UUID

from api.domains.llm_providers.models import LlmProviderConnection, LlmProviderModel, ProviderType

ROUTE_ID_PREFIX = "agentbarn:model"
LITELLM_MODEL_PREFIXES = {
    ProviderType.OPENAI: "openai",
    ProviderType.ANTHROPIC: "anthropic",
    ProviderType.GEMINI: "gemini",
    ProviderType.XAI: "xai",
    ProviderType.DEEPSEEK: "deepseek",
    ProviderType.FIREWORKS: "fireworks_ai",
    ProviderType.NOVITA: "novita",
    ProviderType.AZURE: "azure",
    ProviderType.CUSTOM: "openai",
}
FIXED_API_BASES = {
    ProviderType.DEEPSEEK: "https://api.deepseek.com",
    ProviderType.NOVITA: "https://api.novita.ai/openai",
}
AZURE_API_VERSION = "v1"
KEY_FINGERPRINT_LENGTH = 16
DROPPED_PARAMS = ["session_id"]


@dataclass(frozen=True)
class LiteLLMDeployment:
    model_name: str
    litellm_params: dict
    model_info: dict


def model_route_prefix(connection_id: UUID) -> str:
    return f"{ROUTE_ID_PREFIX}:{connection_id}:"


def model_route_id(connection_id: UUID, model_row_id: UUID) -> str:
    return f"{model_route_prefix(connection_id)}{model_row_id}"


def key_fingerprint(api_key: str) -> str:
    """A short digest of the key. LiteLLM lists a route without its key, so the route carries this
    instead, to show which key it was written with."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:KEY_FINGERPRINT_LENGTH]


def _provider_params(connection: LlmProviderConnection) -> dict:
    if connection.provider_type in FIXED_API_BASES:
        return {"api_base": FIXED_API_BASES[connection.provider_type]}
    if connection.provider_type is ProviderType.AZURE:
        return {"api_base": connection.base_url, "api_version": AZURE_API_VERSION}
    if connection.provider_type is ProviderType.CUSTOM:
        return {"api_base": connection.base_url}
    return {}


def build_model_deployment(
    connection: LlmProviderConnection, model: LlmProviderModel, api_key: str
) -> LiteLLMDeployment:
    prefix = LITELLM_MODEL_PREFIXES.get(connection.provider_type)
    if prefix is None:
        raise ValueError("This provider's models are not routed one by one")
    if model.connection_id != connection.id:
        raise ValueError("The model belongs to another connection")
    return LiteLLMDeployment(
        model_name=f"{connection.slug}/{model.model_id}",
        litellm_params={
            "model": f"{prefix}/{model.model_id}",
            **_provider_params(connection),
            "api_key": api_key,
            "input_cost_per_token": float(model.input_cost_per_token),
            "output_cost_per_token": float(model.output_cost_per_token),
            "cache_read_input_token_cost": float(model.cache_read_input_token_cost),
            "cache_creation_input_token_cost": float(model.cache_creation_input_token_cost),
            "additional_drop_params": list(DROPPED_PARAMS),
        },
        model_info={
            "id": model_route_id(connection.id, model.id),
            "disable_background_health_check": True,
            "key_fingerprint": key_fingerprint(api_key),
        },
    )

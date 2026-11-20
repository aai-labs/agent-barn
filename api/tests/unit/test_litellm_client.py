import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import httpx
import pytest

from api.domains.llm_providers.models import ProviderType
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError, LiteLLMModelPrice, litellm_price_key

MODEL_ID = "agentbarn:openrouter"
PRICE_LIST_URL = "http://litellm:4000/public/litellm_model_cost_map"
MODEL_INFO_URL = "http://litellm:4000/model/info"
MASTER_KEY = "master-key"
ROUTE_PREFIX = "agentbarn:model:0190a1b2-0000-7000-8000-000000000001:"
PROVIDER_KEY = "sk-or-provider-secret"
LITELLM_PARAMS = {"model": "openrouter/*", "api_key": PROVIDER_KEY, "order": 1}
MODEL_INFO = {"id": MODEL_ID, "disable_background_health_check": True}
HEADERS = {"Authorization": "Bearer master-key", "Content-Type": "application/json"}


def _client() -> LiteLLMClient:
    config = MagicMock()
    config.litellm_base_url = "http://litellm:4000"
    return LiteLLMClient(k8s=MagicMock(), config=config)


def test_delete_key_returns_true_for_successful_remote_deletion():
    client = _client()
    response = MagicMock()
    response.raise_for_status.return_value = None

    with patch.object(client, "_master_key", return_value="master-key"):
        with patch("api.infrastructure.litellm.client.httpx.post", return_value=response) as post:
            result = client.delete_key("sk-test-key")

    assert result is True
    post.assert_called_once_with(
        "http://litellm:4000/key/delete",
        json={"keys": ["sk-test-key"]},
        headers={
            "Authorization": "Bearer master-key",
            "Content-Type": "application/json",
        },
        timeout=10,
    )


def test_delete_key_returns_false_and_does_not_log_plaintext_key_on_failure(caplog):
    client = _client()
    key = "sk-test-key"

    with patch.object(client, "_master_key", return_value="master-key"):
        with patch(
            "api.infrastructure.litellm.client.httpx.post",
            side_effect=RuntimeError(f"remote delete failed for {key}"),
        ):
            with caplog.at_level("WARNING"):
                result = client.delete_key(key)

    assert result is False
    assert key not in caplog.text


def test_spend_logs_are_requested_in_ascending_time_order():
    """Ascending order is a correctness requirement, not a preference.

    The cost sync derives its watermark from max(occurred_at) of what it has stored.
    LiteLLM defaults to sort_order=desc, under which a run truncated partway would
    store only the newest rows, push the watermark to ~now, and skip every older row
    permanently. Asserted here rather than left to a comment.
    """
    client = _client()
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": [], "total": 0, "total_pages": 0}

    with patch.object(client, "_master_key", return_value="master-key"):
        with patch("api.infrastructure.litellm.client.httpx.get", return_value=response) as get:
            client.get_spend_logs_v2("2026-09-01 00:00:00", "2026-09-02 00:00:00", page=2, page_size=1000)

    params = get.call_args.kwargs["params"]
    assert params["sort_order"] == "asc"
    assert params["sort_by"] == "startTime"
    assert params["page"] == 2
    assert params["page_size"] == 1000
    # A bare date returns HTTP 400 — the full timestamp form is required.
    assert params["start_date"] == "2026-09-01 00:00:00"


def test_spend_logs_rejects_a_non_object_response():
    client = _client()
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = [{"request_id": "gen-1"}]

    with patch.object(client, "_master_key", return_value="master-key"):
        with patch("api.infrastructure.litellm.client.httpx.get", return_value=response):
            try:
                client.get_spend_logs_v2("2026-09-01 00:00:00", "2026-09-02 00:00:00")
            except Exception as exc:
                assert "Unexpected" in str(exc)
            else:
                raise AssertionError("expected a LiteLLMError for a list response")


def _response(status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    if status_code >= 400:
        response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"failed with {PROVIDER_KEY}", request=MagicMock(), response=response
        )
    else:
        response.raise_for_status.return_value = None
    return response


def test_upsert_model_deployment_creates_a_route_litellm_does_not_have():
    client = _client()

    with patch.object(client, "_master_key", return_value="master-key"):
        with patch("api.infrastructure.litellm.client.httpx.get", return_value=_response(400)) as get:
            with patch("api.infrastructure.litellm.client.httpx.post", return_value=_response(200)) as post:
                client.upsert_model_deployment("openrouter/*", LITELLM_PARAMS, MODEL_INFO)

    get.assert_called_once_with(
        "http://litellm:4000/model/info",
        params={"litellm_model_id": MODEL_ID},
        headers=HEADERS,
        timeout=10,
    )
    post.assert_called_once_with(
        "http://litellm:4000/model/new",
        json={"model_name": "openrouter/*", "litellm_params": LITELLM_PARAMS, "model_info": MODEL_INFO},
        headers=HEADERS,
        timeout=10,
    )


def test_upsert_model_deployment_updates_a_route_litellm_already_has():
    client = _client()

    with patch.object(client, "_master_key", return_value="master-key"):
        with patch("api.infrastructure.litellm.client.httpx.get", return_value=_response(200)):
            with patch("api.infrastructure.litellm.client.httpx.post", return_value=_response(200)) as post:
                client.upsert_model_deployment("openrouter/*", LITELLM_PARAMS, MODEL_INFO)

    post.assert_called_once_with(
        "http://litellm:4000/model/update",
        json={"model_name": "openrouter/*", "litellm_params": LITELLM_PARAMS, "model_info": MODEL_INFO},
        headers=HEADERS,
        timeout=10,
    )


def test_upsert_model_deployment_failure_never_carries_the_provider_key():
    client = _client()

    with patch.object(client, "_master_key", return_value="master-key"):
        with patch("api.infrastructure.litellm.client.httpx.get", return_value=_response(400)):
            with patch("api.infrastructure.litellm.client.httpx.post", return_value=_response(500)):
                with pytest.raises(LiteLLMError) as raised:
                    client.upsert_model_deployment("openrouter/*", LITELLM_PARAMS, MODEL_INFO)

    assert PROVIDER_KEY not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_upsert_model_deployment_refuses_when_the_route_lookup_fails():
    client = _client()

    with patch.object(client, "_master_key", return_value="master-key"):
        with patch("api.infrastructure.litellm.client.httpx.get", return_value=_response(500)):
            with patch("api.infrastructure.litellm.client.httpx.post") as post:
                with pytest.raises(LiteLLMError):
                    client.upsert_model_deployment("openrouter/*", LITELLM_PARAMS, MODEL_INFO)

    post.assert_not_called()


def test_delete_model_deployment_removes_the_route():
    client = _client()

    with patch.object(client, "_master_key", return_value="master-key"):
        with patch("api.infrastructure.litellm.client.httpx.post", return_value=_response(200)) as post:
            removed = client.delete_model_deployment(MODEL_ID)

    assert removed is True
    post.assert_called_once_with(
        "http://litellm:4000/model/delete",
        json={"id": MODEL_ID},
        headers=HEADERS,
        timeout=10,
    )


def test_delete_model_deployment_reports_a_route_that_is_already_gone():
    client = _client()

    with patch.object(client, "_master_key", return_value="master-key"):
        with patch("api.infrastructure.litellm.client.httpx.post", return_value=_response(400)):
            removed = client.delete_model_deployment(MODEL_ID)

    assert removed is False


def test_delete_model_deployment_raises_on_other_failures():
    client = _client()

    with patch.object(client, "_master_key", return_value="master-key"):
        with patch("api.infrastructure.litellm.client.httpx.post", return_value=_response(500)):
            with pytest.raises(LiteLLMError):
                client.delete_model_deployment(MODEL_ID)


def _price_list_response(body: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, content=body.encode(), request=httpx.Request("GET", PRICE_LIST_URL))


def _get_model_prices(response: httpx.Response | Exception) -> tuple[dict[str, LiteLLMModelPrice], MagicMock]:
    client = _client()
    side_effect = response if isinstance(response, Exception) else None
    with patch.object(client, "_master_key") as master_key:
        with patch(
            "api.infrastructure.litellm.client.httpx.get",
            return_value=None if side_effect else response,
            side_effect=side_effect,
        ) as get:
            prices = client.get_model_prices()
    master_key.assert_not_called()
    return prices, get


def test_get_model_prices_reads_the_built_in_list_without_a_key():
    _, get = _get_model_prices(_price_list_response("{}"))

    get.assert_called_once_with(PRICE_LIST_URL, params={"catalog_only": "true"}, timeout=10)


def test_get_model_prices_maps_the_four_prices_exactly_and_the_mode():
    body = (
        '{"claude-sonnet-4-5": {"input_cost_per_token": 3e-06, "output_cost_per_token": 1.5e-05,'
        ' "cache_read_input_token_cost": 3e-07, "cache_creation_input_token_cost": 3.75e-06,'
        ' "mode": "chat", "litellm_provider": "anthropic"}}'
    )

    prices, _ = _get_model_prices(_price_list_response(body))

    assert prices == {
        "claude-sonnet-4-5": LiteLLMModelPrice(
            key="claude-sonnet-4-5",
            mode="chat",
            input_cost_per_token=Decimal("0.000003"),
            output_cost_per_token=Decimal("0.000015"),
            cache_read_input_token_cost=Decimal("3E-7"),
            cache_creation_input_token_cost=Decimal("0.00000375"),
        )
    }


def test_get_model_prices_leaves_a_missing_or_negative_cache_price_unset():
    body = json.dumps(
        {
            "gpt-4o": {"input_cost_per_token": 2.5e-06, "output_cost_per_token": 1e-05, "mode": "chat"},
            "deepseek/deepseek-chat": {
                "input_cost_per_token": 2,
                "output_cost_per_token": 4,
                "cache_read_input_token_cost": -1,
                "cache_creation_input_token_cost": 0,
            },
        }
    )

    prices, _ = _get_model_prices(_price_list_response(body))

    assert prices["gpt-4o"].cache_read_input_token_cost is None
    assert prices["gpt-4o"].cache_creation_input_token_cost is None
    assert prices["deepseek/deepseek-chat"] == LiteLLMModelPrice(
        key="deepseek/deepseek-chat",
        mode=None,
        input_cost_per_token=Decimal(2),
        output_cost_per_token=Decimal(4),
        cache_read_input_token_cost=None,
        cache_creation_input_token_cost=Decimal(0),
    )


@pytest.mark.parametrize(
    "entry",
    [
        {"output_cost_per_token": 1e-05},
        {"input_cost_per_token": None, "output_cost_per_token": 1e-05},
        {"input_cost_per_token": 0.0, "output_cost_per_token": 1e-05},
        {"input_cost_per_token": 2.5e-06, "output_cost_per_token": 0},
        {"input_cost_per_token": -2.5e-06, "output_cost_per_token": 1e-05},
        {"input_cost_per_token": "2.5e-06", "output_cost_per_token": 1e-05},
        {"input_cost_per_token": True, "output_cost_per_token": 1e-05},
        "not an entry",
    ],
)
def test_get_model_prices_leaves_out_an_entry_that_cannot_give_a_price(entry):
    prices, _ = _get_model_prices(_price_list_response(json.dumps({"gpt-4o": entry})))

    assert prices == {}


@pytest.mark.parametrize(
    "response",
    [
        _price_list_response("{}", status_code=500),
        httpx.ConnectError("refused"),
        _price_list_response("not json"),
        _price_list_response("[]"),
    ],
)
def test_get_model_prices_raises_when_litellm_cannot_give_its_list(response):
    with pytest.raises(LiteLLMError, match="Failed to read LiteLLM's price list"):
        _get_model_prices(response)


@pytest.mark.parametrize(
    ("provider_type", "model_id", "key"),
    [
        (ProviderType.OPENAI, "gpt-4o", "gpt-4o"),
        (ProviderType.ANTHROPIC, "claude-sonnet-4-5", "claude-sonnet-4-5"),
        (ProviderType.GEMINI, "gemini-2.5-pro", "gemini/gemini-2.5-pro"),
        (ProviderType.XAI, "grok-4.3", "xai/grok-4.3"),
        (ProviderType.DEEPSEEK, "deepseek-chat", "deepseek/deepseek-chat"),
        (
            ProviderType.FIREWORKS,
            "accounts/fireworks/models/llama-v3p1-8b-instruct",
            "fireworks_ai/accounts/fireworks/models/llama-v3p1-8b-instruct",
        ),
        (ProviderType.NOVITA, "deepseek/deepseek-r1", "novita/deepseek/deepseek-r1"),
        (ProviderType.AZURE, "gpt-4o", "azure/gpt-4o"),
        (ProviderType.OPENROUTER, "openai/gpt-4o", None),
        (ProviderType.CUSTOM, "llama-3", None),
    ],
)
def test_litellm_price_key_follows_each_providers_key_form(provider_type, model_id, key):
    assert litellm_price_key(provider_type, model_id) == key


def _model_info_response(body: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, content=body.encode(), request=httpx.Request("GET", MODEL_INFO_URL))


def _list_model_deployments(response: httpx.Response | Exception) -> tuple[list[dict], MagicMock]:
    client = _client()
    side_effect = response if isinstance(response, Exception) else None
    with patch.object(client, "_master_key", return_value=MASTER_KEY):
        with patch(
            "api.infrastructure.litellm.client.httpx.get",
            return_value=None if side_effect else response,
            side_effect=side_effect,
        ) as get:
            routes = client.list_model_deployments(ROUTE_PREFIX)
    return routes, get


def test_list_model_deployments_asks_litellm_once_for_every_route():
    _, get = _list_model_deployments(_model_info_response('{"data": []}'))

    get.assert_called_once_with(MODEL_INFO_URL, headers=HEADERS, timeout=10)


def test_list_model_deployments_keeps_only_the_routes_with_the_prefix():
    ours = {
        "model_name": "anthropic/claude-sonnet-4-5",
        "litellm_params": {"model": "anthropic/claude-sonnet-4-5", "input_cost_per_token": 3e-06},
        "model_info": {"id": f"{ROUTE_PREFIX}0190a1b2-0000-5000-8000-000000000002"},
    }
    body = json.dumps(
        {
            "data": [
                ours,
                {"model_name": "openrouter/*", "model_info": {"id": MODEL_ID}},
                {"model_name": "x", "model_info": {"id": "agentbarn:model:0190a1b2-0000-7000-8000-000000000009:1"}},
                {"model_name": "no-info"},
                {"model_name": "numeric-id", "model_info": {"id": 7}},
                "not a route",
            ]
        }
    )

    routes, _ = _list_model_deployments(_model_info_response(body))

    assert routes == [ours]


@pytest.mark.parametrize(
    "response",
    [
        _model_info_response(f'{{"error": "{MASTER_KEY}"}}', status_code=500),
        httpx.ConnectError(f"refused for {MASTER_KEY}"),
        _model_info_response("not json"),
        _model_info_response("{}"),
        _model_info_response('{"data": {}}'),
    ],
)
def test_list_model_deployments_raises_without_the_master_key(response, caplog):
    with caplog.at_level("DEBUG"), pytest.raises(LiteLLMError, match="Failed to list the model routes") as raised:
        _list_model_deployments(response)

    assert MASTER_KEY not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True
    assert MASTER_KEY not in caplog.text

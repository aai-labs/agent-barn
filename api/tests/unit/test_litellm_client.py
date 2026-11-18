from unittest.mock import MagicMock, patch

import httpx
import pytest

from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError

MODEL_ID = "agentbarn:openrouter"
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

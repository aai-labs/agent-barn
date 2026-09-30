from unittest.mock import MagicMock, patch

from api.infrastructure.litellm.client import LiteLLMClient


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

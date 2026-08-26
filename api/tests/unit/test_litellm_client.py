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

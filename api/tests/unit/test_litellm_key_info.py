from unittest.mock import Mock

import httpx
import pytest
from hamcrest import assert_that, equal_to

from api.core.config import Config
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMKeyNotFound


def _client(monkeypatch, status: int, body: dict) -> LiteLLMClient:
    instance = LiteLLMClient(k8s=Mock(), config=Config(litellm_base_url="http://proxy"))
    instance._cached_master_key = "test-master"
    response = httpx.Response(status, json=body, request=httpx.Request("GET", "http://proxy/key/info"))
    monkeypatch.setattr(httpx, "get", Mock(return_value=response))
    return instance


def test_a_live_key_reports_its_team(monkeypatch):
    client = _client(monkeypatch, 200, {"key": "h", "info": {"team_id": "org-1", "status": None}})

    assert_that(client.get_key_team("sk-live"), equal_to("org-1"))


def test_an_unknown_key_is_not_found(monkeypatch):
    client = _client(monkeypatch, 404, {"detail": "not found"})

    with pytest.raises(LiteLLMKeyNotFound):
        client.get_key_team("sk-unknown")


@pytest.mark.parametrize(
    "info",
    [
        {"team_id": "org-1", "status": "deleted", "deleted_at": "2026-11-12T11:43:11+00:00"},
        {"team_id": "org-1", "deleted_at": "2026-11-12T11:43:11+00:00"},
        {"team_id": "org-1", "status": "deleted"},
    ],
)
def test_a_deleted_key_is_not_found(monkeypatch, info):
    # LiteLLM v1.108.6 answers /key/info for a deleted key from its deleted-key table.
    client = _client(monkeypatch, 200, {"key": "h", "info": info})

    with pytest.raises(LiteLLMKeyNotFound):
        client.get_key_team("sk-deleted")


def test_cleanup_of_an_already_deleted_key_succeeds_without_blocking(monkeypatch):
    client = _client(monkeypatch, 200, {"key": "h", "info": {"status": "deleted", "deleted_at": "2026-11-12"}})
    client.delete_key = Mock(return_value=False)
    client.block_key = Mock()

    assert_that(client.revoke_memory_key("a" * 64), equal_to(True))
    client.block_key.assert_not_called()

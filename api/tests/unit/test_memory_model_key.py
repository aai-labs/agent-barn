from unittest.mock import Mock

import httpx
import pytest

from api.core.config import Config
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError


def client(info):
    instance = LiteLLMClient(k8s=Mock(), config=Config(litellm_base_url="http://proxy"))
    instance._cached_master_key = "test-master"
    instance.get_key_info = Mock(return_value=info)
    return instance


def test_model_enable_preserves_existing_models_and_does_not_update_budget_or_spend(monkeypatch):
    instance = client({"models": ["old"], "max_budget": 10, "spend": 4})
    post = Mock(return_value=httpx.Response(200, request=httpx.Request("POST", "http://proxy/key/update")))
    monkeypatch.setattr(httpx, "post", post)
    instance.allow_memory_models("a" * 64, ["new", "old", "fallback"])
    assert post.call_args.kwargs["json"] == {"key": "a" * 64, "models": ["fallback", "new", "old"]}


@pytest.mark.parametrize("models", [[], ["new", "old"]])
def test_already_allowed_models_do_not_change_the_key(monkeypatch, models):
    post = Mock()
    monkeypatch.setattr(httpx, "post", post)
    client({"models": models}).allow_memory_models("a" * 64, ["new"])
    post.assert_not_called()


def test_organization_team_key_is_refused(monkeypatch):
    post = Mock()
    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(LiteLLMError, match="Could not enable"):
        client({"models": ["old"], "team_id": "an-organization"}).allow_memory_models("a" * 64, ["new"])
    post.assert_not_called()


def test_upstream_error_is_sanitized(monkeypatch):
    monkeypatch.setattr(httpx, "post", Mock(side_effect=ValueError("private provider response")))
    with pytest.raises(LiteLLMError) as failure:
        client({"models": ["old"]}).allow_memory_models("a" * 64, ["new"])
    assert str(failure.value) == "Could not enable the memory model"

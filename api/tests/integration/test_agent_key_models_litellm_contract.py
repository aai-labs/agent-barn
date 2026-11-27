from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from hamcrest import assert_that, equal_to

from api.infrastructure.litellm.client import LiteLLMClient
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.litellm_memory_budget import MASTER_KEY, pinned_litellm_budget_is_running

pytestmark = pytest.mark.xdist_group("heavy_containers")

SERVED_MODEL = "openrouter/contract/model"
OTHER_MODEL = "openrouter/contract/other"
REFUSED = 403
SERVED = 200


def _client(context, monkeypatch) -> LiteLLMClient:
    config = Mock()
    config.litellm_base_url = context.litellm_url
    client = LiteLLMClient(k8s=Mock(), config=config)
    monkeypatch.setattr(client, "_master_key", lambda: MASTER_KEY)
    return client


def _complete(context, key: str) -> httpx.Response:
    return httpx.post(
        f"{context.litellm_url}/v1/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": SERVED_MODEL, "messages": [{"role": "user", "content": "hello"}]},
        timeout=30,
    )


def test_litellm_serves_an_agent_key_only_the_models_it_lists(monkeypatch):
    with given([pinned_litellm_budget_is_running()]) as context:
        client = _client(context, monkeypatch)
        key = client.generate_key(str(uuid4()), "Contract Agent", str(uuid4()), models=[OTHER_MODEL])

        with when("the key asks for a model it does not list"):
            refused = _complete(context, key)

        with then("LiteLLM refuses it"):
            assert_that(refused.status_code, equal_to(REFUSED), refused.text)

        with when("the key's list is set to that model"):
            wrote = client.set_key_models(key, [SERVED_MODEL])
            served = _complete(context, key)

        with then("the list was written and the next request is served"):
            assert_that(wrote, equal_to(True))
            assert_that(served.status_code, equal_to(SERVED), served.text)

        with then("setting the same list again writes nothing"):
            assert_that(client.set_key_models(key, [SERVED_MODEL]), equal_to(False))

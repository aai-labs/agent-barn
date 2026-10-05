import time
from uuid import uuid4

import httpx
from hamcrest import assert_that, equal_to

from api.core.config import Config
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.litellm.client import LiteLLMClient
from api.tests.core.givenpy import given
from api.tests.helpers.litellm_memory_budget import MASTER_KEY, pinned_litellm_budget_is_running
from api.tests.steps.agent_memory import agent_memory_api_setup


def test_memory_and_runtime_keys_share_the_real_litellm_team_cutoff(monkeypatch):
    with given(agent_memory_api_setup(pinned_litellm_budget_is_running())) as context:
        config = context.injector.get(Config)
        config.litellm_base_url = context.litellm_url
        client = LiteLLMClient(context.injector.get(KubernetesClient), config)
        monkeypatch.setattr(client, "_master_key", lambda: MASTER_KEY)
        org = str(uuid4())
        client.apply_team_budget(org, 1, "30d")
        memory_key = client.generate_memory_key(org)
        runtime_key = client.generate_key("contract-agent", "Contract Agent", org)
        headers = {"Authorization": f"Bearer {MASTER_KEY}"}
        memory_info = httpx.get(f"{context.litellm_url}/key/info", params={"key": memory_key}, headers=headers)
        memory_info.raise_for_status()
        assert_that(memory_info.json()["info"]["team_id"], equal_to(org))
        # A real mock-model completion is billed by LiteLLM, without contacting a provider.
        payload = {"model": "openrouter/contract/model", "messages": [{"role": "user", "content": "hello"}]}
        first = httpx.post(
            f"{context.litellm_url}/v1/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {memory_key}"},
            timeout=30,
        )
        assert_that(first.status_code, equal_to(200), first.text)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = client.get_team_budget_status(org)
            if status and status["spend"] >= 1:
                break
            time.sleep(0.2)
        else:
            raise AssertionError(f"Mock completion was not charged to its team: {status}")
        for key in (memory_key, runtime_key):
            response = httpx.post(
                f"{context.litellm_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "openrouter/contract/model", "messages": [{"role": "user", "content": "hello"}]},
                timeout=30,
            )
            assert_that(response.is_error, equal_to(True), response.text)
            assert_that("budget" in response.text.lower(), equal_to(True), response.text)

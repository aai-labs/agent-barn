import hashlib
import time
from uuid import uuid4

import httpx
import pytest
from hamcrest import assert_that, equal_to

from api.core.config import Config
from api.domains.agent_memory.key_repository import MemoryKeyRepository
from api.domains.agent_memory.runtime_settings_service import MemoryRuntimeSettingsService
from api.domains.organizations.service import OrganizationService
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError, LiteLLMKeyNotFound
from api.tests.core.givenpy import given
from api.tests.helpers.litellm_memory_budget import MASTER_KEY, pinned_litellm_budget_is_running
from api.tests.integration.test_memory_team_budget import request, setup
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


def test_a_proxy_that_drops_team_enrollment_does_not_issue_an_uncapped_memory_key(monkeypatch):
    with given(agent_memory_api_setup(pinned_litellm_budget_is_running())) as context:
        config = context.injector.get(Config)
        config.litellm_base_url = context.litellm_url
        client = LiteLLMClient(context.injector.get(KubernetesClient), config)
        monkeypatch.setattr(client, "_master_key", lambda: MASTER_KEY)
        org = str(uuid4())
        client.apply_team_budget(org, 100, "30d")
        original_post = httpx.post
        generated = []

        def drop_team(url, **kwargs):
            if url.endswith("/key/generate"):
                kwargs["json"] = {name: value for name, value in kwargs["json"].items() if name != "team_id"}
                response = original_post(url, **kwargs)
                response.raise_for_status()
                generated.append(response.json()["key"])
                return response
            return original_post(url, **kwargs)

        monkeypatch.setattr(httpx, "post", drop_team)
        with pytest.raises(LiteLLMError, match="memory processing key"):
            client.generate_memory_key(org)
        assert_that(len(generated), equal_to(1))
        with pytest.raises(LiteLLMError):
            client.get_key_team(generated[0])


def test_stored_credentials_recover_and_hash_only_cleanup_revokes_real_keys(monkeypatch):
    with given(agent_memory_api_setup(setup, pinned_litellm_budget_is_running())) as context:
        config = context.injector.get(Config)
        config.litellm_base_url = context.litellm_url
        client = LiteLLMClient(context.injector.get(KubernetesClient), config)
        monkeypatch.setattr(client, "_master_key", lambda: MASTER_KEY)
        service = context.injector.get(MemoryRuntimeSettingsService)
        service.litellm = client
        service.budgets.litellm = client
        context.injector.get(OrganizationService).llm_budgets.litellm = client
        bank = f"org-{context.organization.id}"
        first = request(context, bank)
        assert_that(first.status_code, equal_to(200), first.text)
        old = first.json()["api_key"]
        assert_that(client.revoke_memory_key(hashlib.sha256(old.encode()).hexdigest()), equal_to(True))
        with pytest.raises(LiteLLMKeyNotFound):
            client.get_memory_key_info(old)
        replacement = request(context, bank)
        assert_that(replacement.status_code, equal_to(200), replacement.text)
        new = replacement.json()["api_key"]
        assert_that(new == old, equal_to(False))
        assert_that(client.get_memory_key_info(new)["team_id"], equal_to(str(context.organization.id)))
        client.block_key(new)
        assert_that(request(context, bank).status_code, equal_to(503))
        response = context.client.delete(
            f"/api/v1/organizations/{context.organization.id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(204), response.text)
        with pytest.raises(LiteLLMKeyNotFound):
            client.get_memory_key_info(new)
        assert_that(context.injector.get(MemoryKeyRepository).hashes(), equal_to({}))

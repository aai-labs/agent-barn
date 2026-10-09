"""A one-off spend limit against the pinned LiteLLM: a team and key with no budget window
stop the Agent once the credit is spent, and report no renewal date."""

import time
from uuid import uuid4

import httpx
from hamcrest import assert_that, equal_to, none

from api.core.config import Config
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.litellm.client import ONE_OFF_BUDGET_WINDOW, LiteLLMClient
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.litellm_memory_budget import MASTER_KEY, pinned_litellm_budget_is_running
from api.tests.steps.agent_memory import agent_memory_api_setup

COMPLETION = {"model": "openrouter/contract/model", "messages": [{"role": "user", "content": "hello"}]}


def _complete(context, key: str) -> httpx.Response:
    return httpx.post(
        f"{context.litellm_url}/v1/chat/completions",
        json=COMPLETION,
        headers={"Authorization": f"Bearer {key}"},
        timeout=30,
    )


def _wait_for_spend(client: LiteLLMClient, org: str, at_least: float) -> dict:
    deadline = time.monotonic() + 30
    status = None
    while time.monotonic() < deadline:
        status = client.get_team_budget_status(org)
        if status and status["spend"] >= at_least:
            return status
        time.sleep(0.2)
    raise AssertionError(f"Mock completion was not charged to its team: {status}")


def test_a_spent_one_off_credit_stops_the_agent_and_never_renews(monkeypatch):
    with given(agent_memory_api_setup(pinned_litellm_budget_is_running())) as context:
        config = context.injector.get(Config)
        config.litellm_base_url = context.litellm_url
        client = LiteLLMClient(context.injector.get(KubernetesClient), config)
        monkeypatch.setattr(client, "_master_key", lambda: MASTER_KEY)
        org = str(uuid4())
        client.apply_team_budget(org, 1, ONE_OFF_BUDGET_WINDOW)
        agent_key = client.generate_key(
            "trial-agent", "Trial Agent", org, max_budget=1, budget_duration=ONE_OFF_BUDGET_WINDOW
        )

        with when("the Agent spends its credit"):
            first = _complete(context, agent_key)
            status = _wait_for_spend(client, org, 1)

        with then("the first call was served"):
            assert_that(first.status_code, equal_to(200), first.text)

        with then("the credit never renews"):
            assert_that(status["renews_at"], none())

        with then("the next call is refused as over budget"):
            refused = _complete(context, agent_key)
            assert_that(refused.is_error, equal_to(True), refused.text)
            assert_that("budget" in refused.text.lower(), equal_to(True), refused.text)


def test_ending_a_trial_keeps_team_and_key_spend_in_step(monkeypatch):
    """The pinned image cannot zero a team's spend, so a key must not be zeroed either
    when its one-off limit becomes a renewing one: both carry the trial's spend until
    their shared renewal."""
    with given(agent_memory_api_setup(pinned_litellm_budget_is_running())) as context:
        config = context.injector.get(Config)
        config.litellm_base_url = context.litellm_url
        client = LiteLLMClient(context.injector.get(KubernetesClient), config)
        monkeypatch.setattr(client, "_master_key", lambda: MASTER_KEY)
        org = str(uuid4())
        client.apply_team_budget(org, 100, ONE_OFF_BUDGET_WINDOW)
        agent_key = client.generate_key(
            "trial-agent", "Trial Agent", org, max_budget=100, budget_duration=ONE_OFF_BUDGET_WINDOW
        )
        _complete(context, agent_key)
        spent = _wait_for_spend(client, org, 1)["spend"]

        with when("the trial ends on a monthly limit"):
            client.apply_team_budget(org, 500, "30d")
            client.apply_key_budget(agent_key, 500, "30d")

        with then("the team and the key both still count the trial's spend, and now renew"):
            team = client.get_team_budget_status(org)
            key = client.get_key_budget_status(agent_key)
            assert team is not None
            assert_that((team["spend"], key["spend"]), equal_to((spent, spent)))
            assert_that(team["renews_at"] is not None and key["renews_at"] is not None, equal_to(True))

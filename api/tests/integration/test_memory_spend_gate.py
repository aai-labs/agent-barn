from datetime import UTC, datetime, timedelta

import pytest
from hamcrest import assert_that, equal_to, has_length

from api.core.config import get_config
from api.domains.agents.models import AgentStatus
from api.domains.costs.repository import CostRepository
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.memory_backend import memory_gateway_is_ready
from api.tests.steps.agent import there_is_an_agent
from api.tests.steps.agent_memory import agent_memory_api_setup, memory_is_enabled
from api.tests.steps.cost import cost_records_are_clean, memory_budget_is_present

_PAYLOADS = {
    "memories": {"items": [{"content": "Durable private fact."}]},
    "reflect": {"query": "What do we know?"},
    "memories/recall": {"query": "What do we know?"},
}


def _setup(*steps):
    return agent_memory_api_setup(
        there_is_an_agent(status=AgentStatus.RUNNING),
        memory_is_enabled(),
        cost_records_are_clean(),
        *steps,
        memory_gateway_is_ready(),
    )


def _post(context, endpoint):
    return context.memory_client.post(
        f"/memory/v1/v1/default/banks/forged-bank/{endpoint}",
        json=_PAYLOADS[endpoint],
        headers={"Authorization": f"Bearer {context.memory_key}"},
    )


@pytest.mark.parametrize("endpoint", ["memories", "reflect"])
@pytest.mark.parametrize("runtime_spend,memory_spend", [(10, "0"), (4, "6"), (4, "7")])
def test_exhausted_combined_spend_blocks_model_producing_memory_operations(endpoint, runtime_spend, memory_spend):
    with given(_setup(memory_budget_is_present(runtime_spend=runtime_spend, memory_spend=memory_spend))) as context:
        with when("the Agent asks for a model-producing memory operation at its Organization limit"):
            response = _post(context, endpoint)
        with then("the gateway rejects it without forwarding tenant content"):
            assert_that(response.status_code, equal_to(429))
            assert_that(response.json(), equal_to({"detail": "Organization model spend limit reached."}))
            assert_that(context.backend_requests, equal_to([]))


@pytest.mark.parametrize("endpoint", ["memories", "reflect"])
def test_memory_operations_below_the_combined_limit_are_forwarded(endpoint):
    with given(_setup(memory_budget_is_present(runtime_spend=4, memory_spend="5.999999999999"))) as context:
        with when("the Agent uses memory below the combined limit"):
            response = _post(context, endpoint)
        with then("the normal authenticated and bank-scoped request reaches Hindsight"):
            assert_that(response.status_code, equal_to(200))
            assert_that(context.backend_requests, has_length(1))
            assert_that(
                context.backend_requests[0]["path"],
                equal_to(f"/v1/default/banks/org-{context.organization.id}/{endpoint}"),
            )


@pytest.mark.parametrize("endpoint", ["memories", "reflect"])
@pytest.mark.parametrize(
    "settings",
    [
        {"llm_spend_usd": None},
        {"llm_spend_usd": float("nan")},
        {"llm_spend_usd": -1},
        {"llm_spend_observed_at": None},
        {"llm_budget_renews_at": None},
        {"llm_budget_duration": "invalid"},
        {"llm_budget_duration": "99999999999999999999999999d"},
        {"llm_spend_observed_at": datetime.now(UTC) - timedelta(minutes=11)},
        {"llm_spend_observed_at": datetime.now(UTC) + timedelta(hours=1)},
        {"llm_budget_renews_at": datetime.now(UTC) - timedelta(seconds=1)},
    ],
)
def test_unknown_stale_or_expired_runtime_budget_status_blocks_new_memory_spend(endpoint, settings):
    with given(_setup(memory_budget_is_present(**settings))) as context:
        with when("the Organization spend window cannot be trusted"):
            response = _post(context, endpoint)
        with then("the gateway refuses new memory model work until refreshed"):
            assert_that(response.status_code, equal_to(503))
            assert_that(context.backend_requests, equal_to([]))


@pytest.mark.parametrize("endpoint", ["memories", "reflect"])
@pytest.mark.parametrize("synced", [False, True])
def test_missing_or_stale_cost_sync_blocks_memory_spend(endpoint, synced):
    with given(_setup(memory_budget_is_present(synced=synced))) as context:
        if synced:
            context.injector.get(CostRepository).record_sync_completion(datetime.now(UTC) - timedelta(minutes=21))
        with when("the memory cost sync has not completed recently"):
            response = _post(context, endpoint)
        with then("the gateway refuses spend without contacting Hindsight"):
            assert_that(response.status_code, equal_to(503))
            assert_that(context.backend_requests, equal_to([]))


def test_zero_limit_is_enforced_without_needing_any_snapshot():
    with given(
        _setup(memory_budget_is_present(limit=0, synced=False, llm_spend_usd=None, llm_budget_renews_at=None))
    ) as context:
        with when("an Agent requests a retain with a zero Organization allowance"):
            response = _post(context, "memories")
        with then("the zero limit denies the retain"):
            assert_that(response.status_code, equal_to(429))
            assert_that(context.backend_requests, equal_to([]))


def test_uncapped_organizations_do_not_depend_on_spend_snapshots():
    with given(_setup(memory_budget_is_present(limit=None, synced=False, llm_spend_usd=None))) as context:
        with when("an uncapped Agent retains a memory"):
            response = _post(context, "memories")
        with then("the retain reaches Hindsight"):
            assert_that(response.status_code, equal_to(200))
            assert_that(context.backend_requests, has_length(1))


@pytest.mark.parametrize("synced", [False, True])
def test_recall_remains_available_at_the_limit_and_without_fresh_cost_data(synced):
    with given(_setup(memory_budget_is_present(limit=0, synced=synced))) as context:
        with when("the Agent recalls existing memories"):
            response = _post(context, "memories/recall")
        with then("recall reaches Hindsight despite the spend gate"):
            assert_that(response.status_code, equal_to(200))
            assert_that(context.backend_requests, has_length(1))


def test_raising_and_removing_a_limit_take_effect_on_the_next_request():
    with given(_setup(memory_budget_is_present(runtime_spend=4, memory_spend="6"))) as context:
        assert_that(_post(context, "memories").status_code, equal_to(429))
        with when("the persisted Organization limit is raised"):
            context.organization.llm_budget_usd = 11
            context.injector.get(PostgresRepositoryDelegate).save(context.organization)
        with then("the next request can retain"):
            assert_that(_post(context, "memories").status_code, equal_to(200))
        with when("the limit is removed and no cost sync is available"):
            context.organization.llm_budget_usd = None
            context.injector.get(PostgresRepositoryDelegate).save(context.organization)
            context.injector.get(CostRepository).record_sync_completion(datetime.now(UTC) - timedelta(days=1))
        with then("the next request can retain without a spend snapshot"):
            assert_that(_post(context, "memories").status_code, equal_to(200))


def test_a_renewed_window_does_not_count_the_previous_windows_memory_charges():
    with given(
        _setup(
            memory_budget_is_present(
                runtime_spend=0, memory_spend="10", llm_budget_renews_at=datetime.now(UTC) + timedelta(days=30)
            )
        )
    ) as context:
        with when("the Agent retains after a refreshed renewal"):
            response = _post(context, "memories")
        with then("previous-window charges no longer exhaust the allowance"):
            assert_that(response.status_code, equal_to(200))


def test_capped_organizations_require_the_attribution_key_configuration():
    with given(_setup(memory_budget_is_present())) as context:
        get_config().memory_litellm_key_hashes = ""
        with when("memory cost attribution is not configured"):
            response = _post(context, "memories")
        with then("the gateway refuses to spend against incomplete attribution"):
            assert_that(response.status_code, equal_to(503))
            assert_that(context.backend_requests, equal_to([]))

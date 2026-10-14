"""One-off spend limits (AF-368): a trial Organization's credit is granted once and never
renews, so its team and its Agents' keys carry a limit with no LiteLLM budget window."""

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

from hamcrest import assert_that, equal_to

from api.domains.costs.memory_budget import MemoryBudgetAccounting
from api.domains.events.catalog import AGENT_LLM_BUDGET_EXHAUSTED, ORGANIZATION_LLM_BUDGET_EXHAUSTED
from api.infrastructure.litellm.client import ONE_OFF_BUDGET_WINDOW, LiteLLMClient
from api.tests.unit.test_organization_llm import (
    budget_email_handler,
    budget_event,
    client,
    config,
    delivery_context,
    response,
)
from api.tests.unit.test_spend_limits import (
    KEY_GENERATE,
    KEY_UPDATE,
    SECRET_KEY,
    agent_budget_event,
    agent_budget_handler,
    key,
)

TEAM_NEW = "http://litellm/team/new"


def team(**fields):
    return response({"team_info": {"team_id": "org", **fields}})


def test_a_one_off_team_limit_is_created_with_no_renewal_window():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[response({}, 404), team(max_budget=10.0, budget_duration=None)],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})) as post,
    ):
        renews = client().apply_team_budget("org", 10.0, ONE_OFF_BUDGET_WINDOW)
    assert_that(post.call_args.args[0], equal_to(TEAM_NEW))
    assert_that(post.call_args.kwargs["json"]["max_budget"], equal_to(10.0))
    assert_that(post.call_args.kwargs["json"]["budget_duration"], equal_to(None))
    assert_that(renews, equal_to(None))


def test_an_unchanged_one_off_team_limit_writes_nothing():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            return_value=team(max_budget=10.0, budget_duration=None, spend=4.0),
        ),
        patch("api.infrastructure.litellm.client.httpx.post") as post,
    ):
        client().apply_team_budget("org", 10.0, ONE_OFF_BUDGET_WINDOW)
    post.assert_not_called()


def test_a_team_created_for_a_new_key_carries_a_one_off_limit():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[response({}, 404), team(max_budget=10.0, budget_duration=None)],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})) as post,
    ):
        client().ensure_team_exists("org", 10.0, ONE_OFF_BUDGET_WINDOW)
    assert_that(post.call_args.kwargs["json"]["budget_duration"], equal_to(None))


def test_a_generated_key_carries_a_one_off_limit_with_no_window():
    c = client()
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch.object(c, "ensure_team_exists"),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({"key": "sk-test"})) as post,
    ):
        c.generate_key("agent", "Agent", "org", max_budget=10.0, budget_duration=ONE_OFF_BUDGET_WINDOW)
    assert_that(post.call_args.args[0], equal_to(KEY_GENERATE))
    assert_that(post.call_args.kwargs["json"]["max_budget"], equal_to(10.0))
    assert_that(post.call_args.kwargs["json"]["budget_duration"], equal_to(None))


def test_a_one_off_key_keeps_its_spend_when_its_limit_changes():
    """A one-off key never had a window, but its spend is the trial's: zeroing it would
    hand the trial its credit again."""
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[
                key(max_budget=10.0, budget_duration=None, spend=7.5),
                key(max_budget=20.0, budget_duration=None, spend=7.5),
            ],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})) as post,
    ):
        client().apply_key_budget(SECRET_KEY, 20.0, ONE_OFF_BUDGET_WINDOW)
    assert_that([c.args[0] for c in post.call_args_list], equal_to([KEY_UPDATE]))
    assert_that(post.call_args.kwargs["json"], equal_to({"key": SECRET_KEY, "max_budget": 20.0}))


# --- notices: a one-off limit is raised, never reset --------------------------------


def test_an_organization_that_spent_its_one_off_credit_is_not_promised_a_reset():
    handler = budget_email_handler([("owner@example.com", "Grace")])
    handler.repository.get.return_value = MagicMock(llm_budget_duration=ONE_OFF_BUDGET_WINDOW)

    handler.handle(
        budget_event(ORGANIZATION_LLM_BUDGET_EXHAUSTED, threshold=100, spend=10.0, limit=10.0, renews=None),
        delivery_context(),
    )

    body = handler.email_service.send_organization_budget_email.call_args.kwargs["body"]
    assert_that(
        body,
        equal_to(
            "Your organization has used its entire model spend limit ($10.00 of $10.00). "
            "Agents can't make model calls until the limit is raised."
        ),
    )


def test_an_agent_that_spent_its_one_off_credit_is_not_promised_a_reset():
    handler = agent_budget_handler([("creator@example.com", "Cleo")])
    handler.organization_lookup.get_llm_limit.return_value = MagicMock(window=ONE_OFF_BUDGET_WINDOW)

    handler.handle(agent_budget_event(AGENT_LLM_BUDGET_EXHAUSTED, threshold=100, spend=20.0), MagicMock())

    body = handler.email_service.send_organization_budget_email.call_args.kwargs["body"]
    assert_that(
        body,
        equal_to(
            "Support Bot in Acme has used its entire model spend limit ($20.00 of $20.00). "
            "It can't make model calls until the limit is raised."
        ),
    )


def test_ending_a_trial_carries_its_keys_spend_into_the_renewing_window():
    """LiteLLM cannot zero a team's spend, so the keys keep theirs too: the trial's spend
    counts until the first renewal, for the team and its keys alike."""
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[
                key(max_budget=10.0, budget_duration=None, spend=9.0),
                key(max_budget=50.0, budget_duration="30d", spend=9.0),
            ],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})) as post,
    ):
        client().apply_key_budget(SECRET_KEY, 50.0, "30d")
    assert_that([c.args[0] for c in post.call_args_list], equal_to([KEY_UPDATE]))


def test_legacy_memory_spend_under_a_one_off_limit_counts_since_the_organization_began():
    created = datetime(2026, 9, 1, tzinfo=UTC)
    costs = MagicMock()
    costs.memory_spend.return_value = Decimal("1.25")
    accounting = MemoryBudgetAccounting(costs=costs, config=config(memory_litellm_key_hashes="f" * 64))
    organization = MagicMock(
        id="org", llm_budget_duration=ONE_OFF_BUDGET_WINDOW, llm_budget_renews_at=None, created_at=created
    )

    spent = accounting.legacy_spend(organization)

    assert_that(spent, equal_to(1.25))
    assert_that(costs.memory_spend.call_args.args[1], equal_to(created))

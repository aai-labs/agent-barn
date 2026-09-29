"""Self-service spend limits (AF-337): an Organization's own limit below the platform
ceiling, and a limit per Agent enforced on that Agent's LiteLLM key."""

from unittest.mock import patch

import httpx
import pytest
from hamcrest import assert_that, equal_to

from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError, LiteLLMKeyNotFound
from api.tests.unit.test_organization_llm import client, response

SECRET_KEY = "sk-super-secret"
KEY_UPDATE = "http://litellm/key/update"
KEY_GENERATE = "http://litellm/key/generate"


def key(found=True, **fields):
    if not found:
        return response({"error": "not found"}, 404)
    return response({"info": {"team_id": "org", **fields}})


# --- apply_key_budget: an Agent's limit, written onto its key ----------------


def test_a_key_policy_is_written_and_verified():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[key(max_budget=None, budget_duration=None), key(max_budget=20.0, budget_duration="30d")],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})) as post,
    ):
        client().apply_key_budget(SECRET_KEY, 20.0, "30d")
    assert_that(post.call_args.args[0], equal_to(KEY_UPDATE))
    assert_that(
        post.call_args.kwargs["json"], equal_to({"key": SECRET_KEY, "max_budget": 20.0, "budget_duration": "30d"})
    )


def test_an_unchanged_key_policy_writes_nothing():
    """Sending budget_duration again would reschedule the key's renewal date."""
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            return_value=key(max_budget=20.0, budget_duration="30d", spend=3.0),
        ),
        patch("api.infrastructure.litellm.client.httpx.post") as post,
    ):
        client().apply_key_budget(SECRET_KEY, 20.0, "30d")
    post.assert_not_called()


def test_changing_only_the_amount_leaves_the_window_alone():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[key(max_budget=20.0, budget_duration="30d"), key(max_budget=5.0, budget_duration="30d")],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})) as post,
    ):
        client().apply_key_budget(SECRET_KEY, 5.0, "30d")
    assert_that(post.call_args.kwargs["json"], equal_to({"key": SECRET_KEY, "max_budget": 5.0}))


def test_a_key_update_litellm_silently_dropped_is_an_error():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[key(max_budget=None, budget_duration=None), key(max_budget=None, budget_duration=None)],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})),
    ):
        with pytest.raises(LiteLLMError):
            client().apply_key_budget(SECRET_KEY, 20.0, "30d")


def test_an_unknown_key_is_reported_as_such():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", return_value=key(found=False)),
    ):
        with pytest.raises(LiteLLMKeyNotFound):
            client().apply_key_budget(SECRET_KEY, 20.0, "30d")


def test_the_key_is_looked_up_by_hash():
    import hashlib

    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            return_value=key(max_budget=20.0, budget_duration="30d"),
        ) as get,
    ):
        client().apply_key_budget(SECRET_KEY, 20.0, "30d")
    assert_that(get.call_args.kwargs["params"], equal_to({"key": hashlib.sha256(SECRET_KEY.encode()).hexdigest()}))


@pytest.mark.parametrize(
    "failure",
    [
        {"side_effect": httpx.ConnectError("boom")},
        {"return_value": response({}, 500)},
    ],
)
def test_key_policy_failures_never_surface_the_key(failure):
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", **failure),
    ):
        with pytest.raises(LiteLLMError) as raised:
            client().apply_key_budget(SECRET_KEY, 20.0, "30d")
    assert_that(SECRET_KEY in str(raised.value), equal_to(False))
    assert_that(raised.value.__cause__ is None, equal_to(True))


def test_a_failed_key_write_never_surfaces_the_key():
    """The write carries the plaintext key in its body."""
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", return_value=key(max_budget=None, budget_duration=None)),
        patch("api.infrastructure.litellm.client.httpx.post", side_effect=httpx.ConnectError(SECRET_KEY)),
    ):
        with pytest.raises(LiteLLMError) as raised:
            client().apply_key_budget(SECRET_KEY, 20.0, "30d")
    assert_that(SECRET_KEY in str(raised.value), equal_to(False))
    assert_that(raised.value.__cause__ is None, equal_to(True))


# --- get_key_budget_status: what an Agent has spent against its own limit ----


def test_key_spend_and_renewal_are_read_from_the_proxy():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            return_value=key(spend=4.5, budget_reset_at="2026-10-01T00:00:00Z"),
        ),
    ):
        status = client().get_key_budget_status(SECRET_KEY)
    assert_that(status, equal_to({"spend": 4.5, "renews_at": "2026-10-01T00:00:00Z"}))


# --- generate_key: a new Agent starts with its limit already on the key -------


def test_a_generated_key_carries_the_agents_limit():
    c = client()
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch.object(c, "ensure_team_exists"),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({"key": "sk-test"})) as post,
    ):
        c.generate_key("agent", "Agent", "org", max_budget=20.0, budget_duration="30d")
    assert_that(post.call_args.args[0], equal_to(KEY_GENERATE))
    assert_that(post.call_args.kwargs["json"]["max_budget"], equal_to(20.0))
    assert_that(post.call_args.kwargs["json"]["budget_duration"], equal_to("30d"))


# --- deployment defaults: required, and consistent with each other ------------

DEFAULT_ENV = ("ORGANIZATION_DEFAULT_LLM_BUDGET_USD", "AGENT_DEFAULT_LLM_BUDGET_USD")


@pytest.fixture
def no_default_env(monkeypatch):
    for name in DEFAULT_ENV:
        monkeypatch.delenv(name, raising=False)


def defaults(**values):
    from api.tests.unit.test_organization_llm import config

    return config(**values)


def test_both_defaults_are_read(no_default_env):
    loaded = defaults(organization_default_llm_budget_usd=100, agent_default_llm_budget_usd=25)
    assert_that(loaded.organization_default_llm_budget_usd, equal_to(100.0))
    assert_that(loaded.agent_default_llm_budget_usd, equal_to(25.0))


def rejected(values) -> list[tuple[str, str]]:
    """(field, error type) for each rejection, so a test proves *why* it failed."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as raised:
        defaults(**values)
    return [(".".join(str(part) for part in error["loc"]), error["type"]) for error in raised.value.errors()]


@pytest.mark.parametrize(
    "values,expected",
    [
        ({"agent_default_llm_budget_usd": 25}, ("organization_default_llm_budget_usd", "missing")),
        ({"organization_default_llm_budget_usd": 100}, ("agent_default_llm_budget_usd", "missing")),
    ],
)
def test_a_missing_default_refuses_to_boot(no_default_env, values, expected):
    """Nobody is uncapped because a deployment forgot to say what the cap is."""
    assert_that(rejected(values), equal_to([expected]))


@pytest.mark.parametrize(
    "values,expected",
    [
        (
            {"organization_default_llm_budget_usd": -1, "agent_default_llm_budget_usd": 0},
            ("organization_default_llm_budget_usd", "greater_than_equal"),
        ),
        (
            {"organization_default_llm_budget_usd": 100, "agent_default_llm_budget_usd": -1},
            ("agent_default_llm_budget_usd", "greater_than_equal"),
        ),
        (
            {"organization_default_llm_budget_usd": "inf", "agent_default_llm_budget_usd": 1},
            ("organization_default_llm_budget_usd", "finite_number"),
        ),
    ],
)
def test_a_negative_or_infinite_default_is_refused(no_default_env, values, expected):
    assert_that(rejected(values), equal_to([expected]))


def test_an_agent_default_above_the_organization_default_is_refused(no_default_env):
    """Every new Agent would start above the only limit that binds it."""
    errors = rejected({"organization_default_llm_budget_usd": 10, "agent_default_llm_budget_usd": 25})
    assert_that(errors, equal_to([("", "value_error")]))


# --- the permission ------------------------------------------------------------


def test_the_budget_permission_matches_the_migration_that_catalogued_it():
    """Startup refuses a catalogue that differs from the database by a single row."""
    from uuid import UUID

    from api.domains.rbac.catalog import PERMISSION_ID_BY_KEY, PermissionKey

    assert_that(
        PERMISSION_ID_BY_KEY[PermissionKey.LLM_BUDGET_MANAGE],
        equal_to(UUID("5d0c2b7e-8f41-5a6c-9e3d-1b7f4a2c6e90")),
    )


def test_no_agent_access_role_carries_the_budget_permission():
    """Admin only for now: an Agent's own Owner cannot set its limit."""
    from api.domains.rbac.catalog import SYSTEM_AGENT_ACCESS_ROLE_GRANTS, PermissionKey

    holders = [
        role for role, grants in SYSTEM_AGENT_ACCESS_ROLE_GRANTS.items() if PermissionKey.LLM_BUDGET_MANAGE in grants
    ]
    assert_that(holders, equal_to([]))


def test_a_team_created_for_a_new_key_carries_the_organizations_limit():
    """Otherwise a team first created on the key path would run uncapped until the
    next reconciliation."""
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[response({}, 404), response({"team_info": {"team_id": "org"}})],
        ),
        patch(
            "api.infrastructure.litellm.client.httpx.post",
            side_effect=[response({}), response({"key": "sk-test"})],
        ) as post,
    ):
        client().generate_key("agent", "Agent", "org", max_budget=20.0, budget_duration="30d", team_budget=100.0)
    team_new = post.call_args_list[0]
    assert_that(team_new.args[0], equal_to("http://litellm/team/new"))
    assert_that(team_new.kwargs["json"]["max_budget"], equal_to(100.0))
    assert_that(team_new.kwargs["json"]["budget_duration"], equal_to("30d"))


# --- an Agent's own limit running out ------------------------------------------

AGENT_ID = "01a0a1ce-0000-7000-8000-00000000a9e7"
ORG_ID = "01a0a1ce-0000-7000-8000-000000000001"


def agent_budget_handler(recipients, already=None):
    from unittest.mock import MagicMock

    from api.domains.agents.event_handlers import AgentBudgetEmailHandler
    from api.domains.agents.repository import AgentLifecycleEmailRecipient

    repository = MagicMock()
    repository.find_lifecycle_email_recipients.return_value = [
        AgentLifecycleEmailRecipient(email=email, full_name=name) for email, name in recipients
    ]
    repository.find_notified_lifecycle_email_recipients.return_value = set(already or [])
    organizations = MagicMock()
    organizations.get_name.return_value = "Acme"
    return AgentBudgetEmailHandler(repository, MagicMock(), organizations)


def agent_budget_event(name, threshold=80, spend=16.0, limit=20.0):
    from unittest.mock import MagicMock
    from uuid import UUID

    return MagicMock(
        event_name=name,
        organization_id=UUID(ORG_ID),
        payload={
            "organization_id": ORG_ID,
            "agent_id": AGENT_ID,
            "threshold_percent": threshold,
            "spend_usd": spend,
            "limit_usd": limit,
            "renews_at": "2026-10-01T00:00:00Z",
            "subject_display": "Support Bot",
        },
    )


def sent(handler):
    return [call.kwargs for call in handler.email_service.send_organization_budget_email.call_args_list]


def test_an_agents_owners_are_told_it_has_run_out():
    from unittest.mock import MagicMock

    from api.domains.events.catalog import AGENT_LLM_BUDGET_EXHAUSTED

    handler = agent_budget_handler([("creator@example.com", "Cleo"), ("owner@example.com", None)])
    handler.handle(agent_budget_event(AGENT_LLM_BUDGET_EXHAUSTED, threshold=100, spend=20.0), MagicMock())
    emails = sent(handler)
    assert_that([email["receiver_email"] for email in emails], equal_to(["creator@example.com", "owner@example.com"]))
    assert_that(emails[0]["headline"], equal_to("Support Bot reached its model spend limit"))
    assert_that(
        emails[0]["body"],
        equal_to(
            "Support Bot in Acme has used its entire model spend limit ($20.00 of $20.00). "
            "It can't make model calls until the limit resets or is raised. It resets on 2026-10-01."
        ),
    )


def test_a_warning_states_usage_without_naming_any_system():
    from unittest.mock import MagicMock

    from api.domains.events.catalog import AGENT_LLM_BUDGET_THRESHOLD_REACHED

    handler = agent_budget_handler([("owner@example.com", None)])
    handler.handle(agent_budget_event(AGENT_LLM_BUDGET_THRESHOLD_REACHED), MagicMock())
    (email,) = sent(handler)
    assert_that(email["headline"], equal_to("Support Bot has used 80% of its model spend limit"))
    assert_that("LiteLLM" in email["body"] or "key" in email["body"].lower(), equal_to(False))


def test_a_retried_alert_skips_owners_already_emailed():
    from unittest.mock import MagicMock

    from api.domains.events.catalog import AGENT_LLM_BUDGET_THRESHOLD_REACHED

    handler = agent_budget_handler(
        [("creator@example.com", "Cleo"), ("owner@example.com", None)], already=["creator@example.com"]
    )
    handler.handle(agent_budget_event(AGENT_LLM_BUDGET_THRESHOLD_REACHED), MagicMock())
    assert_that([email["receiver_email"] for email in sent(handler)], equal_to(["owner@example.com"]))


# --- resolving an Agent's limit --------------------------------------------------


@pytest.mark.parametrize(
    "own,default,organization,expected",
    [
        (None, 25.0, 100.0, (25.0, "default")),
        (10.0, 25.0, 100.0, (10.0, "agent")),
        # A platform default above one Organization's own limit must not put that
        # Organization's Agents over it.
        (None, 25.0, 5.0, (5.0, "organization")),
        (50.0, 25.0, 30.0, (30.0, "organization")),
        (0.0, 25.0, 100.0, (0.0, "agent")),
    ],
)
def test_an_agents_limit_resolves_beneath_its_organizations(own, default, organization, expected):
    from api.domains.agents.llm_budget import resolve_agent_limit
    from api.domains.organizations.lookup import OrganizationLlmLimit

    resolved = resolve_agent_limit(own, default, OrganizationLlmLimit(limit_usd=organization, window="30d"))
    assert_that((resolved.limit_usd, resolved.source), equal_to(expected))


# --- the scheduled pass over Agent keys ------------------------------------------


def agent_row(own=None, alerted=None, alert_key=None):
    from unittest.mock import MagicMock
    from uuid import UUID

    from api.infrastructure.crypto import encrypt_token
    from api.tests.steps.agent import TEST_ENCRYPTION_KEY

    return MagicMock(
        id=UUID(AGENT_ID),
        organization_id=UUID(ORG_ID),
        litellm_key_encrypted=encrypt_token(SECRET_KEY, TEST_ENCRYPTION_KEY),
        llm_budget_usd=own,
        llm_alerted_threshold=alerted,
        llm_alert_key=alert_key,
    )


def agent_budget_service(agents, key_status=None, organization_limit=100.0, default=25.0):
    from unittest.mock import MagicMock

    from api.domains.agents.llm_budget import AgentLlmBudgetService
    from api.domains.organizations.lookup import OrganizationLlmLimit
    from api.tests.steps.agent import TEST_ENCRYPTION_KEY
    from api.tests.unit.test_organization_llm import config

    repository = MagicMock()
    repository.list_llm_budget_targets.return_value = agents
    repository.lower_llm_budgets_above.return_value = ([], [])
    litellm = MagicMock()
    litellm.get_key_budget_status.return_value = key_status or {"spend": None, "renews_at": None}
    organizations = MagicMock()
    organizations.get_llm_limit.return_value = OrganizationLlmLimit(limit_usd=organization_limit, window="30d")
    settings = MagicMock()
    settings.resolve_default_agent_llm_budget.return_value = default
    service = AgentLlmBudgetService(
        repository=repository,
        authorization=MagicMock(),
        permission_policy=MagicMock(),
        litellm=litellm,
        organization_lookup=organizations,
        agent_settings_lookup=settings,
        event_delivery_dispatcher=MagicMock(),
        config=config(agent_token_encryption_key=TEST_ENCRYPTION_KEY),
    )
    return service


def test_an_agent_crossing_a_threshold_is_alerted_once():
    agent = agent_row()
    service = agent_budget_service([agent], key_status={"spend": 21.0, "renews_at": "2026-10-01T00:00:00Z"})
    with patch.object(service, "_publish_crossing", return_value=True):
        first = service.check_llm_budget_thresholds()
        second = service.check_llm_budget_thresholds()
    assert_that([(c.threshold_percent, c.limit_usd) for c in first], equal_to([(80, 25.0)]))
    assert_that(second, equal_to([]))


def test_an_agent_is_held_to_its_organizations_limit_when_alerting():
    service = agent_budget_service([agent_row()], key_status={"spend": 5.0, "renews_at": None}, organization_limit=5.0)
    with patch.object(service, "_publish_crossing", return_value=True):
        (crossing,) = service.check_llm_budget_thresholds()
    assert_that((crossing.threshold_percent, crossing.limit_usd), equal_to((100, 5.0)))


def test_an_unreadable_key_neither_alerts_nor_overwrites_the_snapshot():
    agent = agent_row()
    agent.llm_spend_usd = 3.0
    service = agent_budget_service([agent])
    assert_that(service.check_llm_budget_thresholds(), equal_to([]))
    assert_that(agent.llm_spend_usd, equal_to(3.0))


def test_a_failed_alert_publish_is_retried_on_the_next_pass():
    agent = agent_row()
    service = agent_budget_service([agent], key_status={"spend": 21.0, "renews_at": None})
    with patch.object(service, "_publish_crossing", side_effect=[False, True]):
        assert_that(service.check_llm_budget_thresholds(), equal_to([]))
        assert_that(len(service.check_llm_budget_thresholds()), equal_to(1))


def test_reconciliation_rewrites_every_key_and_pulls_limits_within_the_organization():
    service = agent_budget_service([agent_row(own=10.0), agent_row()])
    service.reconcile_key_budgets()
    service.repository.lower_llm_budgets_above.assert_called_once()
    assert_that(
        [call.args for call in service.litellm.apply_key_budget.call_args_list],
        equal_to([(SECRET_KEY, 10.0, "30d"), (SECRET_KEY, 25.0, "30d")]),
    )


def test_one_unwritable_key_does_not_end_the_reconciliation():
    service = agent_budget_service([agent_row(own=10.0), agent_row()])
    service.litellm.apply_key_budget.side_effect = [LiteLLMError("down"), None]
    service.reconcile_key_budgets()
    assert_that(service.litellm.apply_key_budget.call_count, equal_to(2))


# --- the renewal date is known as soon as a limit is written ------------------------

TEAM = "http://litellm/team"


def team_info(**fields):
    return response({"team_info": {"team_id": "org", **fields}})


def test_writing_a_team_limit_returns_when_it_renews():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[
                team_info(max_budget=50.0, budget_duration="30d"),
                team_info(max_budget=40.0, budget_duration="30d", budget_reset_at="2026-10-01T00:00:00Z"),
            ],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})),
    ):
        renews = client().apply_team_budget("org", 40.0, "30d")
    assert_that(renews, equal_to("2026-10-01T00:00:00Z"))


def test_an_unchanged_team_limit_still_reports_when_it_renews():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            return_value=team_info(max_budget=40.0, budget_duration="30d", budget_reset_at="2026-10-01T00:00:00Z"),
        ),
        patch("api.infrastructure.litellm.client.httpx.post") as post,
    ):
        renews = client().apply_team_budget("org", 40.0, "30d")
    post.assert_not_called()
    assert_that(renews, equal_to("2026-10-01T00:00:00Z"))


def test_a_team_created_with_its_limit_reports_when_it_renews():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[response({}, 404), team_info(budget_reset_at="2026-10-01T00:00:00Z")],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})),
    ):
        renews = client().apply_team_budget("org", 100.0, "30d")
    assert_that(renews, equal_to("2026-10-01T00:00:00Z"))

from unittest.mock import MagicMock, patch

import httpx
import pytest
from hamcrest import assert_that, equal_to

from api.core.config import Config
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError

TEAM_NEW = "http://litellm/team/new"
TEAM_UPDATE = "http://litellm/team/update"


def config(**values):
    return Config.model_validate(
        {
            "db_connection_url": "postgresql://test:test@localhost/test",
            "secret_signing_key": "test",
            "platform_admin_credentials": "test:test",
            "litellm_base_url": "http://litellm",
            "litellm_secret_name": "litellm",
            **values,
        }
    )


def response(data, code=200):
    return httpx.Response(code, json=data, request=httpx.Request("GET", "http://litellm"))


def client():
    return LiteLLMClient(MagicMock(), config())


def team(**fields):
    return response({"team_info": {"team_id": "org", **fields}})


# --- ensure_team_exists: identity only, never policy -------------------------


def test_missing_team_is_created_without_budget_fields():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[response({}, 404), team()],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})) as post,
    ):
        client().ensure_team_exists("org")
    assert_that(post.call_args.args[0], equal_to(TEAM_NEW))
    assert_that(post.call_args.kwargs["json"], equal_to({"team_id": "org", "team_alias": "agentbarn-org"}))


def test_existing_team_is_left_untouched():
    """Key generation must never re-assert policy over a platform admin's setting."""
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", return_value=team(max_budget=50, spend=42)),
        patch("api.infrastructure.litellm.client.httpx.post") as post,
    ):
        client().ensure_team_exists("org")
    post.assert_not_called()


def test_concurrent_creation_is_verified_by_reread():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", side_effect=[response({}, 404), team()]),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({}, 400)),
    ):
        client().ensure_team_exists("org")


def test_failed_creation_raises():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", return_value=response({}, 404)),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({}, 403)),
    ):
        with pytest.raises(LiteLLMError):
            client().ensure_team_exists("org")


def test_mismatched_team_identity_is_refused():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get", return_value=response({"team_info": {"team_id": "other"}})
        ),
    ):
        with pytest.raises(LiteLLMError):
            client().ensure_team_exists("org")


# --- apply_team_budget: policy, passed in by the caller ----------------------


@pytest.mark.parametrize("budget,duration", [(None, None), (0, "30d"), (50, "30d")])
def test_missing_team_is_created_with_the_requested_policy(budget, duration):
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[response({}, 404), team(max_budget=budget, budget_duration=duration)],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})) as post,
    ):
        client().apply_team_budget("org", budget, duration)
    assert_that(
        post.call_args.kwargs["json"],
        equal_to({"team_id": "org", "team_alias": "agentbarn-org", "max_budget": budget, "budget_duration": duration}),
    )


def test_unchanged_policy_writes_nothing():
    """An update would reschedule the renewal date and is not free."""
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            return_value=team(max_budget=50, budget_duration="30d", spend=42, budget_reset_at="later"),
        ),
        patch("api.infrastructure.litellm.client.httpx.post") as post,
    ):
        client().apply_team_budget("org", 50, "30d")
    post.assert_not_called()


@pytest.mark.parametrize(
    "budget,duration,expected",
    [
        (75, "30d", {"max_budget": 75}),
        (50, "7d", {"budget_duration": "7d"}),
        (None, None, {"max_budget": None, "budget_duration": None}),
    ],
)
def test_only_changed_policy_fields_are_patched(budget, duration, expected):
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[
                team(max_budget=50, budget_duration="30d", spend=42),
                # The re-read that confirms the write actually landed.
                team(
                    max_budget=budget,
                    budget_duration=duration if budget is not None else None,
                    spend=42,
                ),
            ],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})) as post,
    ):
        client().apply_team_budget("org", budget, duration)
    assert_that(post.call_args.args[0], equal_to(TEAM_UPDATE))
    assert_that(post.call_args.kwargs["json"], equal_to({"team_id": "org", **expected}))


# --- key generation ----------------------------------------------------------


def test_generated_key_carries_team_and_attribution_metadata():
    c = client()
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch.object(c, "ensure_team_exists") as ensure,
        patch.object(c, "apply_team_budget") as apply_budget,
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({"key": "sk-test"})) as post,
    ):
        assert_that(c.generate_key("agent", "Agent", "org"), equal_to("sk-test"))
    # No budget passed: a team created here would carry none, exactly as before.
    ensure.assert_called_once_with("org", None, None)
    apply_budget.assert_not_called()
    assert_that(
        post.call_args.kwargs["json"],
        equal_to(
            {"key_alias": "Agent-agent", "team_id": "org", "metadata": {"agent_id": "agent", "organization_id": "org"}}
        ),
    )


def test_no_key_is_issued_when_the_team_cannot_be_provisioned():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", return_value=response({}, 404)),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({}, 403)) as post,
    ):
        with pytest.raises(LiteLLMError):
            client().generate_key("agent", "Agent", "org")
    assert_that([call.args[0] for call in post.call_args_list], equal_to([TEAM_NEW]))


# --- service: the Organization row is the source of policy -------------------


def organization_service(**overrides):
    from api.domains.organizations.llm_budget_service import OrganizationLlmBudgetService

    deps = {
        "organization_repository": MagicMock(),
        "agent_budgets": MagicMock(),
        "agent_settings": MagicMock(),
        "litellm": MagicMock(),
        "permission_policy": MagicMock(),
        "event_delivery_dispatcher": MagicMock(),
    }
    deps.update(overrides)
    return OrganizationLlmBudgetService(**deps)


def configured():
    return patch("api.domains.organizations.llm_budget_service.get_config", return_value=config())


def test_reconcile_applies_each_organizations_stored_budget():
    repo = MagicMock()
    repo.list_budget_policies.return_value = [("a", 50.0, "30d"), ("b", 5.0, "7d")]
    service = organization_service(organization_repository=repo)
    with configured():
        service.reconcile_llm_budgets()
    assert_that(
        [call.args for call in service.litellm.apply_team_budget.call_args_list],
        equal_to([("a", 50.0, "30d"), ("b", 5.0, "7d")]),
    )


def test_reconcile_brings_agent_keys_in_step_after_the_teams():
    service = organization_service()
    service.organization_repository.list_budget_policies.return_value = []
    with configured():
        service.reconcile_llm_budgets()
    service.agent_budgets.reconcile_key_budgets.assert_called_once_with()


def test_one_failing_organization_does_not_abort_the_sweep():
    """Drift repair is best effort: budgets are applied when set, not here."""
    repo = MagicMock()
    repo.list_budget_policies.return_value = [("a", 1.0, "30d"), ("b", 2.0, "30d")]
    service = organization_service(organization_repository=repo)
    service.litellm.apply_team_budget.side_effect = [LiteLLMError("down"), None]
    with configured():
        service.reconcile_llm_budgets()
    assert_that(service.litellm.apply_team_budget.call_count, equal_to(2))


def test_reconcile_is_skipped_when_litellm_is_not_configured():
    service = organization_service()
    with patch(
        "api.domains.organizations.llm_budget_service.get_config",
        return_value=config(litellm_base_url="", litellm_secret_name=""),
    ):
        service.reconcile_llm_budgets()
    service.litellm.apply_team_budget.assert_not_called()


def stored_org(ceiling=None, window="30d", own=None, org_id="org"):
    from api.domains.organizations.models import Organization

    return Organization(
        id=org_id if org_id != "org" else ORG,
        name="Acme",
        llm_budget_usd=100.0 if ceiling is None else ceiling,
        llm_budget_duration=window,
        llm_own_budget_usd=own,
    )


def ceiling_service(organization, *, saved=None, **overrides):
    """A budget service whose repository records the write and echoes the row back."""
    repo = MagicMock()
    repo.get.return_value = organization

    def write(organization_id, *, ceiling_usd, window, own_limit_usd, **_):
        if saved is False:
            return None
        organization.llm_budget_usd = ceiling_usd
        organization.llm_budget_duration = window
        organization.llm_own_budget_usd = own_limit_usd
        return organization, []

    repo.set_llm_budgets_with_event.side_effect = write
    return organization_service(organization_repository=repo, **overrides)


def acting():
    """The actor is resolved from a real membership; these tests are about budgets."""
    return patch("api.domains.organizations.llm_budget_service.resolve_actor_identity")


def test_setting_a_ceiling_stores_it_with_its_audit_record_and_pushes_it():
    organization = stored_org(ceiling=100.0)
    service = ceiling_service(organization)
    with configured(), acting():
        service.set_llm_budget(organization.id, 50.0, "30d", MagicMock())
    service.organization_repository.set_llm_budgets_with_event.assert_called_once()
    service.litellm.apply_team_budget.assert_called_once_with(str(organization.id), 50.0, "30d")


def test_the_stored_ceiling_survives_a_proxy_failure():
    """The row is authoritative; the proxy is a projection the sweep will repair."""
    from fastapi import HTTPException

    organization = stored_org()
    service = ceiling_service(organization)
    service.litellm.apply_team_budget.side_effect = LiteLLMError("down")
    with configured(), acting(), pytest.raises(HTTPException) as raised:
        service.set_llm_budget(organization.id, 50.0, "30d", MagicMock())
    assert_that(raised.value.status_code, equal_to(502))
    assert_that(organization.llm_budget_usd, equal_to(50.0))


def test_setting_a_ceiling_on_a_missing_organization_is_404():
    from fastapi import HTTPException

    service = organization_service()
    service.organization_repository.get.return_value = None
    with configured(), pytest.raises(HTTPException) as raised:
        service.set_llm_budget("nope", 50.0, "30d", MagicMock())
    assert_that(raised.value.status_code, equal_to(404))


def test_changing_only_the_amount_keeps_the_configured_window():
    """An amount-only change must preserve the renewal date, and apply_team_budget
    reschedules whenever the duration differs."""
    organization = stored_org(ceiling=50.0, window="7d")
    service = ceiling_service(organization)
    with configured(), acting():
        service.set_llm_budget(organization.id, 75.0, None, MagicMock())
    service.litellm.apply_team_budget.assert_called_once_with(str(organization.id), 75.0, "7d")


def test_a_ceiling_below_the_organizations_own_limit_pulls_it_down():
    organization = stored_org(ceiling=100.0, own=80.0)
    service = ceiling_service(organization)
    with configured(), acting():
        service.set_llm_budget(organization.id, 50.0, None, MagicMock())
    write = service.organization_repository.set_llm_budgets_with_event.call_args.kwargs
    assert_that((write["own_limit_usd"], write["reason"] is not None), equal_to((50.0, True)))
    service.litellm.apply_team_budget.assert_called_once_with(str(organization.id), 50.0, "30d")


def test_a_ceiling_above_the_organizations_own_limit_leaves_it_alone():
    organization = stored_org(ceiling=100.0, own=30.0)
    service = ceiling_service(organization)
    with configured(), acting():
        service.set_llm_budget(organization.id, 200.0, None, MagicMock())
    write = service.organization_repository.set_llm_budgets_with_event.call_args.kwargs
    assert_that((write["own_limit_usd"], write["reason"]), equal_to((30.0, None)))
    # The Organization's own limit is still the one in force.
    service.litellm.apply_team_budget.assert_called_once_with(str(organization.id), 30.0, "30d")


def test_a_ceiling_change_brings_agents_and_the_default_within_it():
    organization = stored_org(ceiling=100.0)
    service = ceiling_service(organization)
    with configured(), acting():
        service.set_llm_budget(organization.id, 20.0, None, MagicMock())
    assert_that(service.agent_settings.lower_default_agent_llm_budget.call_args.args, equal_to((organization.id, 20.0)))
    service.agent_budgets.fit_to_organization.assert_called_once()


def test_an_organization_deleted_mid_write_is_404_not_a_broken_response():
    from fastapi import HTTPException

    organization = stored_org()
    service = ceiling_service(organization, saved=False)
    with configured(), acting(), pytest.raises(HTTPException) as raised:
        service.set_llm_budget(organization.id, 50.0, "30d", MagicMock())
    assert_that(raised.value.status_code, equal_to(404))


# --- the reconciler runs as a CronJob, not inside the API --------------------


def test_startup_never_touches_the_llm_proxy():
    """Regression guard. Reconciliation lived in the lifespan and made the API's
    readiness depend on LiteLLM's; it is a CronJob now and must stay one."""
    import asyncio

    from api.api_app import lifespan
    from api.domains.organizations.service import OrganizationService

    service = MagicMock()
    injector = MagicMock()
    injector.get.side_effect = lambda cls: service if cls is OrganizationService else MagicMock()

    async def run():
        with (
            patch("api.api_app.create_injector", return_value=injector),
            patch("api.api_app.get_config", return_value=config()),
            patch("api.api_app.seed_aai_cli_skills"),
        ):
            async with lifespan(MagicMock()):
                await asyncio.sleep(0.05)

    asyncio.run(run())
    service.reconcile_llm_budgets.assert_not_called()


def test_the_cronjob_entrypoint_runs_one_pass():
    from api.domains.organizations import llm_budget_cron, llm_budget_reconciliation

    service = MagicMock()
    with (
        patch.object(llm_budget_cron, "build_service", return_value=service),
        patch("sys.argv", ["llm-budget-reconciliation"]),
    ):
        llm_budget_reconciliation.main()
    service.reconcile_llm_budgets.assert_called_once_with()


# --- key enrollment ----------------------------------------------------------

SECRET_KEY = "sk-super-secret"
KEY_UPDATE = "http://litellm/key/update"


def key_info(team_id=None, found=True):
    if not found:
        return response({"error": "not found"}, 404)
    return response({"info": {"team_id": team_id}})


def test_a_teamless_key_reports_no_team():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", return_value=key_info(None)),
    ):
        assert_that(client().get_key_team(SECRET_KEY), equal_to(None))


def test_a_key_litellm_has_never_heard_of_is_distinct_from_a_teamless_one():
    from api.infrastructure.litellm.client import LiteLLMKeyNotFound

    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", return_value=key_info(found=False)),
    ):
        with pytest.raises(LiteLLMKeyNotFound):
            client().get_key_team(SECRET_KEY)


def test_enrolling_a_teamless_key_updates_it_and_verifies_the_result():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[key_info(None), key_info("org")],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})) as post,
    ):
        client().attach_key_to_team(SECRET_KEY, "org")
    assert_that(post.call_args.args[0], equal_to(KEY_UPDATE))
    assert_that(post.call_args.kwargs["json"], equal_to({"key": SECRET_KEY, "team_id": "org"}))


def test_a_key_already_in_the_team_is_left_alone():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", return_value=key_info("org")),
        patch("api.infrastructure.litellm.client.httpx.post") as post,
    ):
        client().attach_key_to_team(SECRET_KEY, "org")
    post.assert_not_called()


def test_a_key_belonging_to_another_team_is_never_moved():
    """Someone may have arranged that by hand; silently reassigning it would be worse
    than leaving the Organization partially covered."""
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", return_value=key_info("someone-else")),
        patch("api.infrastructure.litellm.client.httpx.post") as post,
    ):
        with pytest.raises(LiteLLMError):
            client().attach_key_to_team(SECRET_KEY, "org")
    post.assert_not_called()


def test_an_update_litellm_silently_ignored_is_not_reported_as_enrolled():
    """/key/update is the one call this feature cannot verify from its own response."""
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[key_info(None), key_info(None)],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})),
    ):
        with pytest.raises(LiteLLMError):
            client().attach_key_to_team(SECRET_KEY, "org")


@pytest.mark.parametrize(
    "failure",
    [
        {"side_effect": httpx.ConnectError("boom")},
        {"return_value": response({}, 500)},
    ],
)
def test_enrollment_failures_never_surface_the_key(failure):
    """The key travels in /key/info's query string, so an httpx chain would carry it
    into any traceback or log line built from the exception."""
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", **failure),
    ):
        with pytest.raises(LiteLLMError) as raised:
            client().attach_key_to_team(SECRET_KEY, "org")
    assert_that(SECRET_KEY in str(raised.value), equal_to(False))
    assert_that(raised.value.__cause__ is None, equal_to(True))


# --- coverage: what a limit would actually bind ------------------------------

ORG = "01a0a1ce-0000-7000-8000-000000000001"


def coverage_service(credentials, team_of, **overrides):
    """team_of maps a decrypted key to its team, or an exception to raise for it."""
    from api.infrastructure.litellm.client import LiteLLMError

    agents = MagicMock()
    agents.llm_credentials.return_value = credentials
    litellm = MagicMock()

    def get_key_team(key):
        outcome = team_of[key]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    litellm.get_key_team.side_effect = get_key_team

    def attach(key, team_id, current_team=None):
        if isinstance(team_of.get(key), Exception):
            raise LiteLLMError("nope")
        team_of[key] = team_id

    litellm.attach_key_to_team.side_effect = attach
    # No team spend unless a test opts in — otherwise the MagicMock default leaks
    # into the response model.
    litellm.get_team_budget_status.return_value = None
    repo = MagicMock()
    repo.get.return_value = MagicMock(id=ORG)
    return organization_service(agent_budgets=agents, litellm=litellm, organization_repository=repo, **overrides)


def _decrypting():
    return patch("api.domains.organizations.llm_budget_service.decrypt_token", side_effect=lambda value, _: value)


def test_coverage_separates_enrolled_agents_from_the_rest():
    from uuid import UUID as U

    service = coverage_service(
        [(U(ORG), "covered", "k1"), (U(ORG), "bare", "k2")],
        {"k1": ORG, "k2": None},
    )
    with configured(), _decrypting():
        coverage = service.get_llm_coverage(ORG)
    assert_that(coverage.total_agents, equal_to(2))
    assert_that(coverage.enrolled_agents, equal_to(1))
    assert_that([a.status.value for a in coverage.uncovered], equal_to(["unenrolled"]))


def test_reading_coverage_never_enrolls_anything():
    from uuid import UUID as U

    service = coverage_service([(U(ORG), "bare", "k2")], {"k2": None})
    with configured(), _decrypting():
        service.get_llm_coverage(ORG)
    service.litellm.attach_key_to_team.assert_not_called()


def test_enrolling_covers_teamless_keys_and_counts_them():
    from uuid import UUID as U

    service = coverage_service(
        [(U(ORG), "a", "k1"), (U(ORG), "b", "k2")],
        {"k1": ORG, "k2": None},
    )
    with configured(), _decrypting():
        coverage = service.enroll_llm_keys(ORG)
    assert_that(coverage.enrolled_agents, equal_to(2))
    assert_that(coverage.newly_enrolled, equal_to(1))
    assert_that(coverage.uncovered, equal_to([]))
    service.litellm.ensure_team_exists.assert_called_once_with(ORG)


def test_a_key_in_another_team_is_reported_by_name_not_moved():
    from uuid import UUID as U

    service = coverage_service([(U(ORG), "borrowed", "k1")], {"k1": "another-team"})
    with configured(), _decrypting():
        coverage = service.enroll_llm_keys(ORG)
    assert_that(coverage.uncovered[0].agent_name, equal_to("borrowed"))
    assert_that(coverage.uncovered[0].status.value, equal_to("other_team"))
    service.litellm.attach_key_to_team.assert_not_called()


def test_one_unreadable_agent_does_not_end_the_sweep():
    from uuid import UUID as U

    from api.infrastructure.litellm.client import LiteLLMKeyNotFound

    service = coverage_service(
        [(U(ORG), "gone", "k1"), (U(ORG), "fine", "k2")],
        {"k1": LiteLLMKeyNotFound("missing"), "k2": None},
    )
    with configured(), _decrypting():
        coverage = service.enroll_llm_keys(ORG)
    assert_that(coverage.enrolled_agents, equal_to(1))
    assert_that([a.status.value for a in coverage.uncovered], equal_to(["unknown_key"]))


def test_an_undecryptable_key_is_reported_rather_than_raising():
    from uuid import UUID as U

    service = coverage_service([(U(ORG), "corrupt", "k1")], {"k1": None})
    with (
        configured(),
        patch("api.domains.organizations.llm_budget_service.decrypt_token", side_effect=ValueError("bad key")),
    ):
        coverage = service.get_llm_coverage(ORG)
    assert_that([a.status.value for a in coverage.uncovered], equal_to(["unreadable"]))


def test_enrolling_an_unknown_organization_is_404():
    from fastapi import HTTPException

    service = coverage_service([], {})
    service.organization_repository.get.return_value = None
    with configured(), pytest.raises(HTTPException) as raised:
        service.enroll_llm_keys(ORG)
    assert_that(raised.value.status_code, equal_to(404))


def test_an_unreachable_kubernetes_api_degrades_to_a_census_not_a_500():
    """The master key is read through the Kubernetes API, which raises its own
    exception types — those must not escape and fail the whole request."""
    from uuid import UUID as U

    service = coverage_service([(U(ORG), "a", "k1")], {"k1": None})
    service.litellm.get_key_team.side_effect = RuntimeError("k8s unreachable")
    with configured(), _decrypting():
        coverage = service.get_llm_coverage(ORG)
    assert_that(coverage.enrolled_agents, equal_to(0))
    assert_that([a.status.value for a in coverage.uncovered], equal_to(["unreadable"]))


def test_a_kubernetes_failure_reading_the_master_key_is_a_litellm_error():
    """Every caller handles LiteLLMError and nothing else."""
    k8s = MagicMock()
    k8s.get_secret.side_effect = RuntimeError("connection refused")
    with pytest.raises(LiteLLMError):
        LiteLLMClient(k8s, config())._master_key()


def test_enrolling_against_an_unreachable_proxy_is_502_not_500():
    from uuid import UUID as U

    from fastapi import HTTPException

    service = coverage_service([(U(ORG), "a", "k1")], {"k1": None})
    service.litellm.ensure_team_exists.side_effect = LiteLLMError("unreachable")
    with configured(), pytest.raises(HTTPException) as raised:
        service.enroll_llm_keys(ORG)
    assert_that(raised.value.status_code, equal_to(502))


# --- spend against the limit -------------------------------------------------


def test_team_spend_is_read_from_the_proxy():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            return_value=team(max_budget=50, spend=12.5, budget_reset_at="2026-10-01T00:00:00Z"),
        ),
    ):
        assert_that(
            client().get_team_budget_status("org"),
            equal_to({"spend": 12.5, "renews_at": "2026-10-01T00:00:00Z"}),
        )


def test_a_missing_team_has_no_spend_to_report():
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", return_value=response({}, 404)),
    ):
        assert_that(client().get_team_budget_status("org"), equal_to(None))


def test_coverage_reports_spend_against_the_limit():
    from uuid import UUID as U

    service = coverage_service([(U(ORG), "a", "k1")], {"k1": ORG})
    service.litellm.get_team_budget_status.return_value = {
        "spend": 0.011985,
        "renews_at": "2026-10-01T00:00:00Z",
    }
    with configured(), _decrypting():
        coverage = service.get_llm_coverage(ORG)
    assert_that(coverage.spend_usd, equal_to(0.011985))
    assert_that(coverage.renews_at, equal_to("2026-10-01T00:00:00Z"))


def test_an_unreadable_team_leaves_spend_unknown_rather_than_zero():
    """A failed read must never render as $0 spent — that was the defect the whole
    cost-tracking rewrite existed to remove."""
    from uuid import UUID as U

    service = coverage_service([(U(ORG), "a", "k1")], {"k1": ORG})
    service.litellm.get_team_budget_status.side_effect = LiteLLMError("down")
    with configured(), _decrypting():
        coverage = service.get_llm_coverage(ORG)
    assert_that(coverage.spend_usd, equal_to(None))
    assert_that(coverage.renews_at, equal_to(None))


# --- budget thresholds -------------------------------------------------------


def budget_service(orgs, spend_by_org, publishes=True, **overrides):
    repo = MagicMock()
    repo.list_capped_organizations.return_value = orgs
    service = organization_service(organization_repository=repo, **overrides)
    service.litellm.get_team_budget_status.side_effect = lambda team_id: spend_by_org.get(team_id)
    # Staging goes through a real Session, which a mocked repository cannot provide.
    # Threshold behaviour is the subject here; whether the outbox accepted the event
    # is its own test.
    service._publish_budget_crossing = MagicMock(return_value=publishes)
    return service


def capped(org_id="org", limit=50.0, alerted=None, key=None, renews="2026-10-01T00:00:00Z"):
    return MagicMock(
        id=org_id,
        name="Acme",
        llm_budget_usd=limit,
        effective_llm_budget_usd=limit,
        llm_alerted_threshold=alerted,
        llm_alert_key=key,
    )


def status_at(spend, renews="2026-10-01T00:00:00Z"):
    return {"spend": spend, "renews_at": renews}


def test_spend_below_every_threshold_alerts_nobody():
    service = budget_service([capped()], {"org": status_at(10.0)})
    with configured():
        fired = service.check_llm_budget_thresholds()
    assert_that(fired, equal_to([]))


@pytest.mark.parametrize("spend,threshold", [(40.0, 80), (50.0, 100), (61.0, 100)])
def test_crossing_a_threshold_fires_once(spend, threshold):
    service = budget_service([capped()], {"org": status_at(spend)})
    with configured():
        fired = service.check_llm_budget_thresholds()
    assert_that([(f.organization.id, f.threshold_percent) for f in fired], equal_to([("org", threshold)]))


def test_a_threshold_already_alerted_does_not_fire_again():
    org = capped(alerted=80, key="2026-10-01T00:00:00Z|50.0")
    service = budget_service([org], {"org": status_at(41.0)})
    with configured():
        fired = service.check_llm_budget_thresholds()
    assert_that(fired, equal_to([]))


def test_crossing_the_next_threshold_still_fires():
    org = capped(alerted=80, key="2026-10-01T00:00:00Z|50.0")
    service = budget_service([org], {"org": status_at(50.0)})
    with configured():
        fired = service.check_llm_budget_thresholds()
    assert_that([f.threshold_percent for f in fired], equal_to([100]))


def test_raising_the_limit_re_arms_the_thresholds():
    """Otherwise raising a limit silences the Organization for the rest of the window."""
    org = capped(limit=100.0, alerted=100, key="2026-10-01T00:00:00Z|50.0")
    service = budget_service([org], {"org": status_at(85.0)})
    with configured():
        fired = service.check_llm_budget_thresholds()
    assert_that([f.threshold_percent for f in fired], equal_to([80]))


def test_a_renewed_window_re_arms_the_thresholds():
    org = capped(alerted=100, key="2026-09-01T00:00:00Z|50.0")
    service = budget_service([org], {"org": status_at(45.0, renews="2026-10-01T00:00:00Z")})
    with configured():
        fired = service.check_llm_budget_thresholds()
    assert_that([f.threshold_percent for f in fired], equal_to([80]))


def test_the_snapshot_is_stored_even_when_nothing_fires():
    org = capped()
    service = budget_service([org], {"org": status_at(10.0)})
    with configured():
        service.check_llm_budget_thresholds()
    assert_that(org.llm_spend_usd, equal_to(10.0))
    service.organization_repository.save.assert_called()


def test_an_unreadable_team_neither_alerts_nor_overwrites_the_snapshot():
    """An unknown figure must never read as a breach, nor as zero spent."""
    org = capped()
    org.llm_spend_usd = 33.0
    service = budget_service([org], {})
    service.litellm.get_team_budget_status.side_effect = LiteLLMError("down")
    with configured():
        fired = service.check_llm_budget_thresholds()
    assert_that(fired, equal_to([]))
    assert_that(org.llm_spend_usd, equal_to(33.0))


def test_one_unreadable_organization_does_not_stop_the_others():
    a, b = capped(org_id="a"), capped(org_id="b")
    service = budget_service([a, b], {"b": status_at(50.0)})

    def flaky(team_id):
        if team_id == "a":
            raise LiteLLMError("down")
        return status_at(50.0)

    service.litellm.get_team_budget_status.side_effect = flaky
    with configured():
        fired = service.check_llm_budget_thresholds()
    assert_that([f.organization.id for f in fired], equal_to(["b"]))


def test_the_alerts_cronjob_entrypoint_runs_one_pass():
    from api.domains.organizations import llm_budget_alerts, llm_budget_cron

    service = MagicMock()
    with (
        patch.object(llm_budget_cron, "build_service", return_value=service),
        patch("sys.argv", ["llm-budget-alerts"]),
    ):
        llm_budget_alerts.main()
    service.check_llm_budget_thresholds.assert_called_once_with()


def test_the_threshold_pass_also_checks_every_agents_own_limit():
    service = budget_service([], {})
    with configured():
        service.check_llm_budget_thresholds()
    service.agent_budgets.check_llm_budget_thresholds.assert_called_once_with()


# --- the Organization's own view --------------------------------------------


def org_budget_service(organization, **overrides):
    repo = MagicMock()
    repo.get.return_value = organization
    return organization_service(organization_repository=repo, **overrides)


def viewed(limit=50.0, spend=40.0, renews="2026-10-01T00:00:00Z", observed=True, own=None):
    from datetime import UTC, datetime

    from api.domains.organizations.models import Organization

    return Organization(
        id=ORG,
        name="Acme",
        llm_budget_usd=limit,
        llm_budget_duration="30d",
        llm_own_budget_usd=own,
        llm_spend_usd=spend,
        llm_spend_observed_at=datetime.now(UTC) if observed else None,
        llm_budget_renews_at=datetime.fromisoformat(renews) if renews else None,
    )


def test_an_organization_sees_its_own_limit_and_usage():
    service = org_budget_service(viewed())
    read = service.get_organization_llm_budget(ORG, MagicMock())
    assert_that(read.limit_usd, equal_to(50.0))
    assert_that(read.spend_usd, equal_to(40.0))
    assert_that(read.state, equal_to("warning"))


def test_reading_the_budget_requires_cost_read():
    service = org_budget_service(viewed())
    service.get_organization_llm_budget(ORG, MagicMock())
    key = service.permission_policy.require_organization.call_args.args[2]
    assert_that(str(key.value), equal_to("cost.read"))


@pytest.mark.parametrize(
    "spend,limit,expected",
    [(10.0, 50.0, "ok"), (40.0, 50.0, "warning"), (50.0, 50.0, "exhausted"), (60.0, 50.0, "exhausted")],
)
def test_state_follows_spend_against_the_limit(spend, limit, expected):
    service = org_budget_service(viewed(limit=limit, spend=spend))
    assert_that(service.get_organization_llm_budget(ORG, MagicMock()).state, equal_to(expected))


def test_the_organizations_own_limit_is_the_one_in_force():
    service = org_budget_service(viewed(limit=100.0, own=40.0, spend=35.0))
    read = service.get_organization_llm_budget(ORG, MagicMock())
    assert_that((read.limit_usd, read.ceiling_usd, read.own_limit_usd), equal_to((40.0, 100.0, 40.0)))
    # Spend is measured against the limit in force, not the ceiling.
    assert_that(read.state, equal_to("warning"))


def test_a_limit_with_no_observation_yet_is_unknown_not_zero():
    service = org_budget_service(viewed(spend=None, observed=False))
    read = service.get_organization_llm_budget(ORG, MagicMock())
    assert_that(read.state, equal_to("unknown"))
    assert_that(read.spend_usd, equal_to(None))


# --- configurable thresholds -------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, [80, 100]),
        ("", [80, 100]),
        ("50,80,100", [50, 80, 100]),
        ("100,50", [50, 100]),
        ("90, 90 ,100", [90, 100]),
    ],
)
def test_thresholds_parse_and_normalise(raw, expected):
    values = {} if raw is None else {"organization_llm_budget_alert_thresholds": raw}
    assert_that(config(**values).llm_budget_alert_thresholds, equal_to(expected))


@pytest.mark.parametrize("raw", ["0,80", "101", "-5", "eighty", "80;100"])
def test_invalid_thresholds_are_rejected(raw):
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        config(organization_llm_budget_alert_thresholds=raw)


def test_a_configured_threshold_fires_instead_of_the_default():
    service = budget_service([capped()], {"org": status_at(25.0)})
    with patch(
        "api.domains.organizations.llm_budget_service.get_config",
        return_value=config(organization_llm_budget_alert_thresholds="50,100"),
    ):
        fired = service.check_llm_budget_thresholds()
    assert_that([f.threshold_percent for f in fired], equal_to([50]))


def test_the_warning_state_follows_the_lowest_configured_threshold():
    service = org_budget_service(viewed(limit=50.0, spend=27.0))
    with patch(
        "api.domains.organizations.llm_budget_service.get_config",
        return_value=config(organization_llm_budget_alert_thresholds="50,100"),
    ):
        assert_that(service.get_organization_llm_budget(ORG, MagicMock()).state, equal_to("warning"))


# --- the notification itself -------------------------------------------------


def budget_email_handler(recipients, already=None):
    from api.domains.organizations.event_handlers import OrganizationBudgetEmailHandler

    repo = MagicMock()
    repo.find_budget_email_recipients.return_value = recipients
    repo.find_notified_budget_recipients.return_value = already or set()
    return OrganizationBudgetEmailHandler(repository=repo, email_service=MagicMock())


def budget_event(name, threshold=80, spend=40.0, limit=50.0, renews="2026-10-01T00:00:00Z"):
    return MagicMock(
        event_name=name,
        organization_id=ORG,
        payload={
            "organization_id": ORG,
            "threshold_percent": threshold,
            "spend_usd": spend,
            "limit_usd": limit,
            "renews_at": renews,
            "subject_display": "Acme",
        },
    )


def delivery_context():
    return MagicMock(delivery_id="delivery-1")


def test_a_warning_email_states_usage_without_naming_any_system():
    from api.domains.events.catalog import ORGANIZATION_LLM_BUDGET_THRESHOLD_REACHED

    handler = budget_email_handler([("owner@example.com", "Grace")])
    handler.handle(budget_event(ORGANIZATION_LLM_BUDGET_THRESHOLD_REACHED), delivery_context())
    sent = handler.email_service.send_organization_budget_email.call_args.kwargs
    assert_that(sent["headline"], equal_to("80% of your model spend limit used"))
    assert_that("$40.00 of $50.00" in sent["body"], equal_to(True))
    for leak in ("litellm", "LiteLLM", "team", "proxy", "cost_record"):
        assert_that(leak in sent["body"] or leak in sent["headline"], equal_to(False))


def test_an_exhausted_email_says_what_stopped_working():
    from api.domains.events.catalog import ORGANIZATION_LLM_BUDGET_EXHAUSTED

    handler = budget_email_handler([("owner@example.com", "Grace")])
    handler.handle(budget_event(ORGANIZATION_LLM_BUDGET_EXHAUSTED, threshold=100, spend=50.0), delivery_context())
    sent = handler.email_service.send_organization_budget_email.call_args.kwargs
    assert_that(sent["headline"], equal_to("Model spend limit reached"))
    assert_that("can't make model calls" in sent["body"], equal_to(True))


def test_every_owner_and_admin_is_emailed():
    from api.domains.events.catalog import ORGANIZATION_LLM_BUDGET_EXHAUSTED

    handler = budget_email_handler([("a@example.com", "A"), ("b@example.com", None)])
    handler.handle(budget_event(ORGANIZATION_LLM_BUDGET_EXHAUSTED), delivery_context())
    assert_that(handler.email_service.send_organization_budget_email.call_count, equal_to(2))


def test_a_retry_skips_recipients_already_emailed():
    from api.domains.events.catalog import ORGANIZATION_LLM_BUDGET_EXHAUSTED

    handler = budget_email_handler([("a@example.com", "A"), ("b@example.com", "B")], already={"a@example.com"})
    handler.handle(budget_event(ORGANIZATION_LLM_BUDGET_EXHAUSTED), delivery_context())
    sent = [c.kwargs["receiver_email"] for c in handler.email_service.send_organization_budget_email.call_args_list]
    assert_that(sent, equal_to(["b@example.com"]))


def test_a_transient_failure_asks_for_a_retry():
    from api.domains.events.catalog import ORGANIZATION_LLM_BUDGET_EXHAUSTED
    from api.domains.events.handlers import RetryableEventHandlerError
    from api.infrastructure.email.exceptions import RetryableEmailSendingException

    handler = budget_email_handler([("a@example.com", "A")])
    handler.email_service.send_organization_budget_email.side_effect = RetryableEmailSendingException(
        "smtp down", email="a@example.com"
    )
    with pytest.raises(RetryableEventHandlerError):
        handler.handle(budget_event(ORGANIZATION_LLM_BUDGET_EXHAUSTED), delivery_context())


def test_a_sub_dollar_allowance_keeps_its_precision():
    from api.domains.events.catalog import ORGANIZATION_LLM_BUDGET_EXHAUSTED

    handler = budget_email_handler([("a@example.com", "A")])
    handler.handle(budget_event(ORGANIZATION_LLM_BUDGET_EXHAUSTED, spend=0.011985, limit=0.01), delivery_context())
    body = handler.email_service.send_organization_budget_email.call_args.kwargs["body"]
    assert_that("$0.0120 of $0.0100" in body, equal_to(True))


def budget_handler_with_platform(recipients, platform_admins, already=None):
    handler = budget_email_handler(recipients, already)
    handler.repository.find_platform_admin_recipients.return_value = platform_admins
    return handler


def _sent(handler):
    return [c.kwargs["receiver_email"] for c in handler.email_service.send_organization_budget_email.call_args_list]


def test_platform_admins_are_told_when_an_organization_is_cut_off():
    from api.domains.events.catalog import ORGANIZATION_LLM_BUDGET_EXHAUSTED

    handler = budget_handler_with_platform([("owner@acme.com", "Owner")], [("ops@platform.com", "Ops")])
    handler.handle(budget_event(ORGANIZATION_LLM_BUDGET_EXHAUSTED, threshold=100), delivery_context())
    assert_that(sorted(_sent(handler)), equal_to(["ops@platform.com", "owner@acme.com"]))


def test_platform_admins_are_not_told_about_a_warning():
    """An Organization approaching its limit is its own business; being cut off is
    a support ticket heading our way."""
    from api.domains.events.catalog import ORGANIZATION_LLM_BUDGET_THRESHOLD_REACHED

    handler = budget_handler_with_platform([("owner@acme.com", "Owner")], [("ops@platform.com", "Ops")])
    handler.handle(budget_event(ORGANIZATION_LLM_BUDGET_THRESHOLD_REACHED), delivery_context())
    assert_that(_sent(handler), equal_to(["owner@acme.com"]))
    handler.repository.find_platform_admin_recipients.assert_not_called()


def test_someone_who_is_both_is_emailed_once():
    from api.domains.events.catalog import ORGANIZATION_LLM_BUDGET_EXHAUSTED

    handler = budget_handler_with_platform([("both@acme.com", "Both")], [("both@acme.com", "Both")])
    handler.handle(budget_event(ORGANIZATION_LLM_BUDGET_EXHAUSTED, threshold=100), delivery_context())
    assert_that(_sent(handler), equal_to(["both@acme.com"]))


def test_each_audience_is_told_why_it_received_the_mail():
    from api.domains.events.catalog import ORGANIZATION_LLM_BUDGET_EXHAUSTED

    handler = budget_handler_with_platform([("owner@acme.com", "Owner")], [("ops@platform.com", "Ops")])
    handler.handle(budget_event(ORGANIZATION_LLM_BUDGET_EXHAUSTED, threshold=100), delivery_context())
    reasons = {
        c.kwargs["receiver_email"]: c.kwargs["reason"]
        for c in handler.email_service.send_organization_budget_email.call_args_list
    }
    assert_that("owner or admin" in reasons["owner@acme.com"], equal_to(True))
    assert_that("platform administrator" in reasons["ops@platform.com"], equal_to(True))


def test_the_budget_email_renders_with_every_attribute_it_is_given():
    """Rendering is the only place a template/attribute mismatch shows up — the send
    path returns early when delivery is disabled, so nothing else would catch it."""
    from unittest.mock import MagicMock as Mock

    from api.core.config import get_config
    from api.infrastructure.email.models import EmailTemplate, EmailTemplateAttribute
    from api.infrastructure.email.service import EmailService

    service = EmailService.__new__(EmailService)
    service.config = get_config()
    service.client = Mock()
    template = EmailTemplate(
        file_name="organization-budget-template.mjml",
        subject="Model spend limit reached",
        receiver_name="Grace",
        receiver_email="owner@example.com",
        attributes=[
            EmailTemplateAttribute(name="user_name", value="Grace"),
            EmailTemplateAttribute(name="organization_name", value="Northwind Labs"),
            EmailTemplateAttribute(name="headline", value="Model spend limit reached"),
            EmailTemplateAttribute(name="body", value="Used its entire model spend limit."),
            EmailTemplateAttribute(name="reason", value="You received this because you are a platform administrator."),
        ],
    )
    html = service.create_email(template).html_part
    # The Organization has to be named: a platform administrator receiving this needs
    # to know which one it is about.
    for expected in ("Northwind Labs", "Model spend limit reached", "platform administrator", "Grace"):
        assert_that(expected in html, equal_to(True))
    for leak in ("litellm", "LiteLLM", "cost_record", "team_id"):
        assert_that(leak in html, equal_to(False))


def test_a_threshold_is_only_recorded_once_its_notification_is_staged():
    """Recording first and publishing after means a failed publish silences that
    threshold for the rest of the window — the alert is never retried."""
    org = capped()
    service = budget_service([org], {"org": status_at(45.0)}, publishes=False)
    with configured():
        fired = service.check_llm_budget_thresholds()
    assert_that(fired, equal_to([]))
    assert_that(org.llm_alerted_threshold, equal_to(None))
    # The spend snapshot is still worth keeping; only the alert state is withheld.
    assert_that(org.llm_spend_usd, equal_to(45.0))


def test_a_recorded_threshold_survives_into_the_next_pass():
    org = capped()
    service = budget_service([org], {"org": status_at(45.0)})
    with configured():
        service.check_llm_budget_thresholds()
    assert_that(org.llm_alerted_threshold, equal_to(80))


def test_a_silently_ignored_budget_clear_is_not_reported_as_success():
    """Some versions accept an update and drop fields they do not recognise. Without
    the re-read, "Remove limit" would leave the cap enforced while the row and the UI
    both say there is none."""
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[
                team(max_budget=50, budget_duration="30d"),
                team(max_budget=50, budget_duration="30d"),  # the clear did not take
            ],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})),
    ):
        with pytest.raises(LiteLLMError):
            client().apply_team_budget("org", None, None)


def test_a_configured_list_without_100_still_alerts_on_exhaustion():
    """100% is the enforcement boundary, not a notification preference: the banner
    says exhausted regardless, so an alert list that omits it leaves the two
    surfaces disagreeing and the "allowance reached" mail never sent."""
    service = budget_service([capped()], {"org": status_at(50.0)})
    with patch(
        "api.domains.organizations.llm_budget_service.get_config",
        return_value=config(organization_llm_budget_alert_thresholds="50,90"),
    ):
        fired = service.check_llm_budget_thresholds()
    assert_that([f.threshold_percent for f in fired], equal_to([100]))


def test_100_is_always_present_however_the_list_is_configured():
    assert_that(config(organization_llm_budget_alert_thresholds="50").llm_budget_alert_thresholds, equal_to([50, 100]))
    assert_that(config(organization_llm_budget_alert_thresholds="100").llm_budget_alert_thresholds, equal_to([100]))


# --- cost of a sweep ---------------------------------------------------------


def test_the_master_key_is_read_once_not_per_call():
    """Every client call resolved it through the Kubernetes API; a coverage sweep
    paid that per Agent on top of the proxy call."""
    import base64

    k8s = MagicMock()
    k8s.get_secret.return_value = MagicMock(data={"LITELLM_MASTER_KEY": base64.b64encode(b"master").decode()})
    c = LiteLLMClient(k8s, config())
    with patch("api.infrastructure.litellm.client.httpx.get", return_value=key_info("org")):
        c.get_key_team("sk-a")
        c.get_key_team("sk-b")
        c.get_key_team("sk-c")
    assert_that(k8s.get_secret.call_count, equal_to(1))


def test_enrolling_does_not_re_read_a_team_the_caller_already_knows():
    """attach_key_to_team read /key/info before the update and again after; the
    caller had just read it to decide the key needed enrolling at all."""
    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", return_value=key_info("org")) as get,
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})) as post,
    ):
        client().attach_key_to_team(SECRET_KEY, "org", current_team=None)
    # One read: the verification after the write. The pre-read is the caller's.
    assert_that(get.call_count, equal_to(1))
    assert_that(post.call_args.args[0], equal_to(KEY_UPDATE))


def test_a_key_is_looked_up_by_hash_so_it_never_enters_a_query_string():
    """A query string reaches the proxy's access log, any intermediate proxy and log
    aggregation — for every Agent, on every sweep."""
    import hashlib

    with (
        patch.object(LiteLLMClient, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", return_value=key_info("org")) as get,
    ):
        client().get_key_team(SECRET_KEY)
    sent = get.call_args.kwargs["params"]["key"]
    assert_that(sent, equal_to(hashlib.sha256(SECRET_KEY.encode()).hexdigest()))
    assert_that(SECRET_KEY in str(get.call_args), equal_to(False))

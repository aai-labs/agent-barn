from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx
import pytest
from hamcrest import assert_that, equal_to
from pydantic import ValidationError

from api.core.config import Config
from api.domains.organizations.llm import OrganizationLLMService
from api.infrastructure.litellm.client import LiteLLMClient, LiteLLMError


def config(**values):
    return Config.model_validate(
        {
            "db_connection_url": "postgresql://test:test@localhost/test",
            "secret_signing_key": "test",
            "platform_admin_credentials": "test:test",
            "litellm_base_url": "http://litellm",
            "litellm_secret_name": "litellm",
            "organization_llm_budget_usd": None,
            "organization_llm_budget_duration": "30d",
            **values,
        }
    )


def response(data, code=200):
    return httpx.Response(code, json=data, request=httpx.Request("GET", "http://litellm"))


@pytest.mark.parametrize("value", [None, "", "  "])
def test_unset_budget_is_unlimited(value):
    assert_that(config(organization_llm_budget_usd=value).organization_llm_budget_usd, equal_to(None))


@pytest.mark.parametrize("value", [-1, "nan", "inf", "bad"])
def test_invalid_budget_rejected(value):
    with pytest.raises(ValidationError):
        config(organization_llm_budget_usd=value)


@pytest.mark.parametrize("value", ["0d", "-1d", "monthly", "1.5d"])
def test_invalid_duration_rejected(value):
    with pytest.raises(ValidationError):
        config(organization_llm_budget_duration=value)


def test_zero_budget_is_not_unlimited():
    assert_that(config(organization_llm_budget_usd="0").organization_llm_budget_usd, equal_to(0))


@pytest.mark.parametrize("budget", [None, 0, 50])
def test_new_team_has_org_identity_and_optional_budget(budget):
    client = LiteLLMClient(MagicMock(), config(organization_llm_budget_usd=budget))
    duration = "30d" if budget is not None else None
    with (
        patch.object(client, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[
                response({}, 404),
                response({"team_info": {"team_id": "org", "max_budget": budget, "budget_duration": duration}}),
            ],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})) as post,
    ):
        client.ensure_organization_team("org")
    assert_that(post.call_count, equal_to(1))
    assert_that(
        post.call_args.kwargs["json"],
        equal_to({"team_id": "org", "team_alias": "agentbarn-org", "max_budget": budget, "budget_duration": duration}),
    )


def test_unchanged_policy_does_not_reset_budget_window_or_spend():
    client = LiteLLMClient(MagicMock(), config(organization_llm_budget_usd=50))
    with (
        patch.object(client, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            return_value=response(
                {
                    "team_info": {
                        "team_id": "org",
                        "max_budget": 50,
                        "budget_duration": "30d",
                        "spend": 42,
                        "budget_reset_at": "later",
                    }
                }
            ),
        ),
        patch("api.infrastructure.litellm.client.httpx.post") as post,
    ):
        client.ensure_organization_team("org")
    post.assert_not_called()


@pytest.mark.parametrize(
    "budget,duration,expected",
    [
        (75, "30d", {"max_budget": 75}),
        (None, "30d", {"max_budget": None, "budget_duration": None}),
        (50, "7d", {"budget_duration": "7d"}),
    ],
)
def test_policy_changes_patch_only_changed_fields(budget, duration, expected):
    client = LiteLLMClient(
        MagicMock(), config(organization_llm_budget_usd=budget, organization_llm_budget_duration=duration)
    )
    with (
        patch.object(client, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            return_value=response(
                {"team_info": {"team_id": "org", "max_budget": 50, "budget_duration": "30d", "spend": 42}}
            ),
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({})) as post,
    ):
        client.ensure_organization_team("org")
    assert_that(post.call_args.kwargs["json"], equal_to({"team_id": "org", **expected}))


def test_concurrent_team_creation_is_verified_by_reread():
    client = LiteLLMClient(MagicMock(), config())
    with (
        patch.object(client, "_master_key", return_value="master"),
        patch(
            "api.infrastructure.litellm.client.httpx.get",
            side_effect=[response({}, 404), response({"team_info": {"team_id": "org"}})],
        ),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({}, 400)),
    ):
        client.ensure_organization_team("org")


def test_failed_team_creation_never_issues_key():
    client = LiteLLMClient(MagicMock(), config())
    with (
        patch.object(client, "_master_key", return_value="master"),
        patch("api.infrastructure.litellm.client.httpx.get", return_value=response({}, 404)),
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({}, 403)) as post,
    ):
        with pytest.raises(LiteLLMError):
            client.generate_key("agent", "Agent", "org")
    assert_that([call.args[0] for call in post.call_args_list], equal_to(["http://litellm/team/new"]))


def test_generated_key_has_team_and_existing_attribution_metadata():
    client = LiteLLMClient(MagicMock(), config())
    with (
        patch.object(client, "_master_key", return_value="master"),
        patch.object(client, "ensure_organization_team") as ensure,
        patch("api.infrastructure.litellm.client.httpx.post", return_value=response({"key": "sk-test"})) as post,
    ):
        assert_that(client.generate_key("agent", "Agent", "org"), equal_to("sk-test"))
    ensure.assert_called_once_with("org")
    assert_that(
        post.call_args.kwargs["json"],
        equal_to(
            {"key_alias": "Agent-agent", "team_id": "org", "metadata": {"agent_id": "agent", "organization_id": "org"}}
        ),
    )


def test_reconciliation_applies_policy_to_each_organization():
    orgs = [uuid4(), uuid4()]
    repository = MagicMock()
    repository.list_ids_for_llm_reconciliation.return_value = orgs
    client = MagicMock()
    OrganizationLLMService(config(), client, repository).reconcile()
    assert_that(
        [call.args for call in client.ensure_organization_team.call_args_list], equal_to([(str(org),) for org in orgs])
    )


def test_no_litellm_skips_all_provisioning():
    client = MagicMock()
    repo = MagicMock()
    service = OrganizationLLMService(config(litellm_base_url=""), client, repo)
    service.provision_after_commit(uuid4())
    service.reconcile()
    client.ensure_organization_team.assert_not_called()
    repo.list_ids_for_llm_reconciliation.assert_not_called()


def test_committed_creation_survives_remote_failure_without_logging_secrets():
    client = MagicMock()
    client.ensure_organization_team.side_effect = LiteLLMError("sk-secret")
    service = OrganizationLLMService(config(), client, MagicMock())
    org_id = uuid4()
    with patch("api.domains.organizations.llm.logger") as logger:
        service.provision_after_commit(org_id)
    logger.error.assert_called_once_with(
        "LiteLLM team provisioning deferred for Organization %s (%s)", org_id, "LiteLLMError"
    )


@pytest.mark.parametrize("fails", [False, True])
def test_startup_reconciles_before_serving_and_aborts_on_failure(fails):
    import asyncio

    from api.api_app import lifespan

    injector = MagicMock()
    llm = MagicMock()
    injector.get.side_effect = lambda cls: llm if cls is OrganizationLLMService else MagicMock()
    if fails:
        llm.reconcile.side_effect = LiteLLMError("unavailable")

    async def run():
        with (
            patch("api.api_app.create_injector", return_value=injector),
            patch("api.api_app.get_config", return_value=config()),
            patch("api.api_app.seed_aai_cli_skills"),
        ):
            if fails:
                with pytest.raises(RuntimeError, match="Organization LiteLLM reconciliation failed"):
                    async with lifespan(MagicMock()):
                        pytest.fail("Must not serve after incomplete reconciliation")
            else:
                async with lifespan(MagicMock()):
                    llm.reconcile.assert_called_once_with()

    asyncio.run(run())

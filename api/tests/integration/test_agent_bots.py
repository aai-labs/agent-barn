import json
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import UUID, uuid7

import pytest
import yaml
from fastapi import status
from hamcrest import assert_that, contains_inanyorder, contains_string, equal_to, has_item, is_not

from api.core.config import Config as AppConfig
from api.domains.agents.models import AgentStatus, AgentType, pod_agent_id
from api.domains.agents.repository import AgentRepository
from api.domains.agents.service import AgentService
from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID, AGENT_OWNER_ROLE_ID, AGENT_VIEWER_ROLE_ID
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.litellm.client import LiteLLMClient
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.integration.test_organization_agent_limits import a_platform_administrator_is_signed_in
from api.tests.steps.agent import (
    FAKE_LITELLM_KEY,
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_agent_access,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization, there_is_an_organization_with_user_and_access_token
from api.tests.steps.resource_usage import MockPrometheusModule
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

BASE = "/api/v1/organizations/{organization_id}/agents"
ROUTE_MISSING = "Not Found"
CREATE = {"name": "Sales", "template_key": "test-template"}
RESTORE_POINT = "01a1b000-0000-7000-8000-000000000000"
POD_OPERATIONS = [
    ("post", "/start", None),
    ("post", "/stop", None),
    ("post", "/managed-update", None),
    ("put", "/agent-size", {"agent_size_id": None}),
    ("post", "/restore-points", {}),
    ("post", f"/restore-points/{RESTORE_POINT}/restore", {}),
    ("delete", f"/restore-points/{RESTORE_POINT}", None),
    ("get", "/logs", None),
    ("get", "/logs/history", None),
    ("get", "/logs/stream", None),
    ("get", "/diagnostics", None),
    ("get", "/resource-usage", None),
    ("put", "/file-sync", {"enabled": True}),
]
_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), MockPrometheusModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
]


def _auth(context):
    return {"Authorization": f"Bearer {context.access_token}"}


def _parent_with_bots(*slots, status=AgentStatus.STOPPED):
    def step(context):
        there_is_an_agent(name="Parent", agent_type=AgentType.HERMES, status=status)(context)
        context.parent = context.agent
        context.bots = []
        for slot in slots:
            there_is_an_agent(
                name=f"Bot {slot}",
                agent_type=AgentType.HERMES,
                status=status,
                parent_agent_id=context.parent.id,
                bot_slot=slot,
            )(context)
            context.bots.append(context.agent)
        context.bot = context.bots[0] if context.bots else None

    return step


def _member(context):
    owner_token = context.access_token
    member_id = uuid7()
    there_is_a_user(
        id=member_id,
        email=f"member-{member_id}@example.com",
        role=OrganizationRole.MEMBER,
        organization_id=context.organization.id,
    )(context)
    context.member_id = member_id
    context.member_membership_id = context.organization_user.id
    context.access_token = owner_token


def _act_as_member(context):
    there_is_an_access_token_for_user(context.member_id)(context)


def _grant(context, agent, role_id):
    there_is_agent_access(membership_id=context.member_membership_id, agent_id=agent.id, access_role_id=role_id)(
        context
    )


def _get(context, path):
    return context.client.get(f"{BASE}{path}", headers=_auth(context))


def _share(context, agent, *, general_access_role_id=None, assignments=()):
    return context.client.put(
        f"{BASE}/{agent.id}/share",
        json={
            "general_access_role_id": str(general_access_role_id) if general_access_role_id else None,
            "assignments": [{"user_id": str(user_id), "access_role_id": str(role)} for user_id, role in assignments],
        },
        headers=_auth(context),
    )


def _names(response):
    return [item["name"] for item in response.json()["items"]]


def test_bots_are_left_out_of_the_agent_list():
    with given([*_GIVEN, _parent_with_bots(1, 2)]) as context:
        response = _get(context, "")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(_names(response), equal_to(["Parent"]))
        assert_that(response.json()["total"], equal_to(1))


def test_a_bot_is_reachable_by_its_own_id():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        response = _get(context, f"/{context.bot.id}")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["parent_agent_id"], equal_to(str(context.parent.id)))


def test_an_agent_without_a_parent_reads_a_null_parent():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        response = _get(context, f"/{context.parent.id}")

        assert_that(response.json()["parent_agent_id"], equal_to(None))


def test_the_bots_route_lists_a_parents_bots_in_slot_order():
    with given([*_GIVEN, _parent_with_bots(2, 1)]) as context:
        response = _get(context, f"/{context.parent.id}/bots")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that([bot["name"] for bot in response.json()], equal_to(["Bot 1", "Bot 2"]))


def test_an_agent_without_bots_lists_none():
    with given([*_GIVEN, _parent_with_bots()]) as context:
        response = _get(context, f"/{context.parent.id}/bots")

        assert_that(response.json(), equal_to([]))


def test_a_deleted_bot_is_gone_from_the_list_and_its_own_route():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        there_is_an_agent(
            name="Deleted bot",
            agent_type=AgentType.HERMES,
            parent_agent_id=context.parent.id,
            bot_slot=2,
            deleted=True,
        )(context)

        listed = _get(context, f"/{context.parent.id}/bots")
        direct = _get(context, f"/{context.agent.id}")

        assert_that([bot["name"] for bot in listed.json()], equal_to(["Bot 1"]))
        assert_that(direct.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_another_organizations_parent_is_not_found():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        parent_id = context.parent.id
        there_is_an_organization(name="Other Organization")(context)
        there_is_an_organization_with_user_and_access_token()(context)
        use_org_for_auth()(context)

        response = _get(context, f"/{parent_id}/bots")

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(response.json()["detail"], is_not(equal_to(ROUTE_MISSING)))


def test_a_member_with_no_access_cannot_see_bots():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        _member(context)
        _act_as_member(context)

        assert_that(_get(context, f"/{context.bot.id}").status_code, equal_to(status.HTTP_404_NOT_FOUND))
        listed = _get(context, f"/{context.parent.id}/bots")
        assert_that(listed.status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(listed.json()["detail"], is_not(equal_to(ROUTE_MISSING)))


def test_access_to_the_parent_reaches_its_bots():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        _member(context)
        _grant(context, context.parent, AGENT_VIEWER_ROLE_ID)
        _act_as_member(context)

        bot = _get(context, f"/{context.bot.id}")
        listed = _get(context, f"/{context.parent.id}/bots")

        assert_that(bot.status_code, equal_to(status.HTTP_200_OK))
        assert_that(bot.json()["allowed_actions"], is_not(has_item("agent.update")))
        assert_that([item["name"] for item in listed.json()], equal_to(["Bot 1"]))


def test_general_access_on_the_parent_reaches_its_bots():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        _member(context)
        assert_that(
            _share(context, context.parent, general_access_role_id=AGENT_VIEWER_ROLE_ID).status_code,
            equal_to(status.HTTP_200_OK),
        )
        _act_as_member(context)

        assert_that(_get(context, f"/{context.bot.id}").status_code, equal_to(status.HTTP_200_OK))


def test_a_bot_grant_adds_to_the_parents_grant():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        _member(context)
        _grant(context, context.parent, AGENT_VIEWER_ROLE_ID)
        _grant(context, context.bot, AGENT_EDITOR_ROLE_ID)
        _act_as_member(context)

        bot = _get(context, f"/{context.bot.id}").json()
        parent = _get(context, f"/{context.parent.id}").json()

        assert_that(bot["allowed_actions"], has_item("agent.update"))
        assert_that(parent["allowed_actions"], is_not(has_item("agent.update")))


def test_a_bot_cannot_be_shared_with_a_member_who_cannot_read_its_parent():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        _member(context)

        response = _share(context, context.bot, assignments=[(context.member_id, AGENT_VIEWER_ROLE_ID)])

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_a_bot_can_be_shared_with_a_member_who_reads_its_parent():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        _member(context)
        _grant(context, context.parent, AGENT_VIEWER_ROLE_ID)

        response = _share(context, context.bot, assignments=[(context.member_id, AGENT_EDITOR_ROLE_ID)])

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_general_access_on_a_bot_needs_general_access_on_its_parent():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        refused = _share(context, context.bot, general_access_role_id=AGENT_VIEWER_ROLE_ID)
        _share(context, context.parent, general_access_role_id=AGENT_VIEWER_ROLE_ID)
        allowed = _share(context, context.bot, general_access_role_id=AGENT_EDITOR_ROLE_ID)

        assert_that(refused.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(allowed.status_code, equal_to(status.HTTP_200_OK))


def test_a_bots_lifecycle_lock_is_its_parents():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        repository = context.injector.get(AgentRepository)

        with repository.lifecycle_lock(context.parent.id) as parent_acquired:
            with repository.lifecycle_lock(context.bot.id) as bot_acquired:
                assert_that((parent_acquired, bot_acquired), equal_to((True, False)))


def test_a_bot_runs_in_its_parents_pod():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        assert_that(pod_agent_id(context.bot), equal_to(context.parent.id))
        assert_that(pod_agent_id(context.parent), equal_to(context.parent.id))


def test_platform_pod_queries_leave_out_bots():
    with given([*_GIVEN, _parent_with_bots(1, status=AgentStatus.RUNNING)]) as context:
        repository = context.injector.get(AgentRepository)

        running = [agent.id for agent in repository.find_all_running()]
        live = [identity.id for identity in repository.find_live_for_platform_usage()]

        assert_that(running, contains_inanyorder(context.parent.id))
        assert_that(live, contains_inanyorder(context.parent.id))


def _create_bot(context, parent, **fields):
    return context.client.post(f"{BASE}/{parent.id}/bots", json={**CREATE, **fields}, headers=_auth(context))


def _stored(context, agent_id):
    return context.injector.get(AgentRepository).get_by_id(UUID(str(agent_id)))


def _organization_may_run(limit):
    def step(context):
        organizations = context.injector.get(OrganizationRepository)
        organization = organizations.get(context.organization.id)
        organization.agent_limit = limit
        organizations.save(organization)

    return step


def test_creating_a_bot_makes_a_stopped_hermes_agent_inside_its_parent():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots()]) as context:
        response = _create_bot(context, context.parent)

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        body = response.json()
        assert_that(body["parent_agent_id"], equal_to(str(context.parent.id)))
        assert_that(body["agent_type"], equal_to("hermes"))
        assert_that(body["status"], equal_to("STOPPED"))
        stored = _stored(context, body["id"])
        assert_that((stored.bot_slot, stored.file_sync_enabled), equal_to((1, False)))


def test_a_new_bot_takes_its_parents_turn_limit():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots()]) as context:
        context.parent.max_turns = 77
        context.injector.get(AgentRepository).save(context.parent)

        response = _create_bot(context, context.parent)

        assert_that(_stored(context, response.json()["id"]).max_turns, equal_to(77))


def test_a_new_bot_takes_the_lowest_free_slot():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots(1, 3)]) as context:
        response = _create_bot(context, context.parent)

        assert_that(_stored(context, response.json()["id"]).bot_slot, equal_to(2))


def test_a_deleted_bots_slot_is_reused():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots(1)]) as context:
        context.bot.deleted_at = datetime.now(UTC)
        context.injector.get(AgentRepository).save(context.bot)

        response = _create_bot(context, context.parent)

        assert_that(_stored(context, response.json()["id"]).bot_slot, equal_to(1))


def test_a_sixth_bot_is_refused():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots(1, 2, 3, 4, 5)]) as context:
        response = _create_bot(context, context.parent)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(response.json()["detail"], contains_string("5"))


def test_a_bot_counts_toward_the_organizations_agent_limit():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots(1), _organization_may_run(2)]) as context:
        response = _create_bot(context, context.parent)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(response.json()["detail"], contains_string("2 agents"))


def test_an_openclaw_agent_cannot_hold_bots():
    with given([*_GIVEN, there_is_a_template(), there_is_an_agent(agent_type=AgentType.OPENCLAW)]) as context:
        response = _create_bot(context, context.agent)

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_a_bot_cannot_hold_bots():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots(1)]) as context:
        response = _create_bot(context, context.bot)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(response.json()["detail"], contains_string("Bot"))


def test_a_running_parent_refuses_a_new_bot():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots(status=AgentStatus.RUNNING)]) as context:
        response = _create_bot(context, context.parent)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_a_parent_in_a_managed_update_refuses_a_new_bot():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots()]) as context:
        context.parent.managed_update_heartbeat_at = datetime.now(UTC)
        context.injector.get(AgentRepository).save(context.parent)

        response = _create_bot(context, context.parent)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_a_parent_mid_lifecycle_refuses_a_new_bot():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots()]) as context:
        with context.injector.get(AgentRepository).lifecycle_lock(context.parent.id):
            response = _create_bot(context, context.parent)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_an_unknown_template_is_not_found():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots()]) as context:
        response = _create_bot(context, context.parent, template_key="missing")

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(response.json()["detail"], contains_string("missing"))


def test_settings_a_bot_cannot_choose_are_rejected():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots()]) as context:
        for field, value in (
            ("agent_type", "hermes"),
            ("file_sync_enabled", True),
            ("agent_size_id", str(uuid7())),
            ("max_turns", 10),
        ):
            response = _create_bot(context, context.parent, **{field: value})

            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_a_viewer_of_the_parent_cannot_create_a_bot():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots()]) as context:
        _member(context)
        _grant(context, context.parent, AGENT_VIEWER_ROLE_ID)
        _act_as_member(context)

        assert_that(_create_bot(context, context.parent).status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_member_with_no_access_to_the_parent_gets_not_found():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots()]) as context:
        _member(context)
        _act_as_member(context)

        response = _create_bot(context, context.parent)

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(response.json()["detail"], is_not(equal_to(ROUTE_MISSING)))


def test_an_editor_of_the_parent_creates_a_bot_and_owns_it():
    with given([*_GIVEN, there_is_a_template(), _parent_with_bots()]) as context:
        _member(context)
        _grant(context, context.parent, AGENT_EDITOR_ROLE_ID)
        _act_as_member(context)

        response = _create_bot(context, context.parent)

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(response.json()["allowed_actions"], has_item("agent.lifecycle.manage"))


def _k8s(context):
    return context.injector.get(KubernetesClient)


def _call(context, method, path, body=None):
    kwargs = {} if body is None else {"json": body}
    return context.client.request(method, path, headers=_auth(context), **kwargs)


def _deleted_names(mock_method):
    return [call.args[0] for call in mock_method.call_args_list]


@pytest.mark.parametrize(("method", "suffix", "body"), POD_OPERATIONS)
def test_a_pod_operation_on_a_bot_is_refused_and_names_its_parent(method, suffix, body):
    with given([*_GIVEN, _parent_with_bots(1, status=AgentStatus.RUNNING)]) as context:
        response = _call(context, method, f"{BASE}/{context.bot.id}{suffix}", body)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT), suffix)
        assert_that(response.json()["detail"], contains_string(str(context.parent.id)))
        assert_that(_k8s(context).create_deployment.called, equal_to(False))
        assert_that(_k8s(context).delete_deployment.called, equal_to(False))


def test_a_pod_operation_on_a_bot_stays_hidden_from_someone_with_no_access():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        _member(context)
        _act_as_member(context)

        response = _call(context, "post", f"{BASE}/{context.bot.id}/start")

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_a_platform_administrator_cannot_resize_or_restart_a_bot():
    with given([*_GIVEN, _parent_with_bots(1), a_platform_administrator_is_signed_in()]) as context:
        size = _call(context, "put", f"/api/v1/platform/agents/{context.bot.id}/agent-size", {"agent_size_id": None})
        restart = _call(context, "post", f"/api/v1/platform/agents/{context.bot.id}/restart")

        assert_that(size.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(restart.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_a_bots_health_comes_from_its_parents_pod():
    with given([*_GIVEN, _parent_with_bots(1, status=AgentStatus.RUNNING)]) as context:
        _k8s(context).fetch_agent_healthz.return_value = {"status": "ok"}

        response = _call(context, "get", f"{BASE}/{context.bot.id}/healthz")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(_k8s(context).fetch_agent_healthz.call_args.args[0], equal_to(f"agent-{context.parent.id}"))
        assert_that(_k8s(context).get_pod_readiness.call_args.args[0], equal_to(f"agent-{context.parent.id}"))


def _firecrawl_configured(context):
    config = context.injector.get(AppConfig)
    config.agent_firecrawl_api_key = "fc-platform-fixture"
    config.agent_firecrawl_base_url = "https://configured.firecrawl.example/v1"


def _apply_isolation(context):
    return _call(
        context,
        "put",
        f"{BASE}/{context.bot.id}/integrations/firecrawl/isolation",
        {"isolated": True, "restart": True},
    )


def _apply_custom_api(context):
    return _call(
        context,
        "post",
        f"{BASE}/{context.bot.id}/custom-api-connections/apply",
        {
            "creates": [
                {
                    "name": "Inventory",
                    "base_url": "https://api.example.com/v1",
                    "auth": {"type": "bearer", "token": "fixture-private-token"},
                }
            ],
            "restart": True,
        },
    )


@pytest.mark.parametrize("apply", [_apply_isolation, _apply_custom_api])
def test_applying_a_change_on_a_bot_restarts_its_parent(apply):
    with given([*_GIVEN, _parent_with_bots(1, status=AgentStatus.RUNNING)]) as context:
        _firecrawl_configured(context)

        response = apply(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(set(_deleted_names(_k8s(context).delete_deployment)), equal_to({f"agent-{context.parent.id}"}))
        created = _k8s(context).create_deployment.call_args.args[1]
        assert_that(created.metadata.name, equal_to(f"agent-{context.parent.id}"))


@pytest.mark.parametrize("apply", [_apply_isolation, _apply_custom_api])
def test_restarting_through_a_bot_needs_lifecycle_on_the_parent(apply):
    with given([*_GIVEN, _parent_with_bots(1, status=AgentStatus.RUNNING)]) as context:
        _firecrawl_configured(context)
        _member(context)
        _grant(context, context.parent, AGENT_VIEWER_ROLE_ID)
        _grant(context, context.bot, AGENT_OWNER_ROLE_ID)
        _act_as_member(context)

        response = apply(context)

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN), response.text)
        assert_that(_k8s(context).delete_deployment.called, equal_to(False))


@pytest.mark.parametrize("apply", [_apply_isolation, _apply_custom_api])
def test_a_parent_in_a_managed_update_refuses_a_change_on_its_bot(apply):
    with given([*_GIVEN, _parent_with_bots(1, status=AgentStatus.RUNNING)]) as context:
        _firecrawl_configured(context)
        context.parent.managed_update_heartbeat_at = datetime.now(UTC)
        context.injector.get(AgentRepository).save(context.parent)

        response = apply(context)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT), response.text)


def test_deleting_a_bot_leaves_the_running_pod_alone():
    with given([*_GIVEN, _parent_with_bots(1, status=AgentStatus.RUNNING)]) as context:
        response = _call(context, "delete", f"{BASE}/{context.bot.id}")

        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that(_stored(context, context.bot.id), equal_to(None))
        assert_that(_stored(context, context.parent.id) is not None, equal_to(True))
        for method in ("delete_deployment", "delete_service", "delete_pvc", "delete_secret", "delete_config_map"):
            assert_that(getattr(_k8s(context), method).called, equal_to(False), method)
        context.injector.get(LiteLLMClient).block_key.assert_called_once_with(FAKE_LITELLM_KEY)


def test_a_parent_in_a_managed_update_refuses_deleting_its_bot():
    with given([*_GIVEN, _parent_with_bots(1, status=AgentStatus.RUNNING)]) as context:
        context.parent.managed_update_heartbeat_at = datetime.now(UTC)
        context.injector.get(AgentRepository).save(context.parent)

        response = _call(context, "delete", f"{BASE}/{context.bot.id}")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_deleting_a_parent_deletes_its_bots():
    with given([*_GIVEN, _parent_with_bots(1, 2)]) as context:
        response = _call(context, "delete", f"{BASE}/{context.parent.id}")

        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        for agent in [context.parent, *context.bots]:
            assert_that(_stored(context, agent.id), equal_to(None))
        names = [f"agent-{context.parent.id}", *[f"agent-{bot.id}" for bot in context.bots]]
        assert_that(_deleted_names(_k8s(context).delete_deployment), equal_to(names[:1]))
        assert_that(_deleted_names(_k8s(context).delete_pvc), equal_to(names[:1]))
        assert_that(_deleted_names(_k8s(context).delete_secret), contains_inanyorder(*names))
        assert_that(_deleted_names(_k8s(context).delete_config_map), contains_inanyorder(*names))
        assert_that(context.injector.get(LiteLLMClient).block_key.call_count, equal_to(3))


def _start(context, agent=None):
    return _call(context, "post", f"{BASE}/{(agent or context.parent).id}/start")


def _created(mock_method):
    return {call.args[1].metadata.name: call.args[1] for call in mock_method.call_args_list}


def test_starting_a_parent_serves_its_bots_from_one_pod():
    with given([*_GIVEN, _parent_with_bots(1, 2)]) as context:
        response = _start(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        k8s = _k8s(context)
        names = [f"agent-{context.parent.id}", *[f"agent-{bot.id}" for bot in context.bots]]
        assert_that(list(_created(k8s.create_deployment)), equal_to(names[:1]))
        assert_that(list(_created(k8s.create_pvc)), equal_to(names[:1]))
        assert_that(list(_created(k8s.create_service)), equal_to(names[:1]))
        assert_that(list(_created(k8s.create_secret)), contains_inanyorder(*names))
        assert_that(list(_created(k8s.create_config_map)), contains_inanyorder(*names))
        pod = _created(k8s.create_deployment)[names[0]].spec.template.spec
        assert_that({v.name for v in pod.volumes} >= {f"bot-{bot.id}-secret" for bot in context.bots}, equal_to(True))
        env = {item.name: item.value for item in pod.containers[0].env}
        assert_that(env["GATEWAY_MULTIPLEX_PROFILES"], equal_to("1"))
        ports = [port.name for port in _created(k8s.create_service)[names[0]].spec.ports]
        assert_that("trg-1" in ports and "trg-2" in ports, equal_to(True))


def test_the_parent_ships_the_bot_manifest():
    with given([*_GIVEN, _parent_with_bots(1, 2)]) as context:
        _start(context)

        data = _created(_k8s(context).create_config_map)[f"agent-{context.parent.id}"].data
        manifest = json.loads(data["bots.json"])
        assert_that(
            manifest["bots"],
            equal_to([{"id": str(bot.id), "slot": bot.bot_slot} for bot in context.bots]),
        )
        assert_that("AAI_CONFIG" in manifest["passthrough"], equal_to(True))
        assert_that("bot-setup.py" in data, equal_to(True))


def test_the_parents_secret_has_placeholders_for_passthrough_names():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        _start(context)

        secret = _created(_k8s(context).create_secret)[f"agent-{context.parent.id}"].string_data
        assert_that(secret["AAI_CONFIG"], equal_to(""))


def test_a_bots_config_turns_off_its_api_server():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        _start(context)

        data = _created(_k8s(context).create_config_map)[f"agent-{context.bot.id}"].data
        config = yaml.safe_load(data["hermes-config.yaml"])
        assert_that(config["platforms"]["api_server"], equal_to({"enabled": False}))


def test_each_bot_gets_its_own_keys_and_keeps_its_litellm_key():
    with given([*_GIVEN, _parent_with_bots(1, 2)]) as context:
        _start(context)

        secrets = _created(_k8s(context).create_secret)
        keys = {name: secret.string_data["API_SERVER_KEY"] for name, secret in secrets.items()}
        ingest = {name: secret.string_data["INGEST_API_KEY"] for name, secret in secrets.items()}
        assert_that(len(set(keys.values())), equal_to(3))
        assert_that(len(set(ingest.values())), equal_to(3))
        for bot in context.bots:
            assert_that(secrets[f"agent-{bot.id}"].string_data["AGENT_ID"], equal_to(str(bot.id)))
            assert_that(_stored(context, bot.id).ingest_key_encrypted != "", equal_to(True))
        context.injector.get(LiteLLMClient).generate_key.assert_not_called()


def test_starting_mirrors_running_onto_the_bots():
    with given([*_GIVEN, _parent_with_bots(1, 2)]) as context:
        _start(context)

        for bot in context.bots:
            assert_that(_stored(context, bot.id).status, equal_to(AgentStatus.RUNNING))


def test_one_bad_bot_fails_alone_and_is_not_served():
    with given([*_GIVEN, _parent_with_bots(1, 2)]) as context:
        original = AgentService._assemble_agent
        bad = context.bots[0]

        def failing(self, agent, **fields):
            if agent.id == bad.id:
                raise RuntimeError("broken bot")
            return original(self, agent, **fields)

        with patch.object(AgentService, "_assemble_agent", failing):
            response = _start(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        k8s = _k8s(context)
        assert_that(_stored(context, bad.id).status, equal_to(AgentStatus.ERROR))
        assert_that(_stored(context, context.bots[1].id).status, equal_to(AgentStatus.RUNNING))
        data = _created(k8s.create_config_map)[f"agent-{context.parent.id}"].data
        assert_that(
            [entry["id"] for entry in json.loads(data["bots.json"])["bots"]],
            equal_to([str(context.bots[1].id)]),
        )
        assert_that(f"agent-{bad.id}" in _created(k8s.create_secret), equal_to(False))
        pod = _created(k8s.create_deployment)[f"agent-{context.parent.id}"].spec.template.spec
        assert_that(f"bot-{bad.id}-secret" in {v.name for v in pod.volumes}, equal_to(False))


def test_a_multi_line_value_refuses_a_parent_with_bots_naming_only_the_key():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        config = context.injector.get(AppConfig)
        config.agent_firecrawl_api_key = "line1\nline2"
        config.agent_firecrawl_base_url = "https://configured.firecrawl.example/v1"

        response = _start(context)

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT), response.text)
        assert_that(response.text, contains_string("FIRECRAWL_API_KEY"))
        assert_that("line1" in response.text, equal_to(False))
        assert_that(_k8s(context).create_deployment.called, equal_to(False))


def test_a_parent_without_bots_ships_no_manifest():
    with given([*_GIVEN, _parent_with_bots()]) as context:
        _start(context)

        data = _created(_k8s(context).create_config_map)[f"agent-{context.parent.id}"].data
        assert_that("bots.json" in data, equal_to(False))


def test_a_deleted_bot_is_cleaned_up_and_not_served():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        _call(context, "delete", f"{BASE}/{context.bot.id}")

        _start(context)

        k8s = _k8s(context)
        data = _created(k8s.create_config_map)[f"agent-{context.parent.id}"].data
        manifest = json.loads(data["bots.json"])
        assert_that(manifest["bots"], equal_to([]))
        assert_that(manifest["deleted_ids"], equal_to([str(context.bot.id)]))
        pod = _created(k8s.create_deployment)[f"agent-{context.parent.id}"].spec.template.spec
        assert_that("GATEWAY_MULTIPLEX_PROFILES" in {e.name for e in pod.containers[0].env}, equal_to(False))


def test_stopping_a_parent_stops_its_bots_and_removes_their_runtime_material():
    with given([*_GIVEN, _parent_with_bots(1, 2)]) as context:
        _start(context)
        _call(context, "delete", f"{BASE}/{context.bots[1].id}")
        k8s = _k8s(context)
        k8s.delete_secret.reset_mock()
        k8s.delete_config_map.reset_mock()

        response = _call(context, "post", f"{BASE}/{context.parent.id}/stop")

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        stopped = _stored(context, context.bots[0].id)
        assert_that((stopped.status, stopped.running_model), equal_to((AgentStatus.STOPPED, "")))
        names = [f"agent-{context.parent.id}", *[f"agent-{bot.id}" for bot in context.bots]]
        assert_that(_deleted_names(k8s.delete_secret), contains_inanyorder(*names))
        assert_that(_deleted_names(k8s.delete_config_map), contains_inanyorder(*names))


def test_a_running_bot_reports_no_update_or_pending_size():
    with given([*_GIVEN, _parent_with_bots(1)]) as context:
        _start(context)
        stored = _stored(context, context.bot.id)
        stored.running_config_digest = "stale"
        context.injector.get(AgentRepository).save(stored)

        body = _call(context, "get", f"{BASE}/{context.bot.id}").json()

        assert_that((body["update_available"], body["pending_size"]), equal_to((False, False)))


def test_a_cluster_failure_on_one_bot_fails_only_that_bot():
    with given([*_GIVEN, _parent_with_bots(1, 2)]) as context:
        k8s = _k8s(context)
        bad = context.bots[0]

        def create_secret(namespace, secret):
            if secret.metadata.name == f"agent-{bad.id}":
                raise RuntimeError("cluster said no")

        k8s.create_secret.side_effect = create_secret

        response = _start(context)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(_stored(context, bad.id).status, equal_to(AgentStatus.ERROR))
        assert_that(_stored(context, context.bots[1].id).status, equal_to(AgentStatus.RUNNING))
        assert_that(_stored(context, context.parent.id).status, equal_to(AgentStatus.RUNNING))

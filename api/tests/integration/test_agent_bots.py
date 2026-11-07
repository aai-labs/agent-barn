from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, contains_inanyorder, equal_to, has_item, is_not

from api.domains.agents.models import AgentStatus, AgentType, pod_agent_id
from api.domains.agents.repository import AgentRepository
from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID, AGENT_VIEWER_ROLE_ID
from api.domains.users.organization_users.models import OrganizationRole
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
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
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

BASE = "/api/v1/organizations/{organization_id}/agents"
ROUTE_MISSING = "Not Found"
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

"""Integration tests for the Platform Agents page and a Platform Administrator's size override
(Agent Sizes, PR 3).

The contract under test:

- a Platform Administrator lists every live Agent across Organizations, ordered by
  Organization then Agent name, with the size each runs on; nobody else can;
- a Platform Administrator gives one Agent any enabled size, whether or not its Organization
  may choose it, which locks the size for the Organization until the override is cleared;
- clearing puts the Agent back on the default and hands the choice back;
- the override never stops or starts the Agent: it applies at the next start;
- every change leaves one Organization-scoped audit Event marked `by_platform`.
"""

from uuid import UUID, uuid7

from fastapi import status
from hamcrest import assert_that, contains_exactly, equal_to, has_entries, has_length

from api.domains.agent_sizes.models import GIB, MIB, STANDARD_SIZE_ID, AgentSize, OrganizationAgentSize
from api.domains.agents.models import Agent, AgentStatus
from api.domains.events import ActorIdentityType
from api.domains.events.catalog import AGENT_AGENT_SIZE_CHANGED
from api.domains.events.models import EventScope, OutboxMessage
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization, there_is_an_organization_with_user_and_access_token
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_PLATFORM_AGENTS = "/api/v1/platform/agents"
_AGENTS = "/api/v1/organizations/{organization_id}/agents"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_EXTERNAL_URL": "https://api.test.com",
            "SKIP_SLACK_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(email="platform-sizes-owner@example.com"),
    use_org_for_auth(),
    there_is_a_template(),
]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _delegate(context) -> PostgresRepositoryDelegate:
    return context.injector.get(PostgresRepositoryDelegate)


def _size(context, name: str, *, scale: int = 2, enabled: bool = True) -> AgentSize:
    size = AgentSize(
        name=name,
        cpu_request_millicores=50 * scale,
        cpu_limit_millicores=500 * scale,
        memory_request_bytes=320 * MIB * scale,
        memory_limit_bytes=1 * GIB * scale,
        enabled=enabled,
        sort_order=scale,
    )
    _delegate(context).save(size)
    return size


def _platform_admin(context) -> str:
    saved = {
        name: getattr(context, name, None) for name in ("user", "organization", "organization_user", "access_token")
    }
    context.organization = None
    admin_id = uuid7()
    there_is_a_user(id=admin_id, email=f"platform-{admin_id}@example.com", is_platform_admin=True)(context)
    there_is_an_access_token_for_user(admin_id)(context)
    token = context.access_token
    for name, value in saved.items():
        setattr(context, name, value)
    return token


def _admin_member(context) -> str:
    """An Organization Admin's token, without replacing the test's Owner as the actor."""
    saved = {
        name: getattr(context, name, None) for name in ("user", "organization", "organization_user", "access_token")
    }
    user_id = uuid7()
    there_is_a_user(
        id=user_id,
        email=f"admin-{user_id}@example.com",
        role=OrganizationRole.ADMIN,
        organization_id=context.organization.id,
    )(context)
    there_is_an_access_token_for_user(user_id)(context)
    token = context.access_token
    for name, value in saved.items():
        setattr(context, name, value)
    return token


def _other_organization(context, name: str) -> UUID:
    home = context.organization
    there_is_an_organization(name=name)(context)
    other_id = context.organization.id
    context.organization = home
    return other_id


def _list(context, token: str, **params):
    return context.client.get(_PLATFORM_AGENTS, params=params, headers=_auth(token))


def _override(context, token: str, size_id, agent_id: UUID | None = None):
    return context.client.put(
        f"{_PLATFORM_AGENTS}/{agent_id or context.agent.id}/agent-size",
        json={"agent_size_id": str(size_id) if size_id is not None else None},
        headers=_auth(token),
    )


def _org_set_size(context, token: str, size_id):
    url = f"{_AGENTS}/{context.agent.id}/agent-size".format(organization_id=context.organization.id)
    return context.client.put(
        url, json={"agent_size_id": str(size_id) if size_id is not None else None}, headers=_auth(token)
    )


def _events(context) -> list[OutboxMessage]:
    return [
        message
        for message in _delegate(context).find_all(OutboxMessage)
        if message.event_name == AGENT_AGENT_SIZE_CHANGED
    ]


def _stored_agent(context, agent_id: UUID | None = None) -> Agent:
    agent = _delegate(context).find_by_id(Agent, agent_id or context.agent.id)
    assert agent is not None
    return agent


# --- the platform-wide list --------------------------------------------------------


def test_a_platform_administrator_lists_every_live_agent_grouped_by_organization():
    with given(_GIVEN) as context:
        home = context.organization
        acme = _other_organization(context, "Acme")
        zeta = _other_organization(context, "Zeta Works")
        there_is_an_agent(name="Sally", organization_id=zeta)(context)
        there_is_an_agent(name="bravo", organization_id=acme)(context)
        there_is_an_agent(name="Alpha", organization_id=acme)(context)
        there_is_an_agent(name="Gone", organization_id=acme, deleted=True)(context)
        there_is_an_agent(name="Home Agent", organization_id=home.id)(context)
        admin = _platform_admin(context)

        with when("the administrator lists the platform's Agents"):
            response = _list(context, admin)

        with then("they come Organization by Organization, then by name, without deleted ones"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["total"], equal_to(4))
            assert_that(
                [(item["organization_name"], item["name"]) for item in body["items"]],
                contains_exactly(
                    ("Acme", "Alpha"),
                    ("Acme", "bravo"),
                    (home.name, "Home Agent"),
                    ("Zeta Works", "Sally"),
                ),
            )

        with then("each names the size it runs on, the default when none was chosen"):
            assert_that(
                body["items"][0],
                has_entries(
                    agent_size_id=None,
                    agent_size_set_by_platform=False,
                    pending_size=False,
                    status=AgentStatus.STOPPED.value,
                    agent_size=has_entries(id=str(STANDARD_SIZE_ID), name="Standard", is_default=True),
                ),
            )


def test_the_list_filters_by_organization_and_searches_agent_and_organization_names():
    with given(_GIVEN) as context:
        acme = _other_organization(context, "Acme")
        there_is_an_agent(name="Sally", organization_id=acme)(context)
        there_is_an_agent(name="Reporter", organization_id=acme)(context)
        there_is_an_agent(name="Sally Two", organization_id=context.organization.id)(context)
        admin = _platform_admin(context)

        by_org = _list(context, admin, organization_id=str(acme)).json()
        assert_that([item["name"] for item in by_org["items"]], contains_exactly("Reporter", "Sally"))

        by_agent_name = _list(context, admin, search="sally").json()
        assert_that([item["name"] for item in by_agent_name["items"]], contains_exactly("Sally", "Sally Two"))

        by_org_name = _list(context, admin, search="acme").json()
        assert_that(by_org_name["total"], equal_to(2))


def test_the_list_is_paged():
    with given(_GIVEN) as context:
        for index in range(3):
            there_is_an_agent(name=f"Agent {index}")(context)
        admin = _platform_admin(context)

        first = _list(context, admin, page=1, page_size=2).json()
        second = _list(context, admin, page=2, page_size=2).json()

        assert_that(first, has_entries(total=3, page=1, page_size=2))
        assert_that([item["name"] for item in first["items"]], contains_exactly("Agent 0", "Agent 1"))
        assert_that([item["name"] for item in second["items"]], contains_exactly("Agent 2"))


def test_only_platform_administrators_list_or_override():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        large = _size(context, "Large")
        owner = context.access_token

        assert_that(_list(context, owner).status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(_override(context, owner, large.id).status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(_stored_agent(context).agent_size_id, equal_to(None))


def test_a_read_only_api_key_can_list_but_not_override():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        large = _size(context, "Large")
        admin = _platform_admin(context)
        response = context.client.post(
            "/api/v1/auth/me/api-keys",
            json={"name": "Automation", "access_mode": "READ_ONLY"},
            headers=_auth(admin),
        )
        key = response.json()["token"]

        assert_that(_list(context, key).status_code, equal_to(status.HTTP_200_OK))
        assert_that(_override(context, key, large.id).status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(_stored_agent(context).agent_size_id, equal_to(None))


# --- the override ------------------------------------------------------------------


def test_an_override_gives_one_agent_a_size_its_organization_cannot_choose_and_locks_it():
    with given([*_GIVEN, there_is_an_agent(name="Sally")]) as context:
        large = _size(context, "Large", scale=4)
        admin = _platform_admin(context)
        owner = context.access_token

        with when("the administrator gives Sally Large, which her Organization may not choose"):
            response = _override(context, admin, large.id)

        with then("Sally is on Large and the size is locked"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                response.json(),
                has_entries(
                    agent_size_id=str(large.id),
                    agent_size_set_by_platform=True,
                    agent_size=has_entries(name="Large"),
                ),
            )
            stored = _stored_agent(context)
            assert_that((stored.agent_size_id, stored.agent_size_set_by_platform), equal_to((large.id, True)))

        with then("the Organization sees the lock on the Agent"):
            agent = context.client.get(
                f"{_AGENTS}/{context.agent.id}".format(organization_id=context.organization.id),
                headers=_auth(owner),
            ).json()
            assert_that(agent, has_entries(agent_size_set_by_platform=True, agent_size=has_entries(name="Large")))

        with then("one Organization-scoped Event records it as the platform's, by a User actor"):
            [event] = _events(context)
            assert_that(event.event_scope, equal_to(EventScope.ORGANIZATION))
            assert_that(event.organization_id, equal_to(context.organization.id))
            assert_that(event.actor, has_entries(type="USER"))
            assert_that(
                event.payload,
                has_entries(
                    agent_size_id=str(large.id),
                    agent_size_name="Large",
                    previous_agent_size_id=None,
                    by_platform=True,
                ),
            )


def test_the_organization_cannot_change_a_size_the_platform_set_until_it_is_cleared():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        large, medium = _size(context, "Large", scale=4), _size(context, "Medium")
        _delegate(context).save(OrganizationAgentSize(organization_id=context.organization.id, agent_size_id=medium.id))
        admin = _platform_admin(context)
        _override(context, admin, large.id)

        with when("the Owner and an Admin try to choose another size, or the default"):
            refused = [
                _org_set_size(context, context.access_token, medium.id),
                _org_set_size(context, _admin_member(context), None),
            ]

        with then("both are refused as a conflict and the override stays"):
            assert_that([response.status_code for response in refused], equal_to([status.HTTP_409_CONFLICT] * 2))
            assert_that(_stored_agent(context).agent_size_id, equal_to(large.id))

        with when("the administrator clears the override"):
            cleared = _override(context, admin, None)

        with then("the Agent is back on the default and unlocked"):
            assert_that(
                cleared.json(),
                has_entries(
                    agent_size_id=None,
                    agent_size_set_by_platform=False,
                    agent_size=has_entries(name="Standard"),
                ),
            )
            assert_that(
                _events(context)[-1].payload,
                has_entries(agent_size_id=None, previous_agent_size_name="Large", by_platform=True),
            )

        with then("the Owner can choose again"):
            assert_that(
                _org_set_size(context, context.access_token, medium.id).status_code, equal_to(status.HTTP_200_OK)
            )


def test_an_override_can_hold_an_agent_on_the_default_size():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        medium = _size(context, "Medium")
        _delegate(context).save(OrganizationAgentSize(organization_id=context.organization.id, agent_size_id=medium.id))
        admin = _platform_admin(context)

        response = _override(context, admin, STANDARD_SIZE_ID)

        assert_that(response.json(), has_entries(agent_size_id=str(STANDARD_SIZE_ID), agent_size_set_by_platform=True))
        assert_that(
            _org_set_size(context, context.access_token, medium.id).status_code, equal_to(status.HTTP_409_CONFLICT)
        )


def test_an_override_on_a_running_agent_applies_at_its_next_start():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        large = _size(context, "Large", scale=4)
        admin = _platform_admin(context)
        owner = context.access_token
        agent_url = f"{_AGENTS}/{context.agent.id}".format(organization_id=context.organization.id)
        context.client.post(f"{agent_url}/start", headers=_auth(owner))
        k8s = context.injector.get(KubernetesClient)
        k8s.reset_mock()

        with when("the administrator overrides its size while it runs"):
            response = _override(context, admin, large.id)

        with then("it keeps running untouched, with the change pending"):
            assert_that(response.json(), has_entries(status=AgentStatus.RUNNING.value, pending_size=True))
            assert_that(k8s.delete_deployment.called or k8s.create_deployment.called, equal_to(False))
            listed = _list(context, admin).json()["items"][0]
            assert_that(listed, has_entries(pending_size=True, agent_size_set_by_platform=True))

        with when("the Organization restarts it"):
            context.client.post(f"{agent_url}/stop", headers=_auth(owner))
            context.client.post(f"{agent_url}/start", headers=_auth(owner))

        with then("its container runs on Large"):
            container = k8s.create_deployment.call_args.args[1].spec.template.spec.containers[0].resources
            assert_that(container.limits, equal_to({"memory": "4Gi", "cpu": "2000m"}))
            assert_that(_list(context, admin).json()["items"][0]["pending_size"], equal_to(False))


def test_resending_the_same_override_records_nothing():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        large = _size(context, "Large")
        admin = _platform_admin(context)

        _override(context, admin, large.id)
        again = _override(context, admin, large.id)
        _override(context, admin, None)
        cleared_again = _override(context, admin, None)

        assert_that([again.status_code, cleared_again.status_code], equal_to([status.HTTP_200_OK] * 2))
        assert_that(_events(context), has_length(2))


def test_a_disabled_or_unknown_size_is_refused():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        retired = _size(context, "Retired", enabled=False)
        admin = _platform_admin(context)

        for size_id in (retired.id, uuid7()):
            assert_that(_override(context, admin, size_id).status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(_stored_agent(context).agent_size_id, equal_to(None))


def test_an_unknown_or_deleted_agent_is_not_found():
    with given([*_GIVEN, there_is_an_agent(name="Gone", deleted=True)]) as context:
        large = _size(context, "Large")
        admin = _platform_admin(context)

        assert_that(_override(context, admin, large.id).status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(_override(context, admin, large.id, uuid7()).status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_a_size_an_override_holds_cannot_be_deleted():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        large = _size(context, "Large")
        admin = _platform_admin(context)
        _override(context, admin, large.id)

        response = context.client.delete(f"/api/v1/platform/agent-sizes/{large.id}", headers=_auth(admin))

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(_stored_agent(context).agent_size_id, equal_to(large.id))


# --- restarting any Agent ----------------------------------------------------------


def _restart(context, token: str, agent_id: UUID | None = None):
    return context.client.post(f"{_PLATFORM_AGENTS}/{agent_id or context.agent.id}/restart", headers=_auth(token))


def _lifecycle_events(context, name: str) -> list[OutboxMessage]:
    return [message for message in _delegate(context).find_all(OutboxMessage) if message.event_name == name]


def test_a_platform_administrator_restarts_a_running_agent_onto_its_overridden_size():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        large = _size(context, "Large", scale=4)
        admin = _platform_admin(context)
        agent_url = f"{_AGENTS}/{context.agent.id}".format(organization_id=context.organization.id)
        context.client.post(f"{agent_url}/start", headers=_auth(context.access_token))
        _override(context, admin, large.id)
        k8s = context.injector.get(KubernetesClient)
        k8s.reset_mock()

        with when("the administrator restarts it from Platform View"):
            response = _restart(context, admin)

        with then("its pod is replaced by one on Large, and nothing is pending"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json(), has_entries(status=AgentStatus.RUNNING.value, pending_size=False))
            assert_that(k8s.delete_deployment.called, equal_to(True))
            container = k8s.create_deployment.call_args.args[1].spec.template.spec.containers[0].resources
            assert_that(container.limits, equal_to({"memory": "4Gi", "cpu": "2000m"}))

        with then("the stop and the start name the administrator, who has no Membership there"):
            for name in ("agent.stopped", "agent.started"):
                events = _lifecycle_events(context, name)
                assert_that(events[-1].actor["type"], equal_to(ActorIdentityType.USER.value))
                assert_that(events[-1].organization_id, equal_to(context.organization.id))


def test_a_platform_administrator_starts_an_agent_that_is_not_running():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        admin = _platform_admin(context)
        k8s = context.injector.get(KubernetesClient)

        response = _restart(context, admin)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), has_entries(status=AgentStatus.RUNNING.value))
        assert_that(k8s.create_deployment.called, equal_to(True))
        assert_that(_lifecycle_events(context, "agent.stopped"), has_length(0))


def test_only_a_platform_administrator_with_a_writable_credential_restarts_from_platform_view():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        owner = context.access_token
        admin = _platform_admin(context)
        key = context.client.post(
            "/api/v1/auth/me/api-keys",
            json={"name": "Automation", "access_mode": "READ_ONLY"},
            headers=_auth(admin),
        ).json()["token"]

        assert_that(_restart(context, owner).status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(_restart(context, key).status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(_stored_agent(context).status, equal_to(AgentStatus.STOPPED))


def test_restarting_an_unknown_or_deleted_agent_is_not_found():
    with given([*_GIVEN, there_is_an_agent(name="Gone", deleted=True)]) as context:
        admin = _platform_admin(context)

        assert_that(_restart(context, admin).status_code, equal_to(status.HTTP_404_NOT_FOUND))
        assert_that(_restart(context, admin, uuid7()).status_code, equal_to(status.HTTP_404_NOT_FOUND))

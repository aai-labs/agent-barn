"""Integration tests for Organizations choosing an Agent Size (Agent Sizes, PR 2).

The contract under test:

- a Platform Administrator sets which sizes an Organization may choose beyond the default;
  only enabled sizes can be added, and the default is never stored;
- any member reads what the Organization can choose; only Owners and Admins
  (`agent.size.manage`) choose a size when hiring or later, never Agent Owners or Editors;
- a change never stops the Agent: it applies at the next start, and `pending_size` says so;
- withdrawing or disabling a size leaves the Agents on it, and a size any Agent row
  references, even a soft-deleted one, cannot be deleted;
- a choice is re-checked under its locks, so a size withdrawn or disabled meanwhile is refused;
- making an allowed size the default puts the old default in its place, so the Organization
  keeps its choices;
- every change, a size chosen on hire included, leaves one audit Event, and an unchanged save none.
"""

from datetime import UTC, datetime
from uuid import UUID, uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, contains_exactly, equal_to, has_entries, has_item, has_length, is_not

from api.domains.agent_sizes.models import GIB, MIB, STANDARD_SIZE_ID, AgentSize, OrganizationAgentSize
from api.domains.agents.models import Agent, AgentStatus
from api.domains.agents.repository import AgentRepository, AgentSizeUnavailable
from api.domains.events import ActorIdentity, ActorIdentityType
from api.domains.events.catalog import AGENT_AGENT_SIZE_CHANGED, AGENT_CREATED, ORGANIZATION_AGENT_SIZES_CHANGED
from api.domains.events.models import EventScope, OutboxMessage
from api.domains.rbac.catalog import AGENT_EDITOR_ROLE_ID, AGENT_OWNER_ROLE_ID, AGENT_VIEWER_ROLE_ID
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
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
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_AGENTS = "/api/v1/organizations/{organization_id}/agents"
_ORG_SIZES = "/api/v1/organizations/{organization_id}/agent-sizes"
_PLATFORM_ORG = "/api/v1/platform/organizations/{organization_id}"

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
    there_is_an_organization_with_user_and_access_token(email="sizes-owner@example.com"),
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


def _allow(context, *sizes: AgentSize, organization_id: UUID | None = None) -> None:
    for size in sizes:
        _delegate(context).save(
            OrganizationAgentSize(organization_id=organization_id or context.organization.id, agent_size_id=size.id)
        )


def _disable(context, size: AgentSize) -> None:
    size.enabled = False
    _delegate(context).save(size)


def _member(context, role: OrganizationRole, *, email_verified: bool = True, organization_id: UUID | None = None):
    """A Membership and its token, without replacing the test's Owner as the actor."""
    saved = {
        name: getattr(context, name, None) for name in ("user", "organization", "organization_user", "access_token")
    }
    user_id = uuid7()
    there_is_a_user(
        id=user_id,
        email=f"{role.value.lower()}-{user_id}@example.com",
        role=role,
        organization_id=organization_id or context.organization.id,
        email_verified=email_verified,
    )(context)
    membership = context.organization_user
    there_is_an_access_token_for_user(user_id)(context)
    token = context.access_token
    for name, value in saved.items():
        setattr(context, name, value)
    return token, membership


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


def _set_allowed(context, token: str, size_ids: list, organization_id: UUID | None = None):
    url = f"{_PLATFORM_ORG}/agent-sizes".format(organization_id=organization_id or context.organization.id)
    return context.client.put(
        url, json={"agent_size_ids": [str(size_id) for size_id in size_ids]}, headers=_auth(token)
    )


def _choosable(context, token: str):
    return context.client.get(_ORG_SIZES, headers=_auth(token))


def _set_size(context, token: str, size_id, agent_id: UUID | None = None):
    url = f"{_AGENTS}/{agent_id or context.agent.id}/agent-size"
    return context.client.put(
        url, json={"agent_size_id": str(size_id) if size_id is not None else None}, headers=_auth(token)
    )


def _hire(context, token: str, **extra):
    body = {"name": "Sized Agent", "template_key": "test-template", **extra}
    return context.client.post(_AGENTS, json=body, headers=_auth(token))


def _events(context, name: str) -> list[OutboxMessage]:
    return [message for message in _delegate(context).find_all(OutboxMessage) if message.event_name == name]


def _stored_agent(context, agent_id: UUID | None = None) -> Agent:
    agent = _delegate(context).find_by_id(Agent, agent_id or context.agent.id)
    assert agent is not None
    return agent


def _started_container(context):
    deployment = context.injector.get(KubernetesClient).create_deployment.call_args.args[1]
    return deployment.spec.template.spec.containers[0].resources


# --- the platform decides the allowed set ---------------------------------------


def test_a_platform_administrator_sets_the_allowed_set_and_it_is_audited_once():
    with given(_GIVEN) as context:
        large = _size(context, "Large")
        admin = _platform_admin(context)

        with when("the administrator allows Large, sending the default along with it"):
            response = _set_allowed(context, admin, [large.id, STANDARD_SIZE_ID])

        with then("only Large is stored, since the default is always choosable"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["agent_size_ids"], equal_to([str(large.id)]))
            detail = context.client.get(
                _PLATFORM_ORG.format(organization_id=context.organization.id), headers=_auth(admin)
            ).json()
            assert_that(detail["agent_size_ids"], equal_to([str(large.id)]))

        with then("one Organization-scoped Event records the before and after"):
            events = _events(context, ORGANIZATION_AGENT_SIZES_CHANGED)
            assert_that(events, has_length(1))
            assert_that(events[0].event_scope, equal_to(EventScope.ORGANIZATION))
            assert_that(events[0].organization_id, equal_to(context.organization.id))
            assert_that(
                events[0].payload,
                has_entries(
                    agent_size_ids=[str(large.id)],
                    agent_size_names=["Large"],
                    previous_agent_size_ids=[],
                    previous_agent_size_names=[],
                ),
            )

        with when("the same set is saved again"):
            again = _set_allowed(context, admin, [large.id])

        with then("nothing changed, so nothing is recorded"):
            assert_that(again.status_code, equal_to(status.HTTP_200_OK))
            assert_that(_events(context, ORGANIZATION_AGENT_SIZES_CHANGED), has_length(1))


def test_only_enabled_sizes_can_be_added_but_one_disabled_since_may_stay():
    with given(_GIVEN) as context:
        large, retired = _size(context, "Large"), _size(context, "Retired", scale=3, enabled=False)
        admin = _platform_admin(context)

        with then("a disabled or unknown size cannot be allowed"):
            assert_that(_set_allowed(context, admin, [retired.id]).status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(_set_allowed(context, admin, [uuid7()]).status_code, equal_to(status.HTTP_400_BAD_REQUEST))

        with when("Large is allowed and then disabled"):
            _set_allowed(context, admin, [large.id])
            _disable(context, large)

        with then("re-saving the set that still holds it is accepted"):
            assert_that(_set_allowed(context, admin, [large.id]).status_code, equal_to(status.HTTP_200_OK))


@pytest.mark.parametrize("role", [OrganizationRole.OWNER, OrganizationRole.ADMIN, OrganizationRole.MEMBER])
def test_an_organization_cannot_set_its_own_allowed_set(role):
    with given(_GIVEN) as context:
        large = _size(context, "Large")
        token = context.access_token if role is OrganizationRole.OWNER else _member(context, role)[0]

        response = _set_allowed(context, token, [large.id])

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_an_unknown_organization_is_not_found():
    with given(_GIVEN) as context:
        admin = _platform_admin(context)

        assert_that(
            _set_allowed(context, admin, [], organization_id=uuid7()).status_code,
            equal_to(status.HTTP_404_NOT_FOUND),
        )


# --- what an Organization can choose --------------------------------------------


def test_any_member_reads_what_the_organization_can_choose():
    with given(_GIVEN) as context:
        large, huge, retired = (
            _size(context, "Large"),
            _size(context, "Huge", scale=4),
            _size(context, "Retired", scale=3),
        )
        member, _ = _member(context, OrganizationRole.MEMBER)
        pending, _ = _member(context, OrganizationRole.MEMBER, email_verified=False)

        with then("with nothing allowed, only the default is offered"):
            body = _choosable(context, member).json()
            assert_that(body["can_choose"], equal_to(False))
            assert_that([size["name"] for size in body["sizes"]], contains_exactly("Standard"))

        with when("Large, Huge and Retired are allowed, and Retired is then disabled"):
            _allow(context, large, huge, retired)
            _disable(context, retired)

        with then("the default comes first, then the enabled allowed sizes in catalog order"):
            for token in (member, pending, context.access_token):
                body = _choosable(context, token).json()
                assert_that(body["can_choose"], equal_to(True))
                assert_that([size["name"] for size in body["sizes"]], contains_exactly("Standard", "Large", "Huge"))
                assert_that(body["sizes"][0], has_entries(is_default=True, memory_request_bytes=320 * MIB))


def test_someone_from_another_organization_cannot_read_the_choice():
    with given(_GIVEN) as context:
        organization = context.organization
        outsider, _ = _member(context, OrganizationRole.OWNER, organization_id=uuid7())
        context.organization = organization

        assert_that(_choosable(context, outsider).status_code, equal_to(status.HTTP_403_FORBIDDEN))


# --- choosing when hiring ------------------------------------------------------


def test_an_owner_hires_on_an_allowed_size_and_choosing_the_default_follows_it():
    with given(_GIVEN) as context:
        large = _size(context, "Large")
        _allow(context, large)

        with when("the Owner hires one Agent on Large and one on the default, named"):
            on_large = _hire(context, context.access_token, agent_size_id=str(large.id))
            on_default = _hire(context, context.access_token, name="Default Agent", agent_size_id=str(STANDARD_SIZE_ID))

        with then("the first is on Large; the second stores no choice, so it follows the default"):
            assert_that(on_large.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(on_large.json(), has_entries(agent_size_id=str(large.id), pending_size=False))
            assert_that(on_large.json()["agent_size"], has_entries(name="Large", is_default=False))
            assert_that(on_default.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(on_default.json(), has_entries(agent_size_id=None))
            assert_that(on_default.json()["agent_size"], has_entries(name="Standard", is_default=True))


def test_a_member_hires_only_on_the_default():
    with given(_GIVEN) as context:
        large = _size(context, "Large")
        _allow(context, large)
        member, _ = _member(context, OrganizationRole.MEMBER)

        with then("naming a size is refused, even the default"):
            for size_id in (large.id, STANDARD_SIZE_ID):
                response = _hire(context, member, agent_size_id=str(size_id))
                assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

        with then("naming none hires on the default"):
            response = _hire(context, member)
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(response.json()["agent_size"], has_entries(name="Standard"))


def test_a_size_the_organization_may_not_choose_is_refused_when_hiring():
    with given(_GIVEN) as context:
        not_allowed, disabled = _size(context, "Large"), _size(context, "Retired", scale=3)
        _allow(context, disabled)
        _disable(context, disabled)

        for size_id in (not_allowed.id, disabled.id, uuid7()):
            response = _hire(context, context.access_token, agent_size_id=str(size_id))
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_a_size_chosen_on_hire_is_audited_and_the_default_is_not():
    with given(_GIVEN) as context:
        large = _size(context, "Large")
        _allow(context, large)

        with when("the Owner hires one Agent on Large and one naming the default"):
            on_large = _hire(context, context.access_token, agent_size_id=str(large.id)).json()
            _hire(context, context.access_token, name="Default Agent", agent_size_id=str(STANDARD_SIZE_ID))

        with then("only the first records the choice, from the default, in its creation's correlation"):
            events = _events(context, AGENT_AGENT_SIZE_CHANGED)
            assert_that(events, has_length(1))
            assert_that(
                events[0].payload,
                has_entries(
                    agent_id=on_large["id"],
                    agent_size_id=str(large.id),
                    agent_size_name="Large",
                    previous_agent_size_id=None,
                    previous_agent_size_name=None,
                    by_platform=False,
                ),
            )
            created = next(
                event for event in _events(context, AGENT_CREATED) if event.payload["agent_id"] == on_large["id"]
            )
            assert_that(events[0].correlation_id, equal_to(created.correlation_id))


# --- who may change an Agent's size ---------------------------------------------


def _owner(context):
    return context.access_token


def _admin(context):
    return _member(context, OrganizationRole.ADMIN)[0]


def _with_agent_role(role_id):
    def persona(context):
        token, membership = _member(context, OrganizationRole.MEMBER)
        there_is_agent_access(membership_id=membership.id, access_role_id=role_id)(context)
        return token

    return persona


def _unassigned_member(context):
    return _member(context, OrganizationRole.MEMBER)[0]


def _pending_member(context):
    return _member(context, OrganizationRole.MEMBER, email_verified=False)[0]


def _platform_admin_persona(context):
    return _platform_admin(context)


@pytest.mark.parametrize(
    ("persona", "expected"),
    [
        (_owner, status.HTTP_200_OK),
        (_admin, status.HTTP_200_OK),
        (_with_agent_role(AGENT_OWNER_ROLE_ID), status.HTTP_403_FORBIDDEN),
        (_with_agent_role(AGENT_EDITOR_ROLE_ID), status.HTTP_403_FORBIDDEN),
        (_with_agent_role(AGENT_VIEWER_ROLE_ID), status.HTTP_403_FORBIDDEN),
        (_unassigned_member, status.HTTP_404_NOT_FOUND),
        (_pending_member, status.HTTP_404_NOT_FOUND),
        (_platform_admin_persona, status.HTTP_403_FORBIDDEN),
    ],
    ids=["owner", "admin", "agent-owner", "agent-editor", "agent-viewer", "unassigned", "pending", "platform-admin"],
)
def test_only_owners_and_admins_change_an_agents_size(persona, expected):
    with given([*_GIVEN, there_is_an_agent()]) as context:
        large = _size(context, "Large")
        _allow(context, large)
        token = persona(context)

        response = _set_size(context, token, large.id)

        assert_that(response.status_code, equal_to(expected))
        stored = _stored_agent(context).agent_size_id
        assert_that(stored, equal_to(large.id if expected == status.HTTP_200_OK else None))


def test_an_agent_in_another_organization_or_deleted_is_not_found():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        large = _size(context, "Large")
        _allow(context, large)
        home_agent = context.agent
        deleted = _stored_agent(context)

        with when("an Owner of another Organization names this Agent under their own"):
            organization = context.organization
            outsider_org = uuid7()
            outsider, _ = _member(context, OrganizationRole.OWNER, organization_id=outsider_org)
            response = context.client.put(
                f"/api/v1/organizations/{outsider_org}/agents/{home_agent.id}/agent-size",
                json={"agent_size_id": str(large.id)},
                headers=_auth(outsider),
            )
            context.organization = organization

        with then("it is not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

        with when("the Agent is soft-deleted"):
            deleted.deleted_at = datetime.now(UTC)
            _delegate(context).save(deleted)

        with then("its own Owner cannot change it either"):
            assert_that(
                _set_size(context, context.access_token, large.id).status_code, equal_to(status.HTTP_404_NOT_FOUND)
            )


def test_the_size_action_is_offered_to_owners_and_admins_only():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        url = f"{_AGENTS}/{context.agent.id}"
        editor = _with_agent_role(AGENT_EDITOR_ROLE_ID)(context)

        owner_actions = context.client.get(url, headers=_auth(context.access_token)).json()["allowed_actions"]
        editor_actions = context.client.get(url, headers=_auth(editor)).json()["allowed_actions"]

        assert_that(owner_actions, has_item("agent.size.manage"))
        assert_that(editor_actions, is_not(has_item("agent.size.manage")))


# --- a change applies at the next start ------------------------------------------


def test_a_running_agent_keeps_its_resources_until_it_restarts_on_the_new_size():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        large = _size(context, "Large", scale=4)
        _allow(context, large)
        owner = context.access_token
        agent_url = f"{_AGENTS}/{context.agent.id}"

        with when("the Agent is started on the default"):
            assert_that(
                context.client.post(f"{agent_url}/start", headers=_auth(owner)).status_code,
                equal_to(status.HTTP_200_OK),
            )

        with then("it records what its pod got, and nothing is pending"):
            assert_that(
                _stored_agent(context).running_resources,
                equal_to(
                    {
                        "cpu_request_millicores": 50,
                        "cpu_limit_millicores": 500,
                        "memory_request_bytes": 320 * MIB,
                        "memory_limit_bytes": 1 * GIB,
                    }
                ),
            )
            assert_that(context.client.get(agent_url, headers=_auth(owner)).json()["pending_size"], equal_to(False))

        with when("the Owner chooses Large while it runs"):
            context.injector.get(KubernetesClient).reset_mock()
            response = _set_size(context, owner, large.id)

        with then("it keeps running, and a restart is pending"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                response.json(),
                has_entries(status=AgentStatus.RUNNING.value, pending_size=True, agent_size_id=str(large.id)),
            )
            k8s = context.injector.get(KubernetesClient)
            assert_that(k8s.delete_deployment.called or k8s.create_deployment.called, equal_to(False))

        with then("the change is audited once, naming both sizes"):
            events = _events(context, AGENT_AGENT_SIZE_CHANGED)
            assert_that(events, has_length(1))
            assert_that(events[0].event_scope, equal_to(EventScope.ORGANIZATION))
            assert_that(
                events[0].payload,
                has_entries(
                    agent_id=str(context.agent.id),
                    agent_size_id=str(large.id),
                    agent_size_name="Large",
                    previous_agent_size_id=None,
                    previous_agent_size_name=None,
                ),
            )

        with when("the same size is chosen again"):
            _set_size(context, owner, large.id)

        with then("nothing is recorded"):
            assert_that(_events(context, AGENT_AGENT_SIZE_CHANGED), has_length(1))

        with when("the Agent restarts"):
            context.client.post(f"{agent_url}/stop", headers=_auth(owner))
            assert_that(_stored_agent(context).running_resources, equal_to(None))
            context.client.post(f"{agent_url}/start", headers=_auth(owner))

        with then("its container runs on Large and nothing is pending"):
            container = _started_container(context)
            assert_that(container.requests, equal_to({"memory": "1280Mi", "cpu": "200m"}))
            assert_that(container.limits, equal_to({"memory": "4Gi", "cpu": "2000m"}))
            assert_that(context.client.get(agent_url, headers=_auth(owner)).json()["pending_size"], equal_to(False))

        with when("the Owner goes back to the default"):
            back = _set_size(context, owner, None)

        with then("the Agent follows the default again, pending until restart"):
            assert_that(back.json(), has_entries(agent_size_id=None, pending_size=True))
            assert_that(back.json()["agent_size"], has_entries(name="Standard"))
            assert_that(
                _events(context, AGENT_AGENT_SIZE_CHANGED)[-1].payload,
                has_entries(agent_size_id=None, previous_agent_size_name="Large"),
            )


# --- withdrawing, disabling and deleting sizes -----------------------------------


def test_withdrawing_or_disabling_a_size_keeps_the_agents_on_it_but_offers_it_no_more():
    with given([*_GIVEN, there_is_an_agent(name="On Large")]) as context:
        large = _size(context, "Large")
        admin = _platform_admin(context)
        _set_allowed(context, admin, [large.id])
        on_large = context.agent
        _set_size(context, context.access_token, large.id)
        there_is_an_agent(name="Another")(context)
        another = context.agent

        with when("the platform withdraws Large"):
            _set_allowed(context, admin, [])

        with then("the Agent stays on it, re-sending it is a no-op, and no other Agent can take it"):
            assert_that(_stored_agent(context, on_large.id).agent_size_id, equal_to(large.id))
            assert_that(
                _set_size(context, context.access_token, large.id, agent_id=on_large.id).status_code,
                equal_to(status.HTTP_200_OK),
            )
            assert_that(
                _set_size(context, context.access_token, large.id, agent_id=another.id).status_code,
                equal_to(status.HTTP_400_BAD_REQUEST),
            )

        with when("it is allowed again but disabled"):
            _set_allowed(context, admin, [large.id])
            _disable(context, large)

        with then("the Agent still reads Large, and nobody can choose it"):
            read = context.client.get(f"{_AGENTS}/{on_large.id}", headers=_auth(context.access_token)).json()
            assert_that(read["agent_size"], has_entries(name="Large"))
            assert_that(
                _set_size(context, context.access_token, large.id, agent_id=another.id).status_code,
                equal_to(status.HTTP_400_BAD_REQUEST),
            )


def test_a_size_any_agent_row_is_on_cannot_be_deleted_even_once_the_agent_is():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        large, unused = _size(context, "Large"), _size(context, "Unused", scale=3)
        _allow(context, large, unused)
        _set_size(context, context.access_token, large.id)
        admin = _platform_admin(context)
        delete = lambda size: context.client.delete(f"/api/v1/platform/agent-sizes/{size.id}", headers=_auth(admin))

        with then("a size an Agent is on is refused"):
            assert_that(delete(large).status_code, equal_to(status.HTTP_409_CONFLICT))

        with when("the Agent is soft-deleted"):
            agent = _stored_agent(context)
            agent.deleted_at = datetime.now(UTC)
            _delegate(context).save(agent)

        with then("it is still refused, since the row still references it"):
            assert_that(delete(large).status_code, equal_to(status.HTTP_409_CONFLICT))

        with then("a size only Organizations were allowed is deleted, and withdrawn from them"):
            assert_that(delete(unused).status_code, equal_to(status.HTTP_204_NO_CONTENT))
            detail = context.client.get(
                _PLATFORM_ORG.format(organization_id=context.organization.id), headers=_auth(admin)
            ).json()
            assert_that(detail["agent_size_ids"], equal_to([str(large.id)]))


def test_a_size_withdrawn_or_disabled_after_the_check_is_refused_under_the_lock():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        withdrawn, disabled = _size(context, "Large"), _size(context, "Retired", scale=3)
        _allow(context, disabled)
        _disable(context, disabled)
        repository = context.injector.get(AgentRepository)
        actor = ActorIdentity(type=ActorIdentityType.USER, id=context.user.id)

        with then("writing either, as if the service had checked before the change, is refused"):
            for size in (withdrawn, disabled):
                with pytest.raises(AgentSizeUnavailable):
                    repository.set_agent_size_with_event(context.agent, size.id, actor=actor, actor_display="Owner")
                with pytest.raises(AgentSizeUnavailable):
                    repository.create_with_creator_access(
                        Agent(
                            organization_id=context.organization.id,
                            created_by_user_id=context.user.id,
                            name="Raced",
                            agent_size_id=size.id,
                        ),
                        None,
                        actor=actor,
                        actor_display="Owner",
                    )

        with then("the Agent stays on the default, no Agent was hired, and nothing is recorded"):
            assert_that(_stored_agent(context).agent_size_id, equal_to(None))
            assert_that([agent.name for agent in _delegate(context).find_all(Agent)], is_not(has_item("Raced")))
            assert_that(_events(context, AGENT_AGENT_SIZE_CHANGED), has_length(0))


def test_making_a_size_the_default_keeps_every_choice_an_organization_had():
    with given(_GIVEN) as context:
        large, medium = _size(context, "Large"), _size(context, "Medium", scale=3)
        admin = _platform_admin(context)
        _set_allowed(context, admin, [large.id])
        home = context.organization
        there_is_an_organization(name="Medium Only", id=uuid7())(context)
        medium_only = context.organization
        there_is_an_organization(name="Cannot Choose", id=uuid7())(context)
        cannot_choose = context.organization
        context.organization = home
        _set_allowed(context, admin, [medium.id], organization_id=medium_only.id)

        def stored(organization) -> list[str]:
            url = _PLATFORM_ORG.format(organization_id=organization.id)
            return context.client.get(url, headers=_auth(admin)).json()["agent_size_ids"]

        with when("the administrator makes Large the default"):
            response = context.client.patch(
                f"/api/v1/platform/agent-sizes/{large.id}", json={"is_default": True}, headers=_auth(admin)
            )

        with then("the Organization allowed Large can still choose both, with Standard now the stored one"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            choosable = _choosable(context, context.access_token).json()
            assert_that(choosable["can_choose"], equal_to(True))
            assert_that([size["name"] for size in choosable["sizes"]], contains_exactly("Large", "Standard"))
            assert_that(stored(home), equal_to([str(STANDARD_SIZE_ID)]))

        with then("the one allowed only Medium keeps Standard beside it, and one that cannot choose still cannot"):
            assert_that(stored(medium_only), equal_to(sorted([str(STANDARD_SIZE_ID), str(medium.id)])))
            assert_that(stored(cannot_choose), equal_to([]))

        with then("each swap is recorded for its Organization in the default switch's correlation"):
            switch = {message.correlation_id for message in _events(context, "platform.agent_size.changed")}
            assert_that(switch, has_length(1))
            swaps = {
                message.organization_id: message
                for message in _events(context, ORGANIZATION_AGENT_SIZES_CHANGED)
                if message.correlation_id in switch
            }
            assert_that(set(swaps), equal_to({home.id, medium_only.id}))
            assert_that(
                swaps[home.id].payload,
                has_entries(
                    agent_size_ids=[str(STANDARD_SIZE_ID)],
                    agent_size_names=["Standard"],
                    previous_agent_size_ids=[str(large.id)],
                    previous_agent_size_names=["Large"],
                ),
            )
            assert_that(
                swaps[medium_only.id].payload,
                has_entries(agent_size_names=["Standard", "Medium"], previous_agent_size_names=["Medium"]),
            )


def test_the_catalog_counts_the_agents_on_each_size_and_those_following_the_default():
    with given([*_GIVEN, there_is_an_agent(name="On Large")]) as context:
        large = _size(context, "Large")
        _allow(context, large)
        _set_size(context, context.access_token, large.id)
        there_is_an_agent(name="Follows")(context)
        there_is_an_agent(name="Gone")(context)
        gone = _stored_agent(context)
        gone.deleted_at = datetime.now(UTC)
        _delegate(context).save(gone)
        admin = _platform_admin(context)

        def counts(**params):
            sizes = context.client.get("/api/v1/platform/agent-sizes", params=params, headers=_auth(admin)).json()
            return {size["name"]: (size["agent_count"], size["following_agent_count"]) for size in sizes}

        with then("live Agents count: one stored on Large, one following Standard"):
            assert_that(counts(), has_entries(Large=(1, 0), Standard=(0, 1)))

        with then("scoped to another Organization, there are none"):
            assert_that(counts(organization_id=str(uuid7())), has_entries(Large=(0, 0), Standard=(0, 0)))

        with then("scoped to this one, they are its own"):
            assert_that(
                counts(organization_id=str(context.organization.id)), has_entries(Large=(1, 0), Standard=(0, 1))
            )

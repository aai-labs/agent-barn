from uuid import UUID, uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, contains_inanyorder, equal_to, has_item, is_not
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentAccess, AgentFilter
from api.domains.agents.repository import AgentRepository
from api.domains.rbac.catalog import (
    MEMBER_ROLE_ID,
    PERMISSION_ID_BY_KEY,
    PermissionKey,
    PermissionScope,
)
from api.domains.rbac.models import Role, RolePermission
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.infrastructure.shared.models import Pagination
from api.tests.core.givenpy import given
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    there_is_agent_access,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_BASE = "/api/v1/agents"
_CREATE = {
    "name": "Member Agent",
    "platform": "slack",
    "slack_bot_token": "xoxb-member-agent",
    "slack_app_token": "xapp-1-member-agent",
    "template_slug": "test-template",
}
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
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_a_template(),
]


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _switch_to_member(*, member_id: UUID | None = None):
    def step(context):
        member_id_value = member_id or uuid7()
        there_is_a_user(
            id=member_id_value,
            email=f"member-{member_id_value}@example.com",
            role=OrganizationRole.MEMBER,
            organization_id=context.organization.id,
        )(context)
        there_is_an_access_token_for_user(member_id_value)(context)
        context.member = context.user
        context.member_membership = context.organization_user

    return step


def _save_current_agent_as(context, name: str) -> None:
    setattr(context, name, context.agent)


def test_member_creation_persists_creator_access_and_effective_permission_keys():
    with given([*_GIVEN, _switch_to_member()]) as context:
        response = context.client.post(_BASE, json=_CREATE, headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        body = response.json()
        assert_that(
            body["allowed_actions"],
            contains_inanyorder(
                PermissionKey.AGENT_READ.value,
                PermissionKey.AGENT_UPDATE.value,
                PermissionKey.AGENT_DELETE.value,
                PermissionKey.AGENT_START.value,
                PermissionKey.AGENT_ACCESS_MANAGE.value,
                PermissionKey.AGENT_SECRET_MANAGE.value,
                PermissionKey.ACTIVITY_READ.value,
                PermissionKey.COST_READ.value,
            ),
        )

        repository: AgentRepository = context.injector.get(AgentRepository)
        agent = repository.get_by_id(UUID(body["id"]))
        assert agent is not None
        assert_that(agent.created_by_user_id, equal_to(context.member.id))
        with Session(repository.delegate.engine) as session:
            access = session.exec(
                select(AgentAccess).where(
                    col(AgentAccess.agent_id) == agent.id,
                    col(AgentAccess.membership_id) == context.member_membership.id,
                )
            ).first()
        assert access is not None


def test_creator_keeps_assigned_agent_after_owner_is_demoted_to_member():
    with given(_GIVEN) as context:
        created = context.client.post(_BASE, json=_CREATE, headers=_auth(context))
        assert_that(created.status_code, equal_to(status.HTTP_201_CREATED))
        membership_repository: OrganizationUserRepository = context.injector.get(
            OrganizationUserRepository
        )
        membership = membership_repository.get_by_user_id_and_organization_id(
            context.user.id, context.organization.id
        )
        assert membership is not None
        membership.role_id = MEMBER_ROLE_ID
        membership_repository.save(membership)

        response = context.client.get(
            f"{_BASE}/{created.json()['id']}", headers=_auth(context)
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            response.json()["allowed_actions"],
            has_item(PermissionKey.AGENT_ACCESS_MANAGE.value),
        )


def test_agent_and_creator_access_insert_roll_back_together():
    with given(_GIVEN) as context:
        repository: AgentRepository = context.injector.get(AgentRepository)
        agent = Agent(
            organization_id=context.organization.id,
            created_by_user_id=context.user.id,
            name="Rollback Agent",
            template_slug="test-template",
            template_version=1,
        )

        with pytest.raises(IntegrityError):
            repository.create_with_creator_access(agent, uuid7())

        assert_that(repository.get_by_id(agent.id), equal_to(None))


def test_assigned_list_count_detail_and_recipient_actions_are_scoped():
    with given([*_GIVEN, there_is_an_agent(name="Assigned One")]) as context:
        _save_current_agent_as(context, "assigned_one")
        there_is_an_agent(name="Hidden")(context)
        _save_current_agent_as(context, "hidden")
        there_is_an_agent(name="Assigned Two")(context)
        _save_current_agent_as(context, "assigned_two")
        _switch_to_member()(context)
        there_is_agent_access(agent_id=context.assigned_one.id)(context)
        there_is_agent_access(agent_id=context.assigned_two.id)(context)

        page_one = context.client.get(
            _BASE, params={"page": 1, "page_size": 1}, headers=_auth(context)
        )
        page_two = context.client.get(
            _BASE, params={"page": 2, "page_size": 1}, headers=_auth(context)
        )
        hidden = context.client.get(
            f"{_BASE}/{context.hidden.id}", headers=_auth(context)
        )

        assert_that(page_one.status_code, equal_to(status.HTTP_200_OK))
        assert_that(page_two.status_code, equal_to(status.HTTP_200_OK))
        assert_that(page_one.json()["total"], equal_to(2))
        returned_ids = {
            page_one.json()["items"][0]["id"],
            page_two.json()["items"][0]["id"],
        }
        assert_that(
            returned_ids,
            equal_to({str(context.assigned_one.id), str(context.assigned_two.id)}),
        )
        actions = page_one.json()["items"][0]["allowed_actions"]
        assert_that(actions, is_not(has_item(PermissionKey.AGENT_ACCESS_MANAGE.value)))
        assert_that(hidden.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_visible_agent_without_update_permission_returns_403():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        role = Role(
            organization_id=context.organization.id,
            name="Agent Reader",
            is_system=False,
        )
        repository: AgentRepository = context.injector.get(AgentRepository)
        repository.delegate.save(role)
        repository.delegate.save(
            RolePermission(
                role_id=role.id,
                permission_id=PERMISSION_ID_BY_KEY[PermissionKey.AGENT_READ],
                scope=PermissionScope.ORGANIZATION,
            )
        )
        _switch_to_member()(context)
        context.member_membership.role_id = role.id
        membership_repository: OrganizationUserRepository = context.injector.get(
            OrganizationUserRepository
        )
        membership_repository.save(context.member_membership)

        visible = context.client.get(
            f"{_BASE}/{context.agent.id}", headers=_auth(context)
        )
        forbidden = context.client.patch(
            f"{_BASE}/{context.agent.id}",
            json={"name": "Forbidden"},
            headers=_auth(context),
        )

        assert_that(visible.status_code, equal_to(status.HTTP_200_OK))
        assert_that(forbidden.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_assigned_activity_and_cost_endpoints_cannot_be_bypassed():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        assigned_agent = context.agent
        there_is_an_agent(name="Hidden Aggregate")(context)
        hidden_agent = context.agent
        _switch_to_member()(context)
        there_is_agent_access(agent_id=assigned_agent.id)(context)

        assigned_urls = (
            f"{_BASE}/{assigned_agent.id}/logs",
            f"{_BASE}/{assigned_agent.id}/conversations/channels",
            f"{_BASE}/{assigned_agent.id}/tool-calls",
            f"/api/v1/costs/agents/{assigned_agent.id}",
        )
        hidden_urls = (
            f"{_BASE}/{hidden_agent.id}/logs",
            f"{_BASE}/{hidden_agent.id}/conversations/channels",
            f"{_BASE}/{hidden_agent.id}/tool-calls",
            f"/api/v1/costs/agents/{hidden_agent.id}",
        )

        for url in assigned_urls:
            response = context.client.get(url, headers=_auth(context))
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), url)
        for url in hidden_urls:
            response = context.client.get(url, headers=_auth(context))
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND), url)


def test_access_revocation_is_observed_on_next_request():
    with given([*_GIVEN, there_is_an_agent(), _switch_to_member()]) as context:
        there_is_agent_access()(context)
        repository: AgentRepository = context.injector.get(AgentRepository)
        first = context.client.get(
            f"{_BASE}/{context.agent.id}", headers=_auth(context)
        )
        with Session(repository.delegate.engine) as session:
            access = session.exec(
                select(AgentAccess).where(
                    col(AgentAccess.agent_id) == context.agent.id,
                    col(AgentAccess.membership_id) == context.member_membership.id,
                )
            ).one()
            session.delete(access)
            session.commit()
        second = context.client.get(
            f"{_BASE}/{context.agent.id}", headers=_auth(context)
        )

        assert_that(first.status_code, equal_to(status.HTTP_200_OK))
        assert_that(second.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_repository_assigned_scope_filters_before_count_and_pagination():
    with given([*_GIVEN, there_is_an_agent(), _switch_to_member()]) as context:
        there_is_agent_access()(context)
        repository: AgentRepository = context.injector.get(AgentRepository)
        from api.domains.rbac.policy import AuthorizationScope

        agents, total = repository.find_all_active(
            AuthorizationScope(
                organization_id=context.organization.id,
                scope=PermissionScope.ASSIGNED,
                membership_id=context.member_membership.id,
            ),
            AgentFilter(),
            Pagination(page=1, size=1),
        )

        assert_that(total, equal_to(1))
        assert_that([agent.id for agent in agents], equal_to([context.agent.id]))

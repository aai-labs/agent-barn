from uuid import UUID, uuid7

import pytest
from fastapi import status
from hamcrest import assert_that, contains_inanyorder, equal_to, has_item, is_not
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentAccess, AgentFilter, AgentPlatform
from api.domains.agents.repository import AgentRepository
from api.domains.events import ActorIdentity, ActorIdentityType
from api.domains.organizations.models import Organization
from api.domains.rbac.catalog import (
    AGENT_EDITOR_ROLE_ID,
    AGENT_OWNER_ROLE_ID,
    AGENT_VIEWER_ROLE_ID,
    PERMISSION_ID_BY_KEY,
    SYSTEM_AGENT_ACCESS_ROLE_GRANTS,
    PermissionKey,
)
from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.infrastructure.crypto import decrypt_token
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
    there_is_agent_access,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_BASE = "/api/v1/organizations/{organization_id}/agents"
_CREATE = {
    "name": "Member Agent",
    "platform": "slack",
    "slack_bot_token": "xoxb-member-agent",
    "slack_app_token": "xapp-1-member-agent",
    "template_key": "test-template",
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


def _add_member(
    context,
    *,
    role: OrganizationRole = OrganizationRole.MEMBER,
    email_verified: bool = True,
    organization_id: UUID | None = None,
    full_name: str = "Test User",
    email: str | None = None,
):
    """Create a target Membership without replacing the authenticated test actor."""
    saved = {
        name: getattr(context, name, None)
        for name in (
            "user",
            "organization",
            "organization_user",
            "current_user_context",
        )
    }
    user_id = uuid7()
    there_is_a_user(
        name=full_name,
        id=user_id,
        email=email or f"target-{user_id}@example.com",
        role=role,
        organization_id=organization_id or context.organization.id,
        email_verified=email_verified,
    )(context)
    user = context.user
    membership = context.organization_user
    for name, value in saved.items():
        setattr(context, name, value)
    return user, membership


def _insert_custom_agent_role(context, permissions: set[PermissionKey]) -> AgentAccessRole:
    repository: AgentRepository = context.injector.get(AgentRepository)
    role = AgentAccessRole(
        organization_id=context.organization.id,
        name=f"CUSTOM-{uuid7()}",
        is_system=False,
    )
    repository.delegate.save(role)
    for permission in permissions:
        repository.delegate.save(
            AgentAccessRolePermission(
                role_id=role.id,
                permission_id=PERMISSION_ID_BY_KEY[permission],
            )
        )
    return role


def test_discord_token_rotation_requires_secret_permission_from_actual_caller():
    with given([*_GIVEN, there_is_an_agent(platform=AgentPlatform.DISCORD)]) as context:
        repository: AgentRepository = context.injector.get(AgentRepository)
        original_config = repository.get_discord_config(context.agent.id)
        assert original_config is not None
        original_token = decrypt_token(original_config.bot_token_encrypted, TEST_ENCRYPTION_KEY)

        _switch_to_member()(context)
        role = _insert_custom_agent_role(
            context,
            {PermissionKey.AGENT_READ, PermissionKey.AGENT_UPDATE},
        )
        there_is_agent_access(access_role_id=role.id)(context)

        response = context.client.patch(
            f"{_BASE}/{context.agent.id}",
            json={"discord_bot_token": "forbidden-rotation"},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        persisted = repository.get_discord_config(context.agent.id)
        assert persisted is not None
        assert_that(
            decrypt_token(persisted.bot_token_encrypted, TEST_ENCRYPTION_KEY),
            equal_to(original_token),
        )


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
                PermissionKey.AGENT_LIFECYCLE_MANAGE.value,
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
        assert_that(access.access_role_id, equal_to(AGENT_OWNER_ROLE_ID))


def test_creator_keeps_assigned_agent_after_owner_is_demoted_to_member():
    with given(_GIVEN) as context:
        created = context.client.post(_BASE, json=_CREATE, headers=_auth(context))
        assert_that(created.status_code, equal_to(status.HTTP_201_CREATED))
        membership_repository: OrganizationUserRepository = context.injector.get(OrganizationUserRepository)
        membership = membership_repository.get_by_user_id_and_organization_id(context.user.id, context.organization.id)
        assert membership is not None
        membership.role = OrganizationRole.MEMBER
        membership_repository.save(membership)

        response = context.client.get(f"{_BASE}/{created.json()['id']}", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            response.json()["allowed_actions"],
            has_item(PermissionKey.AGENT_ACCESS_MANAGE.value),
        )


def test_agent_and_creator_access_insert_roll_back_together():
    with given(_GIVEN) as context:
        repository: AgentRepository = context.injector.get(AgentRepository)
        from api.domains.templates.defaults import (
            DEFAULT_AGENTS_MD,
            DEFAULT_BOOT_MD,
            DEFAULT_BOOTSTRAP_MD,
            DEFAULT_HEARTBEAT_MD,
            DEFAULT_IDENTITY_MD,
            DEFAULT_SOUL_MD,
            DEFAULT_TOOLS_MD,
            DEFAULT_USER_MD,
        )
        from api.domains.templates.models import AgentTemplate, TemplateSource
        from api.domains.templates.repository import TemplateRepository

        template_repo = context.injector.get(TemplateRepository)
        template = AgentTemplate(
            organization_id=context.organization.id,
            template_key="rollback-template",
            template_name="Rollback Template",
            template_source=TemplateSource.CUSTOM,
            version=1,
            soul_md=DEFAULT_SOUL_MD,
            identity_md=DEFAULT_IDENTITY_MD,
            user_md=DEFAULT_USER_MD,
            tools_md=DEFAULT_TOOLS_MD,
            agents_md=DEFAULT_AGENTS_MD,
            boot_md=DEFAULT_BOOT_MD,
            bootstrap_md=DEFAULT_BOOTSTRAP_MD,
            heartbeat_md=DEFAULT_HEARTBEAT_MD,
        )
        template_repo.save_template(template)
        agent = Agent(
            organization_id=context.organization.id,
            created_by_user_id=context.user.id,
            name="Rollback Agent",
            agent_template_id=template.id,
        )

        with pytest.raises(IntegrityError):
            repository.create_with_creator_access(
                agent,
                uuid7(),
                actor=ActorIdentity(type=ActorIdentityType.USER, id=context.user.id),
            )

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

        page_one = context.client.get(_BASE, params={"page": 1, "page_size": 1}, headers=_auth(context))
        page_two = context.client.get(_BASE, params={"page": 2, "page_size": 1}, headers=_auth(context))
        hidden = context.client.get(f"{_BASE}/{context.hidden.id}", headers=_auth(context))

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
        _switch_to_member()(context)
        repository: AgentRepository = context.injector.get(AgentRepository)
        repository.delegate.save(
            AgentAccess(
                organization_id=context.organization.id,
                membership_id=context.member_membership.id,
                agent_id=context.agent.id,
                access_role_id=AGENT_VIEWER_ROLE_ID,
            )
        )

        visible = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context))
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
            f"/api/v1/organizations/{{organization_id}}/costs/agents/{assigned_agent.id}",
        )
        hidden_urls = (
            f"{_BASE}/{hidden_agent.id}/logs",
            f"{_BASE}/{hidden_agent.id}/conversations/channels",
            f"{_BASE}/{hidden_agent.id}/tool-calls",
            f"/api/v1/organizations/{{organization_id}}/costs/agents/{hidden_agent.id}",
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
        first = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context))
        with Session(repository.delegate.engine) as session:
            access = session.exec(
                select(AgentAccess).where(
                    col(AgentAccess.agent_id) == context.agent.id,
                    col(AgentAccess.membership_id) == context.member_membership.id,
                )
            ).one()
            session.delete(access)
            session.commit()
        second = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context))

        assert_that(first.status_code, equal_to(status.HTTP_200_OK))
        assert_that(second.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_repository_agent_access_filters_before_count_and_pagination():
    with given([*_GIVEN, there_is_an_agent(), _switch_to_member()]) as context:
        there_is_agent_access()(context)
        repository: AgentRepository = context.injector.get(AgentRepository)
        from api.domains.rbac.policy import AuthorizationScope

        agents, total = repository.find_all_active(
            AuthorizationScope(
                organization_id=context.organization.id,
                membership_id=context.member_membership.id,
                permission=PermissionKey.AGENT_READ,
            ),
            AgentFilter(),
            Pagination(page=1, size=1),
        )

        assert_that(total, equal_to(1))
        assert_that([agent.id for agent in agents], equal_to([context.agent.id]))


def test_locked_agent_access_roles_are_listed_with_exact_permissions():
    with given(_GIVEN) as context:
        response = context.client.get(f"{_BASE}/share-roles", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        roles = {role["name"]: role for role in response.json()}
        assert_that(set(roles), equal_to({"VIEWER", "EDITOR", "OWNER"}))
        assert all(role["is_locked"] for role in roles.values())
        assert_that(
            set(roles["VIEWER"]["permissions"]),
            equal_to(
                {
                    PermissionKey.AGENT_READ.value,
                    PermissionKey.ACTIVITY_READ.value,
                    PermissionKey.COST_READ.value,
                }
            ),
        )
        assert_that(
            set(roles["OWNER"]["permissions"]),
            equal_to({permission.value for permission in SYSTEM_AGENT_ACCESS_ROLE_GRANTS[AGENT_OWNER_ROLE_ID]}),
        )


def _share_url(agent_id: UUID) -> str:
    return f"{_BASE}/{agent_id}/share"


def _assignment(user_id: UUID, role_id: UUID) -> dict[str, str]:
    return {"user_id": str(user_id), "access_role_id": str(role_id)}


def test_owner_replaces_share_snapshot_and_revokes_omitted_access():
    with given(_GIVEN) as context:
        owner_id = context.user.id
        created = context.client.post(_BASE, json=_CREATE, headers=_auth(context))
        assert_that(created.status_code, equal_to(status.HTTP_201_CREATED))
        agent_id = UUID(created.json()["id"])
        target, _ = _add_member(context)

        saved = context.client.put(
            _share_url(agent_id),
            json={
                "general_access_role_id": None,
                "assignments": [_assignment(target.id, AGENT_VIEWER_ROLE_ID)],
            },
            headers=_auth(context),
        )
        loaded = context.client.get(_share_url(agent_id), headers=_auth(context))
        there_is_an_access_token_for_user(target.id)(context)
        visible = context.client.get(f"{_BASE}/{agent_id}", headers=_auth(context))
        there_is_an_access_token_for_user(owner_id)(context)
        revoked = context.client.put(
            _share_url(agent_id),
            json={"general_access_role_id": None, "assignments": []},
            headers=_auth(context),
        )
        there_is_an_access_token_for_user(target.id)(context)
        hidden = context.client.get(f"{_BASE}/{agent_id}", headers=_auth(context))

        assert_that(saved.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            [item["user_id"] for item in saved.json()["assignments"]],
            contains_inanyorder(str(target.id)),
        )
        loaded_user_ids = [item["user_id"] for item in loaded.json()["assignments"]]
        assert_that(loaded_user_ids, contains_inanyorder(str(target.id)))
        assert_that(visible.status_code, equal_to(status.HTTP_200_OK))
        assert_that(revoked.status_code, equal_to(status.HTTP_200_OK))
        assert_that(hidden.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_share_snapshot_role_change_takes_effect_on_next_request():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        owner_id = context.user.id
        target, _ = _add_member(context)
        granted = context.client.put(
            _share_url(context.agent.id),
            json={
                "general_access_role_id": None,
                "assignments": [_assignment(target.id, AGENT_VIEWER_ROLE_ID)],
            },
            headers=_auth(context),
        )
        there_is_an_access_token_for_user(target.id)(context)
        forbidden = context.client.patch(
            f"{_BASE}/{context.agent.id}",
            json={"name": "Not yet"},
            headers=_auth(context),
        )
        there_is_an_access_token_for_user(owner_id)(context)
        changed = context.client.put(
            _share_url(context.agent.id),
            json={
                "general_access_role_id": None,
                "assignments": [_assignment(target.id, AGENT_EDITOR_ROLE_ID)],
            },
            headers=_auth(context),
        )
        there_is_an_access_token_for_user(target.id)(context)
        updated = context.client.patch(
            f"{_BASE}/{context.agent.id}",
            json={"name": "Now editor"},
            headers=_auth(context),
        )

        assert_that(granted.status_code, equal_to(status.HTTP_200_OK))
        assert_that(forbidden.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(changed.status_code, equal_to(status.HTTP_200_OK))
        assert_that(updated.status_code, equal_to(status.HTTP_200_OK))


def test_explicit_owner_can_share_onward_while_editor_cannot():
    with given([*_GIVEN, _switch_to_member()]) as context:
        created = context.client.post(_BASE, json=_CREATE, headers=_auth(context))
        assert_that(created.status_code, equal_to(status.HTTP_201_CREATED))
        agent_id = UUID(created.json()["id"])
        owner_recipient, _ = _add_member(context)
        editor_recipient, _ = _add_member(context)
        third_member, _ = _add_member(context)

        owner_grant = context.client.put(
            _share_url(agent_id),
            json={
                "general_access_role_id": None,
                "assignments": [
                    _assignment(owner_recipient.id, AGENT_OWNER_ROLE_ID),
                    _assignment(editor_recipient.id, AGENT_EDITOR_ROLE_ID),
                ],
            },
            headers=_auth(context),
        )
        there_is_an_access_token_for_user(owner_recipient.id)(context)
        forwarded = context.client.put(
            _share_url(agent_id),
            json={
                "general_access_role_id": None,
                "assignments": [
                    _assignment(owner_recipient.id, AGENT_OWNER_ROLE_ID),
                    _assignment(editor_recipient.id, AGENT_EDITOR_ROLE_ID),
                    _assignment(third_member.id, AGENT_VIEWER_ROLE_ID),
                ],
            },
            headers=_auth(context),
        )
        there_is_an_access_token_for_user(editor_recipient.id)(context)
        forbidden = context.client.get(_share_url(agent_id), headers=_auth(context))

        assert_that(owner_grant.status_code, equal_to(status.HTTP_200_OK))
        assert_that(forwarded.status_code, equal_to(status.HTTP_200_OK))
        assert_that(forbidden.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_unassigned_member_cannot_discover_share_settings():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        unrelated, _ = _add_member(context)
        there_is_an_access_token_for_user(unrelated.id)(context)

        response = context.client.get(_share_url(context.agent.id), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_creator_assignment_follows_normal_change_and_revoke_rules():
    with given([*_GIVEN, _switch_to_member()]) as context:
        creator_id = context.user.id
        created = context.client.post(_BASE, json=_CREATE, headers=_auth(context))
        agent_id = UUID(created.json()["id"])

        changed = context.client.put(
            _share_url(agent_id),
            json={
                "general_access_role_id": None,
                "assignments": [_assignment(creator_id, AGENT_VIEWER_ROLE_ID)],
            },
            headers=_auth(context),
        )
        update_forbidden = context.client.patch(
            f"{_BASE}/{agent_id}",
            json={"name": "No longer editor"},
            headers=_auth(context),
        )

        assert_that(changed.status_code, equal_to(status.HTTP_200_OK))
        assert_that(update_forbidden.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_explicit_owner_can_revoke_creator_assignment():
    with given([*_GIVEN, _switch_to_member()]) as context:
        creator_id = context.user.id
        created = context.client.post(_BASE, json=_CREATE, headers=_auth(context))
        agent_id = UUID(created.json()["id"])
        other_owner, _ = _add_member(context)
        granted = context.client.put(
            _share_url(agent_id),
            json={
                "general_access_role_id": None,
                "assignments": [
                    _assignment(creator_id, AGENT_OWNER_ROLE_ID),
                    _assignment(other_owner.id, AGENT_OWNER_ROLE_ID),
                ],
            },
            headers=_auth(context),
        )
        there_is_an_access_token_for_user(other_owner.id)(context)
        revoked = context.client.put(
            _share_url(agent_id),
            json={
                "general_access_role_id": None,
                "assignments": [_assignment(other_owner.id, AGENT_OWNER_ROLE_ID)],
            },
            headers=_auth(context),
        )
        there_is_an_access_token_for_user(creator_id)(context)
        hidden = context.client.get(f"{_BASE}/{agent_id}", headers=_auth(context))

        assert_that(granted.status_code, equal_to(status.HTTP_200_OK))
        assert_that(revoked.status_code, equal_to(status.HTTP_200_OK))
        assert_that(hidden.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_share_snapshot_rejects_missing_foreign_pending_non_member_and_cross_org():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        target, _ = _add_member(context)
        pending, _ = _add_member(context, email_verified=False)
        admin, _ = _add_member(context, role=OrganizationRole.ADMIN)
        cross_org, _ = _add_member(context, organization_id=uuid7())
        repository: AgentRepository = context.injector.get(AgentRepository)
        other_organization = Organization(name="Other Org")
        repository.delegate.save(other_organization)
        foreign_role = AgentAccessRole(
            organization_id=other_organization.id,
            name="FOREIGN",
            is_system=False,
        )
        repository.delegate.save(foreign_role)

        missing = context.client.put(
            _share_url(context.agent.id),
            json={
                "general_access_role_id": None,
                "assignments": [_assignment(target.id, uuid7())],
            },
            headers=_auth(context),
        )
        foreign = context.client.put(
            _share_url(context.agent.id),
            json={
                "general_access_role_id": None,
                "assignments": [_assignment(target.id, foreign_role.id)],
            },
            headers=_auth(context),
        )
        pending_response = context.client.put(
            _share_url(context.agent.id),
            json={
                "general_access_role_id": None,
                "assignments": [_assignment(pending.id, AGENT_EDITOR_ROLE_ID)],
            },
            headers=_auth(context),
        )
        admin_response = context.client.put(
            _share_url(context.agent.id),
            json={
                "general_access_role_id": None,
                "assignments": [_assignment(admin.id, AGENT_EDITOR_ROLE_ID)],
            },
            headers=_auth(context),
        )
        cross_org_response = context.client.put(
            _share_url(context.agent.id),
            json={
                "general_access_role_id": None,
                "assignments": [_assignment(cross_org.id, AGENT_EDITOR_ROLE_ID)],
            },
            headers=_auth(context),
        )

        assert_that(missing.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(foreign.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(pending_response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(admin_response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(cross_org_response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_removed_membership_cascades_agent_access():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        target, target_membership = _add_member(context)
        granted = context.client.put(
            _share_url(context.agent.id),
            json={
                "general_access_role_id": None,
                "assignments": [_assignment(target.id, AGENT_EDITOR_ROLE_ID)],
            },
            headers=_auth(context),
        )
        membership_repository: OrganizationUserRepository = context.injector.get(OrganizationUserRepository)
        membership_repository.delete(target_membership)
        repository: AgentRepository = context.injector.get(AgentRepository)

        assert_that(granted.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            list(repository.find_access_membership_ids(context.agent.id, context.organization.id)),
            is_not(has_item(target_membership.id)),
        )


def test_membershipless_platform_admin_cannot_manage_agent_share_in_org_url():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        organization = context.organization
        target, _ = _add_member(context)
        context.organization = None
        there_is_a_user(
            id=uuid7(),
            email="rbac-platform_admin@example.com",
            is_platform_admin=True,
        )(context)
        platform_admin_id = context.user.id
        context.organization = organization
        there_is_an_access_token_for_user(platform_admin_id)(context)
        response = context.client.put(
            _share_url(context.agent.id),
            json={
                "general_access_role_id": None,
                "assignments": [_assignment(target.id, AGENT_EDITOR_ROLE_ID)],
            },
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

from uuid import UUID, uuid7

from fastapi import status
from hamcrest import assert_that, contains_inanyorder, equal_to, has_item, is_not, none

from api.domains.rbac.catalog import (
    AGENT_EDITOR_ROLE_ID,
    AGENT_VIEWER_ROLE_ID,
    PERMISSION_ID_BY_KEY,
    PermissionKey,
)
from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
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
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user
from api.domains.agents.models import AgentAccess
from api.domains.agents.repository import AgentRepository
from api.domains.organizations.models import Organization
from api.domains.users.organization_users.models import OrganizationRole

_BASE = "/api/v1/agents"
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
    there_is_an_agent(),
]


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _general_access_url(agent_id: UUID) -> str:
    return f"{_BASE}/{agent_id}/general-access"


def test_general_access_defaults_to_restricted():
    with given(_GIVEN) as context:
        response = context.client.get(
            _general_access_url(context.agent.id), headers=_auth(context)
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["role"], none())


def test_owner_sets_changes_and_removes_general_access():
    with given(_GIVEN) as context:
        set_response = context.client.put(
            _general_access_url(context.agent.id),
            json={"access_role_id": str(AGENT_VIEWER_ROLE_ID)},
            headers=_auth(context),
        )

        assert_that(set_response.status_code, equal_to(status.HTTP_200_OK))
        role = set_response.json()["role"]
        assert_that(role["id"], equal_to(str(AGENT_VIEWER_ROLE_ID)))
        assert_that(role["name"], equal_to("VIEWER"))
        assert_that(role["is_locked"], equal_to(True))

        read_response = context.client.get(
            _general_access_url(context.agent.id), headers=_auth(context)
        )
        assert_that(read_response.json()["role"]["id"], equal_to(role["id"]))

        removed = context.client.delete(
            _general_access_url(context.agent.id), headers=_auth(context)
        )
        assert_that(removed.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        restricted = context.client.get(
            _general_access_url(context.agent.id), headers=_auth(context)
        )
        assert_that(restricted.json()["role"], none())


def test_general_access_rejects_unknown_role():
    with given(_GIVEN) as context:
        response = context.client.put(
            _general_access_url(context.agent.id),
            json={"access_role_id": str(uuid7())},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def _switch_to_member(context, *, email_verified: bool = True) -> None:
    member_id = uuid7()
    there_is_a_user(
        id=member_id,
        email=f"member-{member_id}@example.com",
        role=OrganizationRole.MEMBER,
        organization_id=context.organization.id,
        email_verified=email_verified,
    )(context)
    there_is_an_access_token_for_user(member_id)(context)


def test_member_without_access_manage_cannot_read_or_change_general_access():
    with given(_GIVEN) as context:
        agent_id = context.agent.id
        _switch_to_member(context)
        repository: AgentRepository = context.injector.get(AgentRepository)
        repository.delegate.save(
            AgentAccess(
                organization_id=context.organization.id,
                membership_id=context.organization_user.id,
                agent_id=agent_id,
                access_role_id=AGENT_VIEWER_ROLE_ID,
            )
        )

        read_response = context.client.get(
            _general_access_url(agent_id), headers=_auth(context)
        )
        set_response = context.client.put(
            _general_access_url(agent_id),
            json={"access_role_id": str(AGENT_VIEWER_ROLE_ID)},
            headers=_auth(context),
        )
        delete_response = context.client.delete(
            _general_access_url(agent_id), headers=_auth(context)
        )

        assert_that(read_response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(set_response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
        assert_that(delete_response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_unassigned_member_cannot_discover_general_access():
    with given(_GIVEN) as context:
        agent_id = context.agent.id
        _switch_to_member(context)

        response = context.client.get(
            _general_access_url(agent_id), headers=_auth(context)
        )

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def _insert_custom_role(
    context, *, organization_id: UUID, permissions: set[PermissionKey]
) -> AgentAccessRole:
    repository: AgentRepository = context.injector.get(AgentRepository)
    role = AgentAccessRole(
        organization_id=organization_id,
        name=f"CUSTOM-{uuid7().hex}",
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


def test_general_access_rejects_foreign_custom_role():
    with given(_GIVEN) as context:
        repository: AgentRepository = context.injector.get(AgentRepository)
        other_organization = Organization(name="Other Org")
        repository.delegate.save(other_organization)
        foreign_role = _insert_custom_role(
            context,
            organization_id=other_organization.id,
            permissions={PermissionKey.AGENT_READ},
        )

        response = context.client.put(
            _general_access_url(context.agent.id),
            json={"access_role_id": str(foreign_role.id)},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_general_access_requires_role_granting_agent_read():
    with given(_GIVEN) as context:
        readless_role = _insert_custom_role(
            context,
            organization_id=context.organization.id,
            permissions={PermissionKey.ACTIVITY_READ},
        )
        readable_role = _insert_custom_role(
            context,
            organization_id=context.organization.id,
            permissions={PermissionKey.AGENT_READ},
        )

        rejected = context.client.put(
            _general_access_url(context.agent.id),
            json={"access_role_id": str(readless_role.id)},
            headers=_auth(context),
        )
        accepted = context.client.put(
            _general_access_url(context.agent.id),
            json={"access_role_id": str(readable_role.id)},
            headers=_auth(context),
        )

        assert_that(rejected.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(accepted.status_code, equal_to(status.HTTP_200_OK))
        assert_that(accepted.json()["role"]["id"], equal_to(str(readable_role.id)))


def test_general_access_makes_agent_visible_with_role_permissions():
    with given(_GIVEN) as context:
        agent_id = context.agent.id
        context.client.put(
            _general_access_url(agent_id),
            json={"access_role_id": str(AGENT_VIEWER_ROLE_ID)},
            headers=_auth(context),
        )
        _switch_to_member(context)

        listed = context.client.get(_BASE, headers=_auth(context))
        detail = context.client.get(f"{_BASE}/{agent_id}", headers=_auth(context))
        forbidden_update = context.client.patch(
            f"{_BASE}/{agent_id}",
            json={"name": "Viewer cannot update"},
            headers=_auth(context),
        )

        assert_that(listed.status_code, equal_to(status.HTTP_200_OK))
        assert_that(listed.json()["total"], equal_to(1))
        assert_that(listed.json()["items"][0]["id"], equal_to(str(agent_id)))
        assert_that(detail.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            detail.json()["allowed_actions"],
            contains_inanyorder(
                PermissionKey.AGENT_READ.value,
                PermissionKey.ACTIVITY_READ.value,
                PermissionKey.COST_READ.value,
            ),
        )
        assert_that(
            detail.json()["allowed_actions"],
            is_not(has_item(PermissionKey.AGENT_UPDATE.value)),
        )
        assert_that(forbidden_update.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_general_access_scopes_subordinate_agent_resources():
    with given(_GIVEN) as context:
        general_agent = context.agent
        there_is_an_agent(name="Restricted Agent")(context)
        restricted_agent = context.agent
        context.client.put(
            _general_access_url(general_agent.id),
            json={"access_role_id": str(AGENT_VIEWER_ROLE_ID)},
            headers=_auth(context),
        )
        _switch_to_member(context)

        general_urls = (
            f"{_BASE}/{general_agent.id}/logs",
            f"{_BASE}/{general_agent.id}/conversations/channels",
            f"{_BASE}/{general_agent.id}/tool-calls",
            f"/api/v1/costs/agents/{general_agent.id}",
        )
        restricted_urls = (
            f"{_BASE}/{restricted_agent.id}/logs",
            f"{_BASE}/{restricted_agent.id}/conversations/channels",
            f"{_BASE}/{restricted_agent.id}/tool-calls",
            f"/api/v1/costs/agents/{restricted_agent.id}",
        )

        for url in general_urls:
            response = context.client.get(url, headers=_auth(context))
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), url)
        for url in restricted_urls:
            response = context.client.get(url, headers=_auth(context))
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND), url)


def test_pending_members_do_not_receive_general_access():
    with given(_GIVEN) as context:
        agent_id = context.agent.id
        context.client.put(
            _general_access_url(agent_id),
            json={"access_role_id": str(AGENT_VIEWER_ROLE_ID)},
            headers=_auth(context),
        )
        _switch_to_member(context, email_verified=False)

        listed = context.client.get(_BASE, headers=_auth(context))
        detail = context.client.get(f"{_BASE}/{agent_id}", headers=_auth(context))

        assert_that(listed.status_code, equal_to(status.HTTP_200_OK))
        assert_that(listed.json()["total"], equal_to(0))
        assert_that(detail.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_direct_and_general_access_permissions_are_additive():
    with given(_GIVEN) as context:
        owner_id = context.user.id
        agent_id = context.agent.id
        context.client.put(
            _general_access_url(agent_id),
            json={"access_role_id": str(AGENT_VIEWER_ROLE_ID)},
            headers=_auth(context),
        )
        _switch_to_member(context)
        member_id = context.user.id
        member_membership_id = context.organization_user.id
        repository: AgentRepository = context.injector.get(AgentRepository)
        repository.delegate.save(
            AgentAccess(
                organization_id=context.organization.id,
                membership_id=member_membership_id,
                agent_id=agent_id,
                access_role_id=AGENT_EDITOR_ROLE_ID,
            )
        )

        editable = context.client.patch(
            f"{_BASE}/{agent_id}",
            json={"name": "Direct Editor plus General Viewer"},
            headers=_auth(context),
        )
        detail = context.client.get(f"{_BASE}/{agent_id}", headers=_auth(context))
        there_is_an_access_token_for_user(owner_id)(context)
        revoked = context.client.delete(
            f"{_BASE}/{agent_id}/access/{member_id}", headers=_auth(context)
        )
        there_is_an_access_token_for_user(member_id)(context)
        still_visible = context.client.get(
            f"{_BASE}/{agent_id}", headers=_auth(context)
        )
        no_longer_editable = context.client.patch(
            f"{_BASE}/{agent_id}",
            json={"name": "General Viewer only"},
            headers=_auth(context),
        )

        assert_that(editable.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            detail.json()["allowed_actions"],
            has_item(PermissionKey.AGENT_UPDATE.value),
        )
        assert_that(revoked.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that(still_visible.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            still_visible.json()["allowed_actions"],
            contains_inanyorder(
                PermissionKey.AGENT_READ.value,
                PermissionKey.ACTIVITY_READ.value,
                PermissionKey.COST_READ.value,
            ),
        )
        assert_that(
            no_longer_editable.status_code,
            equal_to(status.HTTP_403_FORBIDDEN),
        )


def test_removing_general_access_leaves_direct_access_intact():
    with given(_GIVEN) as context:
        owner_id = context.user.id
        agent_id = context.agent.id
        context.client.put(
            _general_access_url(agent_id),
            json={"access_role_id": str(AGENT_VIEWER_ROLE_ID)},
            headers=_auth(context),
        )
        _switch_to_member(context)
        member_id = context.user.id
        repository: AgentRepository = context.injector.get(AgentRepository)
        repository.delegate.save(
            AgentAccess(
                organization_id=context.organization.id,
                membership_id=context.organization_user.id,
                agent_id=agent_id,
                access_role_id=AGENT_EDITOR_ROLE_ID,
            )
        )
        there_is_an_access_token_for_user(owner_id)(context)
        removed_general = context.client.delete(
            _general_access_url(agent_id), headers=_auth(context)
        )
        there_is_an_access_token_for_user(member_id)(context)

        still_editable = context.client.patch(
            f"{_BASE}/{agent_id}",
            json={"name": "Direct Editor survives"},
            headers=_auth(context),
        )

        assert_that(removed_general.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that(still_editable.status_code, equal_to(status.HTTP_200_OK))

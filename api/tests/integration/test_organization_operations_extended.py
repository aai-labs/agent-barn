from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, equal_to
from starlette.testclient import TestClient

from api.domains.rbac.catalog import PermissionKey
from api.domains.users.organization_users.models import OrganizationRole
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
    skill_is_assigned_to_agent,
    there_is_a_skill,
    there_is_an_agent,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.rbac import role_lacks_permission
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

# Seeding agents needs the mocked k8s/LiteLLM clients + encryption env.
_AGENT_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]


def _clear_active_org():
    def step(context):
        context.organization = None
        context.organization_user = None

    return step


def test_regular_user_context_includes_only_their_organizations():
    org_a = uuid7()
    org_b = uuid7()
    owner_a = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_a,
                email="owner-list-a@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                email="owner-list-b@example.com",
                organization_id=org_b,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_a),
        ]
    ) as context:
        client: TestClient = context.client
        response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {context.access_token}"})
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        memberships = response.json()["organization_users"]
        assert_that(len(memberships), equal_to(1))
        assert_that(memberships[0]["organization_id"], equal_to(str(org_a)))


def test_member_context_includes_their_organization():
    """A non-owner MEMBER must still see the org they belong to (not just owners)."""
    org_a = uuid7()
    org_b = uuid7()
    member_a = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                email="owner-memberlist-a@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                id=member_a,
                email="member-memberlist-a@example.com",
                organization_id=org_a,
                role=OrganizationRole.MEMBER,
            ),
            there_is_a_user(
                email="owner-memberlist-b@example.com",
                organization_id=org_b,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=member_a),
        ]
    ) as context:
        client: TestClient = context.client
        response = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {context.access_token}"})
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        memberships = response.json()["organization_users"]
        assert_that(len(memberships), equal_to(1))
        assert_that(memberships[0]["organization_id"], equal_to(str(org_a)))


def test_member_can_view_their_organization():
    """A MEMBER may fetch their own org by id."""
    org_id = uuid7()
    member_id = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                email="owner-viewself@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                id=member_id,
                email="member-viewself@example.com",
                organization_id=org_id,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(user_id=member_id),
        ]
    ) as context:
        client: TestClient = context.client
        response = client.get(
            f"/api/v1/organizations/{org_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["id"], equal_to(str(org_id)))


def test_owner_without_organization_read_cannot_view_their_organization():
    org_id = uuid7()
    owner_id = uuid7()

    with given(
        [
            *_AGENT_GIVEN,
            there_is_a_user(
                id=owner_id,
                email="owner-no-read@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_id),
            role_lacks_permission(OrganizationRole.OWNER, PermissionKey.ORGANIZATION_READ),
        ]
    ) as context:
        response = context.client.get(
            f"/api/v1/organizations/{org_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_user_cannot_view_another_organization():
    """An owner of org A must not be able to fetch org B they don't belong to."""
    org_a = uuid7()
    org_b = uuid7()
    owner_a = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_a,
                email="owner-a-crossview@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                email="owner-b-crossview@example.com",
                organization_id=org_b,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_a),
        ]
    ) as context:
        client: TestClient = context.client
        response = client.get(
            f"/api/v1/organizations/{org_b}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_platform_admin_without_membership_cannot_update_organization_by_url():
    org_id = uuid7()
    super_id = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                email="owner-super-update@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            _clear_active_org(),
            there_is_a_user(
                id=super_id,
                email="super-update@example.com",
                is_platform_admin=True,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.patch(
            f"/api/v1/organizations/{org_id}",
            json={"name": "Updated By Platform Admin"},
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_owner_without_organization_update_cannot_update_organization():
    org_id = uuid7()
    owner_id = uuid7()

    with given(
        [
            *_AGENT_GIVEN,
            there_is_a_user(
                id=owner_id,
                email="owner-no-update@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_id),
            role_lacks_permission(OrganizationRole.OWNER, PermissionKey.ORGANIZATION_UPDATE),
        ]
    ) as context:
        response = context.client.patch(
            f"/api/v1/organizations/{org_id}",
            json={"name": "Should Not Work"},
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_owner_with_assigned_organization_update_cannot_update_organization():
    org_id = uuid7()
    owner_id = uuid7()

    with given(
        [
            *_AGENT_GIVEN,
            there_is_a_user(
                id=owner_id,
                email="owner-assigned-update@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_id),
            role_lacks_permission(
                OrganizationRole.OWNER,
                PermissionKey.ORGANIZATION_UPDATE,
            ),
        ]
    ) as context:
        response = context.client.patch(
            f"/api/v1/organizations/{org_id}",
            json={"name": "Should Not Work"},
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_member_cannot_update_organization():
    org_id = uuid7()
    owner_id = uuid7()
    member_id = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_id,
                email="owner@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                id=member_id,
                email="member@example.com",
                organization_id=org_id,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(user_id=member_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.patch(
            f"/api/v1/organizations/{org_id}",
            json={"name": "Should Not Work"},
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_platform_admin_without_membership_gets_403_for_missing_organization_url():
    super_id = uuid7()
    missing_org = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=super_id,
                email="super@example.com",
                is_platform_admin=True,
                organization_id=None,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.get(
            f"/api/v1/organizations/{missing_org}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_member_cannot_delete_organization():
    org_id = uuid7()
    owner_id = uuid7()
    member_id = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_id,
                email="owner-delete2@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                id=member_id,
                email="member-delete2@example.com",
                organization_id=org_id,
                role=OrganizationRole.MEMBER,
            ),
            there_is_an_access_token_for_user(user_id=member_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.delete(
            f"/api/v1/organizations/{org_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_platform_admin_without_membership_cannot_delete_organization_by_url():
    super_id = uuid7()
    org_a = uuid7()
    org_b = uuid7()
    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=super_id,
                email="super-delete-context@example.com",
                is_platform_admin=True,
                organization_id=None,
            ),
            there_is_a_user(
                email="owner-delete-context-a@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                email="owner-delete-context-b@example.com",
                organization_id=org_b,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        response = context.client.delete(
            f"/api/v1/organizations/{org_b}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_platform_admin_without_membership_cannot_delete_organization():
    super_id = uuid7()
    org_id = uuid7()
    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=super_id,
                email="platform-admin@example.com",
                is_platform_admin=True,
                organization_id=None,
            ),
            there_is_a_user(
                email="owner-admin-delete@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.delete(
            f"/api/v1/organizations/{org_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_owner_cannot_delete_another_organization():
    """An owner of org A must not be able to delete org B they don't belong to."""
    org_a = uuid7()
    org_b = uuid7()
    owner_a = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_a,
                email="owner-a-cross@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                email="owner-b-cross@example.com",
                organization_id=org_b,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_a),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.delete(
            f"/api/v1/organizations/{org_b}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_owner_cannot_update_another_organization():
    """An owner of org A must not be able to rename org B they don't belong to."""
    org_a = uuid7()
    org_b = uuid7()
    owner_a = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_a,
                email="owner-a-crossupd@example.com",
                organization_id=org_a,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                email="owner-b-crossupd@example.com",
                organization_id=org_b,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_a),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.patch(
            f"/api/v1/organizations/{org_b}",
            json={"name": "Hijacked"},
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_cannot_delete_organization():
    """Deleting an org is owner/platform_admin only; an admin is forbidden."""
    org_id = uuid7()
    admin_id = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                email="owner-admindel@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_a_user(
                id=admin_id,
                email="admin-admindel@example.com",
                organization_id=org_id,
                role=OrganizationRole.ADMIN,
            ),
            there_is_an_access_token_for_user(user_id=admin_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.delete(
            f"/api/v1/organizations/{org_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_owner_can_delete_their_organization():
    org_id = uuid7()
    owner_id = uuid7()

    with given(
        [
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            there_is_a_user(
                id=owner_id,
                email="owner-selfdel@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_id),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.delete(
            f"/api/v1/organizations/{org_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))


def test_organization_with_agents_cannot_be_deleted():
    """An org that still has (non-deleted) agents must be torn down first."""
    org_id = uuid7()
    owner_id = uuid7()

    with given(
        [
            *_AGENT_GIVEN,
            there_is_a_user(
                id=owner_id,
                email="owner-hasagents@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_id),
            there_is_an_agent(organization_id=org_id, name="Keeper"),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.delete(
            f"/api/v1/organizations/{org_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_organization_with_only_deleted_agents_can_be_deleted():
    """A soft-deleted agent doesn't block org deletion."""
    org_id = uuid7()
    owner_id = uuid7()

    with given(
        [
            *_AGENT_GIVEN,
            there_is_a_user(
                id=owner_id,
                email="owner-deletedagents@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_id),
            there_is_an_agent(organization_id=org_id, name="Gone", deleted=True),
        ]
    ) as context:
        client: TestClient = context.client

        response = client.delete(
            f"/api/v1/organizations/{org_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )
        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))


def test_organization_with_deleted_agent_skill_assignment_can_be_deleted():
    """A soft-deleted Agent's skill pin must not block the organization cascade."""
    org_id = uuid7()
    owner_id = uuid7()

    with given(
        [
            *_AGENT_GIVEN,
            there_is_a_user(
                id=owner_id,
                email="owner-deletedagent-skill@example.com",
                organization_id=org_id,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=owner_id),
            there_is_an_agent(organization_id=org_id, name="Gone With Skill", deleted=True),
            there_is_a_skill(name="Retired Skill"),
            skill_is_assigned_to_agent(),
        ]
    ) as context:
        response = context.client.delete(
            f"/api/v1/organizations/{org_id}",
            headers={"Authorization": f"Bearer {context.access_token}"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))

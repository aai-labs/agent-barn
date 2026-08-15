"""Cross-organization isolation (multi-tenant object-level access control).

List-level scoping is covered per-domain elsewhere; this suite pins the object-level
(IDOR) guarantees: authenticating as a member of org A and using org A's URL scope,
you must not be able to read or mutate org B's resources *by id/key*.

Isolation contract:
- Resources (agents, skills, templates) return **404** cross-org — existence is never
  leaked to a non-member.
- Organization/member *management* returns **403** — the org is a known entity you
  simply lack permission to administer.
- Platform Administrators use platform routes; org URLs still require real membership.
"""

from uuid import UUID, uuid7

from fastapi import status
from hamcrest import assert_that, equal_to

from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.skills.models import Skill, SkillSource
from api.domains.skills.repository import SkillRepository
from api.domains.users.organization_users.models import OrganizationRole
from api.tests.core.givenpy import given, then, when
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
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import (
    there_is_a_user,
    there_is_an_access_token_for_user,
)

ORG_A = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
ORG_B = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
MEMBER_A = UUID("11111111-1111-1111-1111-111111111111")
OWNER_A = UUID("33333333-3333-3333-3333-333333333333")
SUPERUSER = UUID("22222222-2222-2222-2222-222222222222")

_GIVEN = [
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


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _headers(context) -> dict:
    return _auth(context)


def _agents(org_id: UUID) -> str:
    return f"/api/v1/organizations/{org_id}/agents"


def _skills(org_id: UUID) -> str:
    return f"/api/v1/organizations/{org_id}/skills"


def _templates(org_id: UUID) -> str:
    return f"/api/v1/organizations/{org_id}/templates"


def _there_is_a_bare_org(org_id: UUID, name: str):
    """Insert a plain Organization row (satisfies FKs) without an owner user."""

    def step(context):
        repo: OrganizationRepository = context.injector.get(OrganizationRepository)
        repo.save(Organization(id=org_id, name=name))

    return step


def _there_is_a_skill_in_org(org_id: UUID):
    def step(context):
        skill = Skill(
            organization_id=org_id,
            name="Org B Skill",
            slug="org-b-skill",
            root_dir="org-b-skill",
            entry_path="SKILL.md",
            source=SkillSource.CUSTOM,
            required_providers=[],
        )
        repo: SkillRepository = context.injector.get(SkillRepository)
        repo.save(skill)
        repo.publish_version(skill.id, [("SKILL.md", "# Org B Skill")])
        context.skill_b = skill

    return step


# --------------------------------------------------------------------------- #
# Agents — object-level cross-org access must 404
# --------------------------------------------------------------------------- #


def _member_a_with_org_b_agent():
    return [
        *_GIVEN,
        there_is_a_user(
            id=MEMBER_A,
            email="member-a@example.com",
            organization_id=ORG_A,
            role=OrganizationRole.MEMBER,
        ),
        there_is_an_access_token_for_user(),
        _there_is_a_bare_org(ORG_B, "Org B"),
        there_is_an_agent(organization_id=ORG_B, name="Agent B"),
    ]


def test_cannot_read_agent_from_another_org():
    with given(_member_a_with_org_b_agent()) as context:
        agent_id = context.agent.id
        with when("a member of org A reads org B's agent, scoped to org A"):
            response = context.client.get(f"{_agents(ORG_A)}/{agent_id}", headers=_headers(context))
            with then("the agent is not found"):
                assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_cannot_update_agent_from_another_org():
    with given(_member_a_with_org_b_agent()) as context:
        agent_id = context.agent.id
        response = context.client.patch(
            f"{_agents(ORG_A)}/{agent_id}",
            json={"name": "Hijacked"},
            headers=_headers(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_cannot_delete_agent_from_another_org():
    with given(_member_a_with_org_b_agent()) as context:
        agent_id = context.agent.id
        response = context.client.delete(f"{_agents(ORG_A)}/{agent_id}", headers=_headers(context))
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_cannot_start_agent_from_another_org():
    with given(_member_a_with_org_b_agent()) as context:
        agent_id = context.agent.id
        response = context.client.post(f"{_agents(ORG_A)}/{agent_id}/start", headers=_headers(context))
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_cannot_stop_agent_from_another_org():
    with given(_member_a_with_org_b_agent()) as context:
        agent_id = context.agent.id
        response = context.client.post(f"{_agents(ORG_A)}/{agent_id}/stop", headers=_headers(context))
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_cannot_read_agent_health_from_another_org():
    with given(_member_a_with_org_b_agent()) as context:
        agent_id = context.agent.id
        response = context.client.get(f"{_agents(ORG_A)}/{agent_id}/healthz", headers=_headers(context))
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_cannot_read_agent_template_from_another_org():
    with given(_member_a_with_org_b_agent()) as context:
        agent_id = context.agent.id
        response = context.client.get(f"{_agents(ORG_A)}/{agent_id}/template/1", headers=_headers(context))
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --------------------------------------------------------------------------- #
# Skills — object-level cross-org access must 404
# --------------------------------------------------------------------------- #


def _member_a_with_org_b_skill():
    return [
        *_GIVEN,
        there_is_a_user(
            id=MEMBER_A,
            email="member-a@example.com",
            organization_id=ORG_A,
            role=OrganizationRole.MEMBER,
        ),
        there_is_an_access_token_for_user(),
        _there_is_a_bare_org(ORG_B, "Org B"),
        _there_is_a_skill_in_org(ORG_B),
    ]


def test_cannot_read_skill_from_another_org():
    with given(_member_a_with_org_b_skill()) as context:
        skill_id = context.skill_b.id
        response = context.client.get(f"{_skills(ORG_A)}/{skill_id}", headers=_headers(context))
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_cannot_update_skill_from_another_org():
    with given(_member_a_with_org_b_skill()) as context:
        skill_id = context.skill_b.id
        response = context.client.patch(
            f"{_skills(ORG_A)}/{skill_id}",
            json={"name": "Hijacked"},
            headers=_headers(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_cannot_delete_skill_version_from_another_org():
    with given(_member_a_with_org_b_skill()) as context:
        skill_id = context.skill_b.id
        response = context.client.delete(f"{_skills(ORG_A)}/{skill_id}/versions/1", headers=_headers(context))
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --------------------------------------------------------------------------- #
# Templates — a key that exists only in org B must 404 for org A
# --------------------------------------------------------------------------- #

_ORG_B_TEMPLATE_KEY = "orgb-secret-template"


def _member_a_with_org_b_template():
    return [
        *_GIVEN,
        there_is_a_user(
            id=MEMBER_A,
            email="member-a@example.com",
            organization_id=ORG_A,
            role=OrganizationRole.MEMBER,
        ),
        there_is_an_access_token_for_user(),
        _there_is_a_bare_org(ORG_B, "Org B"),
        there_is_a_template(template_key=_ORG_B_TEMPLATE_KEY, name="Org B Secret", organization_id=ORG_B),
    ]


def test_cannot_read_template_from_another_org():
    with given(_member_a_with_org_b_template()) as context:
        response = context.client.get(f"{_templates(ORG_A)}/{_ORG_B_TEMPLATE_KEY}", headers=_headers(context))
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_cannot_update_template_from_another_org():
    with given(_member_a_with_org_b_template()) as context:
        response = context.client.patch(
            f"{_templates(ORG_A)}/{_ORG_B_TEMPLATE_KEY}",
            json={"soul_md": "# Hijacked"},
            headers=_headers(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_cannot_list_template_versions_from_another_org():
    with given(_member_a_with_org_b_template()) as context:
        response = context.client.get(
            f"{_templates(ORG_A)}/{_ORG_B_TEMPLATE_KEY}/versions",
            headers=_headers(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --------------------------------------------------------------------------- #
# Members — managing another org must 403 (path-org authz, not header-org)
# --------------------------------------------------------------------------- #


def _owner_a_and_bare_org_b():
    """Owner of org A, scoped to org A, aiming at org B they don't belong to."""
    return [
        *_GIVEN,
        there_is_a_user(
            id=OWNER_A,
            email="owner-a@example.com",
            organization_id=ORG_A,
            role=OrganizationRole.OWNER,
        ),
        there_is_an_access_token_for_user(),
        _there_is_a_bare_org(ORG_B, "Org B"),
    ]


def test_cannot_list_members_of_another_org():
    with given(_owner_a_and_bare_org_b()) as context:
        response = context.client.get(f"/api/v1/organizations/{ORG_B}/members", headers=_headers(context))
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_cannot_add_member_to_another_org():
    with given(_owner_a_and_bare_org_b()) as context:
        response = context.client.post(
            f"/api/v1/organizations/{ORG_B}/members",
            json={"email": "victim@example.com", "role": "MEMBER"},
            headers=_headers(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_cannot_change_member_role_in_another_org():
    with given(_owner_a_and_bare_org_b()) as context:
        response = context.client.patch(
            f"/api/v1/organizations/{ORG_B}/members/{uuid7()}",
            json={"role": "ADMIN"},
            headers=_headers(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_cannot_remove_member_from_another_org():
    with given(_owner_a_and_bare_org_b()) as context:
        response = context.client.delete(
            f"/api/v1/organizations/{ORG_B}/members/{uuid7()}",
            headers=_headers(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_cannot_transfer_ownership_of_another_org():
    with given(_owner_a_and_bare_org_b()) as context:
        response = context.client.post(
            f"/api/v1/organizations/{ORG_B}/transfer-ownership",
            json={"user_id": str(uuid7())},
            headers=_headers(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


# --------------------------------------------------------------------------- #
# Platform Administrator non-member controls — targeting an org URL is forbidden
# --------------------------------------------------------------------------- #


def test_platform_admin_without_membership_cannot_read_org_agent_via_url():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=SUPERUSER,
                email="root@example.com",
                is_platform_admin=True,
                organization_id=None,
            ),
            there_is_an_access_token_for_user(),
            _there_is_a_bare_org(ORG_B, "Org B"),
            there_is_an_agent(organization_id=ORG_B, name="Agent B"),
        ]
    ) as context:
        agent_id = context.agent.id
        response = context.client.get(f"{_agents(ORG_B)}/{agent_id}", headers=_headers(context))
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_platform_admin_without_membership_cannot_list_org_members_via_url():
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=SUPERUSER,
                email="root@example.com",
                is_platform_admin=True,
                organization_id=None,
            ),
            there_is_a_user(
                email="owner-b@example.com",
                organization_id=ORG_B,
                role=OrganizationRole.OWNER,
            ),
            there_is_an_access_token_for_user(user_id=SUPERUSER),
        ]
    ) as context:
        response = context.client.get(f"/api/v1/organizations/{ORG_B}/members", headers=_headers(context))
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

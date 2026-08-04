from uuid import uuid7

from fastapi import status
from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    has_items,
    is_not,
    none,
)
from starlette.testclient import TestClient

from api.domains.agents.repository import AgentRepository
from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import AuthorizationScope
from api.domains.skills.repository import SkillRepository
from api.domains.templates.defaults import DEFAULT_SOUL_MD
from api.domains.templates.models import PlatformTemplate, TemplateSource
from api.domains.templates.predefined import PREDEFINED_TEMPLATES
from api.domains.templates.repository import TemplateRepository
from api.domains.templates.service import TemplateService
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
    there_is_a_skill,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.rbac import role_lacks_permission
from api.tests.steps.template import (
    there_is_a_template,
    there_is_a_template_skill,
    there_is_a_template_skill_group,
)
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_BASE = "/api/v1/organizations/{organization_id}/templates"
_PLATFORM_TEMPLATES_BASE = "/api/v1/platform/templates"
_AGENTS_BASE = "/api/v1/organizations/{organization_id}/agents"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
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
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _platform_version(slug: str, version: int, **overrides: str) -> PlatformTemplate:
    return PlatformTemplate(
        template_slug=slug,
        template_name="Manual Platform Template",
        version=version,
        description=overrides.get("description", f"platform description {version}"),
        soul_md=overrides.get("soul_md", f"platform soul {version}"),
        identity_md=overrides.get("identity_md", f"platform identity {version}"),
        user_md=overrides.get("user_md", f"platform user {version}"),
        tools_md=overrides.get("tools_md", f"platform tools {version}"),
        agents_md=overrides.get("agents_md", f"platform agents {version}"),
        boot_md=overrides.get("boot_md", f"platform boot {version}"),
        bootstrap_md=overrides.get("bootstrap_md", f"platform bootstrap {version}"),
        heartbeat_md=overrides.get("heartbeat_md", f"platform heartbeat {version}"),
    )


def _there_is_a_role_actor(role: OrganizationRole):
    def step(context):
        user_id = uuid7()
        there_is_a_user(
            id=user_id,
            email=f"{role.value.lower()}-templates@example.com",
            role=role,
        )(context)
        there_is_an_access_token_for_user(user_id=user_id)(context)

    return step


def _there_is_a_member_actor():
    return _there_is_a_role_actor(OrganizationRole.MEMBER)


def _there_is_a_platform_admin_actor():
    def step(context):
        user_id = uuid7()
        there_is_a_user(
            id=user_id,
            email="platform-template-admin@example.com",
            is_platform_admin=True,
            organization_id=uuid7(),
        )(context)
        there_is_an_access_token_for_user(user_id=user_id)(context)

    return step


# --- list ---


def test_member_without_template_read_cannot_list_templates():
    with given(
        [
            *_GIVEN,
            _there_is_a_member_actor(),
            role_lacks_permission(OrganizationRole.MEMBER, PermissionKey.TEMPLATE_READ),
        ]
    ) as context:
        response = context.client.get(_BASE, headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_member_can_list_shared_templates():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="shared", name="Shared"),
            _there_is_a_member_actor(),
        ]
    ) as context:
        response = context.client.get(_BASE, headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json()["items"][0]["template_slug"], equal_to("shared"))


def test_list_templates_returns_latest_version_per_slug():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="alpha", name="Alpha", version=1),
            there_is_a_template(slug="alpha", name="Alpha", version=2),
            there_is_a_template(slug="beta", name="Beta", version=1),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I list templates"):
            response = client.get(_BASE, headers=_auth(context))

        with then("each slug appears once at its latest version"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["total"], equal_to(2))
            by_slug = {item["template_slug"]: item for item in body["items"]}
            assert_that(by_slug["alpha"]["version"], equal_to(2))
            assert_that(by_slug["beta"]["version"], equal_to(1))


def test_list_templates_is_org_scoped():
    with given([*_GIVEN, there_is_a_template(slug="mine", name="Mine")]) as context:
        client: TestClient = context.client
        org_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        other_org = Organization(name="Other Org")
        org_repository.save(other_org)
        there_is_a_template(slug="theirs", name="Theirs", organization_id=other_org.id)(context)

        with when("I list templates"):
            response = client.get(_BASE, headers=_auth(context))

        with then("only my org's templates are returned"):
            body = response.json()
            slugs = [item["template_slug"] for item in body["items"]]
            assert_that(slugs, equal_to(["mine"]))


def test_list_templates_search_filters_by_name_and_slug():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="scrum-master", name="Scrum Master"),
            there_is_a_template(slug="code-reviewer", name="PR Reviewer"),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I search by a name substring"):
            response = client.get(f"{_BASE}?search=scrum", headers=_auth(context))

        with then("only matching templates are returned"):
            body = response.json()
            assert_that(body["total"], equal_to(1))
            assert_that(body["items"][0]["template_slug"], equal_to("scrum-master"))

        with when("I search by a slug substring matching the other"):
            response = client.get(f"{_BASE}?search=reviewer", headers=_auth(context))

        with then("the slug match is returned"):
            body = response.json()
            assert_that(body["total"], equal_to(1))
            assert_that(body["items"][0]["template_name"], equal_to("PR Reviewer"))


def test_list_templates_filters_by_source():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="seeded", name="Seeded", source=TemplateSource.PRE_DEFINED),
            there_is_a_template(slug="own", name="Own"),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I filter by source=pre-defined"):
            response = client.get(f"{_BASE}?source=pre-defined", headers=_auth(context))

        with then("only pre-defined templates are returned"):
            body = response.json()
            assert_that(body["total"], equal_to(1))
            assert_that(body["items"][0]["template_slug"], equal_to("seeded"))


def test_list_templates_paginates():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="t-a", name="A"),
            there_is_a_template(slug="t-b", name="B"),
            there_is_a_template(slug="t-c", name="C"),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I request page 2 with page_size 2"):
            response = client.get(f"{_BASE}?page=2&page_size=2", headers=_auth(context))

        with then("the remaining template is returned"):
            body = response.json()
            assert_that(body["total"], equal_to(3))
            assert_that(len(body["items"]), equal_to(1))
            assert_that(body["items"][0]["template_name"], equal_to("C"))


def test_list_templates_no_auth_returns_401():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I list templates without a token"):
            response = client.get(_BASE)

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_platform_admin_can_read_latest_published_platform_template():
    with given([*_GIVEN, _there_is_a_platform_admin_actor()]) as context:
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        repository.save_platform_template(_platform_version("manual", 1))

        response = context.client.get(f"{_PLATFORM_TEMPLATES_BASE}/manual", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["template_slug"], equal_to("manual"))
        assert_that(body["version"], equal_to(1))
        assert_that(body["soul_md"], equal_to("platform soul 1"))
        assert_that(body["template_source"], equal_to("pre-defined"))


def test_platform_admin_can_list_all_published_platform_template_versions():
    with given([*_GIVEN, _there_is_a_platform_admin_actor()]) as context:
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        repository.save_platform_template(_platform_version("manual", 1))
        repository.save_platform_template(_platform_version("manual", 2, soul_md="platform soul 2"))

        response = context.client.get(f"{_PLATFORM_TEMPLATES_BASE}/manual/versions", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that([version["version"] for version in body], equal_to([2, 1]))
        assert_that(body[0]["soul_md"], equal_to("platform soul 2"))
        assert_that(body[1]["soul_md"], equal_to("platform soul 1"))


def test_platform_admin_can_start_a_draft_from_a_selected_published_version():
    with given([*_GIVEN, _there_is_a_platform_admin_actor()]) as context:
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        repository.save_platform_template(_platform_version("manual", 1))
        repository.save_platform_template(_platform_version("manual", 2, soul_md="platform soul 2"))

        response = context.client.post(
            f"{_PLATFORM_TEMPLATES_BASE}/manual/draft?source_version=1",
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(response.json()["soul_md"], equal_to("platform soul 1"))


def test_non_platform_admin_cannot_read_published_platform_template():
    with given(_GIVEN) as context:
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        repository.save_platform_template(_platform_version("manual", 1))

        response = context.client.get(f"{_PLATFORM_TEMPLATES_BASE}/manual", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_list_templates_includes_required_skills():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template(slug="alpha", name="Alpha"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I list templates"):
            response = client.get(_BASE, headers=_auth(context))

        with then("the template includes its required skills"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            items = response.json()["items"]
            assert_that(len(items), equal_to(1))
            skill_names = [s["name"] for s in items[0]["required_skills"]]
            assert_that(skill_names, equal_to(["Jira"]))


# --- get ---


def test_member_without_template_read_cannot_get_template():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="alpha", name="Alpha"),
            _there_is_a_member_actor(),
            role_lacks_permission(OrganizationRole.MEMBER, PermissionKey.TEMPLATE_READ),
        ]
    ) as context:
        response = context.client.get(f"{_BASE}/alpha", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_get_template_returns_latest_with_metadata():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="alpha", name="Alpha", version=1),
            there_is_a_template(slug="alpha", name="Alpha v2", version=2),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I get the template by slug"):
            response = client.get(f"{_BASE}/alpha", headers=_auth(context))

        with then("the latest version with name and source is returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["version"], equal_to(2))
            assert_that(body["template_name"], equal_to("Alpha v2"))
            assert_that(body["template_source"], equal_to("custom"))


def test_get_template_unknown_slug_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I get a non-existent template"):
            response = client.get(f"{_BASE}/nope", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_get_template_reports_in_use():
    with given([*_GIVEN, there_is_an_agent(name="Pinned")]) as context:
        client: TestClient = context.client
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        template = repository.get_pinned_template(context.agent)
        assert template is not None

        with when("I get the template the agent is pinned to"):
            response = client.get(f"{_BASE}/{template.template_slug}", headers=_auth(context))

        with then("it is flagged in_use"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["in_use"], equal_to(True))


def test_get_template_reports_not_in_use():
    with given([*_GIVEN, there_is_a_template(slug="idle", name="Idle")]) as context:
        client: TestClient = context.client

        with when("I get a template no agent uses"):
            response = client.get(f"{_BASE}/idle", headers=_auth(context))

        with then("it is flagged not in_use"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["in_use"], equal_to(False))


# --- versions ---


def test_member_without_template_read_cannot_list_template_versions():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="alpha", name="Alpha"),
            _there_is_a_member_actor(),
            role_lacks_permission(OrganizationRole.MEMBER, PermissionKey.TEMPLATE_READ),
        ]
    ) as context:
        response = context.client.get(f"{_BASE}/alpha/versions", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_list_template_versions_returns_all_desc():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="alpha", name="Alpha", version=1),
            there_is_a_template(slug="alpha", name="Alpha", version=2),
            there_is_a_template(slug="alpha", name="Alpha", version=3),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I list the lineage's versions"):
            response = client.get(f"{_BASE}/alpha/versions", headers=_auth(context))

        with then("all versions are returned newest-first"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            versions = [item["version"] for item in response.json()]
            assert_that(versions, equal_to([3, 2, 1]))


def test_list_template_versions_unknown_slug_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I list versions of a non-existent lineage"):
            response = client.get(f"{_BASE}/nope/versions", headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_list_template_versions_no_auth_returns_401():
    with given([*_GIVEN, there_is_a_template(slug="alpha", name="Alpha")]) as context:
        client: TestClient = context.client

        with when("I list versions without a token"):
            response = client.get(f"{_BASE}/alpha/versions")

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_list_template_versions_includes_required_skills():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template(slug="alpha", name="Alpha", version=1),
            there_is_a_template_skill(),
            there_is_a_template(slug="alpha", name="Alpha", version=2),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I list versions of the template"):
            response = client.get(f"{_BASE}/alpha/versions", headers=_auth(context))

        with then("v1 includes the required skill; v2 has none (new version, no inherit via API)"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            versions = {v["version"]: v for v in response.json()}
            assert_that(len(versions[1]["required_skills"]), equal_to(1))
            assert_that(versions[1]["required_skills"][0]["name"], equal_to("Jira"))
            assert_that(versions[2]["required_skills"], equal_to([]))


def test_list_template_versions_reports_in_use_for_every_version():
    with given([*_GIVEN, there_is_an_agent(name="Pinned")]) as context:
        client: TestClient = context.client
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        template = repository.get_pinned_template(context.agent)
        assert template is not None
        there_is_a_template(slug=template.template_slug, name="Pinned", version=2)(context)

        with when("I list the lineage's versions"):
            response = client.get(f"{_BASE}/{template.template_slug}/versions", headers=_auth(context))

        with then("every version is flagged in_use, even ones the agent isn't pinned to"):
            versions = {v["version"]: v for v in response.json()}
            assert_that(versions[1]["in_use"], equal_to(True))
            assert_that(versions[2]["in_use"], equal_to(True))


# --- create ---


def test_member_cannot_create_template():
    with given([*_GIVEN, _there_is_a_member_actor()]) as context:
        response = context.client.post(
            _BASE,
            json={"template_name": "Member Template"},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_without_template_manage_cannot_create_template():
    with given(
        [
            *_GIVEN,
            _there_is_a_role_actor(OrganizationRole.ADMIN),
            role_lacks_permission(OrganizationRole.ADMIN, PermissionKey.TEMPLATE_MANAGE),
        ]
    ) as context:
        response = context.client.post(
            _BASE,
            json={"template_name": "Blocked Admin Template"},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_with_assigned_template_manage_cannot_create_template():
    with given(
        [
            *_GIVEN,
            _there_is_a_role_actor(OrganizationRole.ADMIN),
            role_lacks_permission(
                OrganizationRole.ADMIN,
                PermissionKey.TEMPLATE_MANAGE,
            ),
        ]
    ) as context:
        response = context.client.post(
            _BASE,
            json={"template_name": "Assigned Admin Template"},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_can_create_template():
    with given([*_GIVEN, _there_is_a_role_actor(OrganizationRole.ADMIN)]) as context:
        response = context.client.post(
            _BASE,
            json={"template_name": "Admin Template"},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))


def test_platform_admin_without_template_manage_permission_cannot_create_template():
    super_id = uuid7()
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=super_id,
                email="super-templates@example.com",
                role=OrganizationRole.MEMBER,
                is_platform_admin=True,
            ),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        response = context.client.post(
            _BASE,
            json={"template_name": "Platform administrator Template"},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_create_template_returns_201_v1_custom():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a template with name and soul only"):
            response = client.post(
                _BASE,
                json={"template_name": "My Helper!", "soul_md": "# Soul"},
                headers=_auth(context),
            )

        with then("it returns 201 with a slugified slug, v1, custom source"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["template_slug"], equal_to("my-helper"))
            assert_that(body["template_name"], equal_to("My Helper!"))
            assert_that(body["version"], equal_to(1))
            assert_that(body["template_source"], equal_to("custom"))
            assert_that(body["soul_md"], equal_to("# Soul"))

        with then("missing md fields fall back to defaults"):
            assert_that(body["user_md"], is_not(equal_to("")))
            assert_that(body["tools_md"], is_not(equal_to("")))


def test_create_template_duplicate_slug_returns_409():
    with given([*_GIVEN, there_is_a_template(slug="my-helper", name="My Helper")]) as context:
        client: TestClient = context.client

        with when("I create a template whose name slugifies to an existing slug"):
            response = client.post(
                _BASE,
                json={"template_name": "My helper"},
                headers=_auth(context),
            )

        with then("it returns 409"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_create_template_same_name_in_other_org_is_allowed():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        other_org = Organization(name="Other Org")
        context.injector.get(OrganizationRepository).save(other_org)
        there_is_a_template(slug="my-helper", name="My Helper", organization_id=other_org.id)(context)

        with when("I create a template with the same name in my org"):
            response = client.post(
                _BASE,
                json={"template_name": "My Helper"},
                headers=_auth(context),
            )

        with then("it returns 201"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))


def test_create_template_symbol_only_name_returns_422():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a template whose name has no alphanumerics"):
            response = client.post(
                _BASE,
                json={"template_name": "!!!"},
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_create_template_empty_name_returns_422():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a template with an empty name"):
            response = client.post(_BASE, json={"template_name": ""}, headers=_auth(context))

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_create_template_with_required_skills_stores_them():
    with given([*_GIVEN, there_is_a_skill(name="Jira")]) as context:
        client: TestClient = context.client

        with when("I create a template with a required skill"):
            response = client.post(
                _BASE,
                json={
                    "template_name": "My Template",
                    "required_skill_ids": [str(context.skill.id)],
                },
                headers=_auth(context),
            )

        with then("it returns 201 with required_skills populated"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(len(body["required_skills"]), equal_to(1))
            assert_that(body["required_skills"][0]["id"], equal_to(str(context.skill.id)))
            assert_that(body["required_skills"][0]["name"], equal_to("Jira"))

        with then("GET also returns the required skill"):
            get_resp = client.get(f"{_BASE}/my-template", headers=_auth(context))
            assert_that(len(get_resp.json()["required_skills"]), equal_to(1))


def test_create_template_with_unknown_skill_returns_404():
    from uuid import uuid4

    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a template with a non-existent skill ID"):
            response = client.post(
                _BASE,
                json={
                    "template_name": "My Template",
                    "required_skill_ids": [str(uuid4())],
                },
                headers=_auth(context),
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_create_template_with_required_skill_group_stores_group_key():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="GitHub"),
            there_is_a_skill(name="Bitbucket"),
        ]
    ) as context:
        client: TestClient = context.client
        skill_repository: SkillRepository = context.injector.get(SkillRepository)
        skills_by_name = {s.name: s for s in skill_repository.find_accessible_for_org(context.organization.id)}
        github_id = str(skills_by_name["GitHub"].id)
        bitbucket_id = str(skills_by_name["Bitbucket"].id)

        with when("I create a template with an at-least-one-of skill group"):
            response = client.post(
                _BASE,
                json={
                    "template_name": "My Template",
                    "required_skill_groups": [
                        {"group_key": "github-or-bitbucket", "skill_ids": [github_id, bitbucket_id]}
                    ],
                },
                headers=_auth(context),
            )

        with then("it returns 201 with both skills sharing the group_key"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(len(body["required_skills"]), equal_to(2))
            group_keys = {s["group_key"] for s in body["required_skills"]}
            assert_that(group_keys, equal_to({"github-or-bitbucket"}))


def test_create_template_rejects_skill_in_both_standalone_and_group():
    with given([*_GIVEN, there_is_a_skill(name="GitHub")]) as context:
        client: TestClient = context.client
        skill_id = str(context.skill.id)

        with when("the same skill is both standalone-required and in a group"):
            response = client.post(
                _BASE,
                json={
                    "template_name": "My Template",
                    "required_skill_ids": [skill_id],
                    "required_skill_groups": [{"group_key": "grp", "skill_ids": [skill_id]}],
                },
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_create_template_rejects_skill_in_two_groups():
    with given([*_GIVEN, there_is_a_skill(name="GitHub")]) as context:
        client: TestClient = context.client
        skill_id = str(context.skill.id)

        with when("the same skill appears in two different groups"):
            response = client.post(
                _BASE,
                json={
                    "template_name": "My Template",
                    "required_skill_groups": [
                        {"group_key": "grp-a", "skill_ids": [skill_id]},
                        {"group_key": "grp-b", "skill_ids": [skill_id]},
                    ],
                },
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_create_template_rejects_duplicate_group_keys():
    with given([*_GIVEN, there_is_a_skill(name="GitHub")]) as context:
        client: TestClient = context.client
        skill_id = str(context.skill.id)

        with when("two groups share the same group_key"):
            response = client.post(
                _BASE,
                json={
                    "template_name": "My Template",
                    "required_skill_groups": [
                        {"group_key": "dup", "skill_ids": [skill_id]},
                        {"group_key": "dup", "skill_ids": [skill_id]},
                    ],
                },
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


# --- update ---


def test_member_cannot_update_template():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="alpha", name="Alpha"),
            _there_is_a_member_actor(),
        ]
    ) as context:
        response = context.client.patch(
            f"{_BASE}/alpha",
            json={"description": "Changed"},
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_update_template_creates_new_version_with_merge():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="alpha", name="Alpha", soul_md="# Old Soul", tools_md="# Tools"),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I update only the soul"):
            response = client.patch(
                f"{_BASE}/alpha",
                json={"soul_md": "# New Soul"},
                headers=_auth(context),
            )

        with then("a new version is created, untouched fields carried over"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["version"], equal_to(2))
            assert_that(body["soul_md"], equal_to("# New Soul"))
            assert_that(body["tools_md"], equal_to("# Tools"))
            assert_that(body["template_slug"], equal_to("alpha"))


def test_update_template_name_is_inherited_not_editable():
    with given([*_GIVEN, there_is_a_template(slug="alpha", name="Alpha")]) as context:
        client: TestClient = context.client

        with when("I edit content and attempt to rename in the same request"):
            response = client.patch(
                f"{_BASE}/alpha",
                json={"soul_md": "# New", "template_name": "Alpha Renamed"},
                headers=_auth(context),
            )

        with then("the new version inherits the v1 name; the rename is ignored"):
            body = response.json()
            assert_that(body["template_name"], equal_to("Alpha"))
            assert_that(body["template_slug"], equal_to("alpha"))
            assert_that(body["version"], equal_to(2))
            assert_that(body["soul_md"], equal_to("# New"))


def test_update_predefined_template_keeps_source():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="seeded", name="Seeded", source=TemplateSource.PRE_DEFINED),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I update a pre-defined template"):
            response = client.patch(
                f"{_BASE}/seeded",
                json={"soul_md": "# Edited"},
                headers=_auth(context),
            )

        with then("the new version stays pre-defined"):
            body = response.json()
            assert_that(body["version"], equal_to(2))
            assert_that(body["template_source"], equal_to("pre-defined"))


def test_update_template_does_not_touch_agent_pins():
    with given([*_GIVEN, there_is_a_template(slug="test-template", name="Test Template")]) as context:
        client: TestClient = context.client

        with when("an agent is hired from the lineage"):
            agent = client.post(
                _AGENTS_BASE,
                json={
                    "name": "Pinned Agent",
                    "platform": "slack",
                    "slack_bot_token": "xoxb-token",
                    "slack_app_token": "xapp-1-token",
                    "template_slug": "test-template",
                },
                headers=_auth(context),
            ).json()
            assert_that(agent["template_version"], equal_to(1))

        with when("the templates page publishes a new version of that lineage"):
            response = client.patch(
                f"{_BASE}/test-template",
                json={"soul_md": "# v2"},
                headers=_auth(context),
            )

        with then("the agent stays pinned to its original version"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["version"], equal_to(2))
            agent_response = client.get(f"{_AGENTS_BASE}/{agent['id']}", headers=_auth(context))
            assert_that(agent_response.json()["template_version"], equal_to(1))


def test_update_template_unknown_slug_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I update a non-existent template"):
            response = client.patch(f"{_BASE}/nope", json={"soul_md": "# X"}, headers=_auth(context))

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_update_template_empty_body_returns_422():
    with given([*_GIVEN, there_is_a_template(slug="alpha", name="Alpha")]) as context:
        client: TestClient = context.client

        with when("I send an empty update"):
            response = client.patch(f"{_BASE}/alpha", json={}, headers=_auth(context))

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_update_template_inherits_skills_by_default():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template(slug="alpha", name="Alpha"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I update the template without specifying required_skill_ids"):
            response = client.patch(
                f"{_BASE}/alpha",
                json={"soul_md": "# Updated"},
                headers=_auth(context),
            )

        with then("the new version carries over the required skills from v1"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["version"], equal_to(2))
            assert_that(len(body["required_skills"]), equal_to(1))
            assert_that(body["required_skills"][0]["name"], equal_to("Jira"))


def test_update_template_replaces_skills():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template(slug="alpha", name="Alpha"),
            there_is_a_template_skill(),
            there_is_a_skill(name="Confluence"),
        ]
    ) as context:
        client: TestClient = context.client
        confluence_id = str(context.skill.id)

        with when("I update the template replacing required skills"):
            response = client.patch(
                f"{_BASE}/alpha",
                json={"soul_md": "# Updated", "required_skill_ids": [confluence_id]},
                headers=_auth(context),
            )

        with then("the new version has only the replacement skill"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["version"], equal_to(2))
            assert_that(len(body["required_skills"]), equal_to(1))
            assert_that(body["required_skills"][0]["name"], equal_to("Confluence"))


def test_update_template_clears_skills():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template(slug="alpha", name="Alpha"),
            there_is_a_template_skill(),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I update the template clearing required skills"):
            response = client.patch(
                f"{_BASE}/alpha",
                json={"soul_md": "# Updated", "required_skill_ids": []},
                headers=_auth(context),
            )

        with then("the new version has no required skills"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["version"], equal_to(2))
            assert_that(body["required_skills"], equal_to([]))


def test_update_template_inherits_groups_when_field_unset():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="alpha", name="Alpha"),
            there_is_a_template_skill_group(("GitHub", "Bitbucket"), group_key="github-or-bitbucket"),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I update other fields without touching required_skill_groups"):
            response = client.patch(
                f"{_BASE}/alpha",
                json={"soul_md": "# Updated"},
                headers=_auth(context),
            )

        with then("the new version keeps the inherited group"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["version"], equal_to(2))
            assert_that(len(body["required_skills"]), equal_to(2))
            group_keys = {s["group_key"] for s in body["required_skills"]}
            assert_that(group_keys, equal_to({"github-or-bitbucket"}))


def test_update_template_replaces_groups():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="alpha", name="Alpha"),
            there_is_a_template_skill_group(("GitHub", "Bitbucket"), group_key="github-or-bitbucket"),
            there_is_a_skill(name="Jira"),
        ]
    ) as context:
        client: TestClient = context.client
        jira_id = str(context.skill.id)

        with when("I replace the required_skill_groups with a different group"):
            response = client.patch(
                f"{_BASE}/alpha",
                json={
                    "soul_md": "# Updated",
                    "required_skill_groups": [{"group_key": "solo-jira", "skill_ids": [jira_id]}],
                },
                headers=_auth(context),
            )

        with then("the new version only has the replacement group"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(len(body["required_skills"]), equal_to(1))
            assert_that(body["required_skills"][0]["name"], equal_to("Jira"))
            assert_that(body["required_skills"][0]["group_key"], equal_to("solo-jira"))


def test_update_template_clears_groups():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="alpha", name="Alpha"),
            there_is_a_template_skill_group(("GitHub", "Bitbucket"), group_key="github-or-bitbucket"),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I clear required_skill_groups explicitly"):
            response = client.patch(
                f"{_BASE}/alpha",
                json={"soul_md": "# Updated", "required_skill_groups": []},
                headers=_auth(context),
            )

        with then("the new version has no required skills"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["required_skills"], equal_to([]))


def test_update_template_rejects_overlap_with_inherited_group():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="alpha", name="Alpha"),
            there_is_a_template_skill_group(("GitHub", "Bitbucket"), group_key="github-or-bitbucket"),
        ]
    ) as context:
        client: TestClient = context.client
        github_skill = context.template_skill_group["skills"][0]

        with when("required_skill_ids is set to a skill already inherited as a group member"):
            response = client.patch(
                f"{_BASE}/alpha",
                json={"soul_md": "# Updated", "required_skill_ids": [str(github_skill.id)]},
                headers=_auth(context),
            )

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


# --- delete ---


def test_delete_template_returns_204_and_purges_all_org_versions():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira"),
            there_is_a_template(slug="doomed", name="Doomed", version=1),
            there_is_a_template_skill(),
            there_is_a_template(slug="doomed", name="Doomed", version=2),
        ]
    ) as context:
        client: TestClient = context.client
        repository: TemplateRepository = context.injector.get(TemplateRepository)

        with when("I delete the template"):
            response = client.delete(f"{_BASE}/doomed", headers=_auth(context))

        with then("every org-scoped version and its skill links are gone"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            assert_that(repository.find_org_versions(context.organization.id, "doomed"), equal_to([]))
            assert_that(
                client.get(f"{_BASE}/doomed", headers=_auth(context)).status_code,
                equal_to(status.HTTP_404_NOT_FOUND),
            )


def test_delete_template_unknown_slug_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I delete a template that does not exist"):
            response = client.delete(f"{_BASE}/no-such-slug", headers=_auth(context))

        with then("I get 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_delete_template_requires_auth():
    with given([*_GIVEN, there_is_a_template(slug="doomed", name="Doomed")]) as context:
        client: TestClient = context.client

        with when("I delete without auth"):
            response = client.delete(f"{_BASE}/doomed")

        with then("I get 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_member_cannot_delete_template():
    with given([*_GIVEN, there_is_a_template(slug="doomed", name="Doomed"), _there_is_a_member_actor()]) as context:
        response = context.client.delete(f"{_BASE}/doomed", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_delete_predefined_template_returns_403():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="builtin", name="Built In", source=TemplateSource.PRE_DEFINED),
        ]
    ) as context:
        client: TestClient = context.client
        repository: TemplateRepository = context.injector.get(TemplateRepository)

        with when("I try to delete a pre-defined template"):
            response = client.delete(f"{_BASE}/builtin", headers=_auth(context))

        with then("I get 403 and the template survives"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(repository.get_latest_org_template(context.organization.id, "builtin"), is_not(none()))


def test_delete_platform_template_returns_403():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        service: TemplateService = context.injector.get(TemplateService)

        with when("I seed and try to delete a global platform template"):
            service.seed_predefined_templates()
            response = client.delete(f"{_BASE}/general-purpose", headers=_auth(context))

        with then("I get 403"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_delete_template_used_by_live_agent_returns_409():
    with given([*_GIVEN, there_is_an_agent(name="Pinned")]) as context:
        client: TestClient = context.client
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        template = repository.get_pinned_template(context.agent)
        assert template is not None
        there_is_a_template(slug=template.template_slug, name="Pinned", version=2)(context)

        with when("I try to delete the template the agent uses"):
            response = client.delete(f"{_BASE}/{template.template_slug}", headers=_auth(context))

        with then("I get 409 and every version survives"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(len(repository.find_org_versions(context.organization.id, template.template_slug)), equal_to(2))


def test_delete_template_referenced_by_soft_deleted_agent_returns_204():
    with given([*_GIVEN, there_is_an_agent(name="Ghost", deleted=True)]) as context:
        client: TestClient = context.client
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        template = repository.get_pinned_template(context.agent)
        assert template is not None

        with when("I delete the template only a soft-deleted agent references"):
            response = client.delete(f"{_BASE}/{template.template_slug}", headers=_auth(context))

        with then("the template is purged and the agent's pin is cleared"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            assert_that(
                client.get(f"{_BASE}/{template.template_slug}", headers=_auth(context)).status_code,
                equal_to(status.HTTP_404_NOT_FOUND),
            )
            agent_repository: AgentRepository = context.injector.get(AgentRepository)
            ghost = agent_repository.get_deleted_in_scope(
                context.agent.id,
                AuthorizationScope(organization_id=context.organization.id),
            )
            assert_that(ghost, is_not(none()))
            assert ghost is not None
            assert_that(ghost.agent_template_id, none())
            assert_that(ghost.platform_template_id, none())


def test_delete_template_of_another_org_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        org_repository: OrganizationRepository = context.injector.get(OrganizationRepository)
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        other_org = Organization(name="Other Org")
        org_repository.save(other_org)
        there_is_a_template(slug="theirs", name="Theirs", organization_id=other_org.id)(context)

        with when("I delete another org's template"):
            response = client.delete(f"{_BASE}/theirs", headers=_auth(context))

        with then("I get 404 and their template survives"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(repository.get_latest_org_template(other_org.id, "theirs"), is_not(none()))


def test_list_templates_reports_in_use():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="idle", name="Idle"),
            there_is_an_agent(name="Busy"),
        ]
    ) as context:
        client: TestClient = context.client
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        template = repository.get_pinned_template(context.agent)
        assert template is not None

        with when("I list templates"):
            response = client.get(_BASE, headers=_auth(context))

        with then("only the agent's template is marked in use"):
            by_slug = {item["template_slug"]: item for item in response.json()["items"]}
            assert_that(by_slug[template.template_slug]["in_use"], equal_to(True))
            assert_that(by_slug["idle"]["in_use"], equal_to(False))


# --- seeding ---


def test_seed_predefined_templates_creates_three_lineages():
    with given(_GIVEN) as context:
        service: TemplateService = context.injector.get(TemplateService)
        repository: TemplateRepository = context.injector.get(TemplateRepository)

        with when("I seed the global predefined catalogue"):
            service.seed_predefined_templates()

        with then("all pre-defined lineages exist at v1"):
            for slug in (
                "general-purpose",
                "scrum-master",
                "code-reviewer",
                "email-reminder",
                "jira-task-helper",
                "documentation-agent",
            ):
                template = repository.get_latest_platform_template(slug)
                assert_that(template, is_not(none()))
                assert template is not None
                assert_that(template.version, equal_to(1))
                # platform_template rows are inherently pre-defined (no source column)

        with then("the registry and DB agree on the count"):
            assert_that(len(PREDEFINED_TEMPLATES), equal_to(6))


def test_seed_predefined_templates_is_idempotent():
    with given(_GIVEN) as context:
        service: TemplateService = context.injector.get(TemplateService)
        client: TestClient = context.client

        with when("I seed twice"):
            service.seed_predefined_templates()
            service.seed_predefined_templates()

        with then("each lineage still has exactly one version"):
            response = client.get(f"{_BASE}?source=pre-defined", headers=_auth(context))
            body = response.json()
            assert_that(body["total"], equal_to(6))
            for item in body["items"]:
                assert_that(item["version"], equal_to(1))


def test_seed_does_not_clobber_edited_predefined_template():
    with given(_GIVEN) as context:
        service: TemplateService = context.injector.get(TemplateService)
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        client: TestClient = context.client
        org_id = context.organization.id
        service.seed_predefined_templates()

        with when("I edit scrum-master and reseed"):
            client.patch(
                f"{_BASE}/scrum-master",
                json={"soul_md": "# Edited Soul"},
                headers=_auth(context),
            )
            service.seed_predefined_templates()

        with then("the edited org fork stays the latest"):
            latest = repository.get_latest_org_template(org_id, "scrum-master")
            assert latest is not None
            assert_that(latest.version, equal_to(2))
            assert_that(latest.soul_md, equal_to("# Edited Soul"))
            assert_that(latest.template_source, equal_to(TemplateSource.PRE_DEFINED))
            assert_that(latest.forked_from_platform_template_id, is_not(none()))
            assert_that(latest.fork_baseline_platform_template_id, equal_to(latest.forked_from_platform_template_id))

        with when("the organization edits the fork again"):
            response = client.patch(
                f"{_BASE}/scrum-master",
                json={"tools_md": "# Edited Tools"},
                headers=_auth(context),
            )

        with then("the new org version preserves the original fork and its baseline"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            latest_again = repository.get_latest_org_template(org_id, "scrum-master")
            assert latest_again is not None
            assert_that(latest_again.version, equal_to(3))
            assert_that(
                latest_again.forked_from_platform_template_id,
                equal_to(latest.forked_from_platform_template_id),
            )
            assert_that(
                latest_again.fork_baseline_platform_template_id,
                equal_to(latest.fork_baseline_platform_template_id),
            )

        with then("the platform v1 seed is untouched"):
            platform = repository.get_latest_platform_template("scrum-master")
            assert platform is not None
            assert_that(platform.version, equal_to(1))


def test_seed_does_not_refresh_existing_platform_v1():
    """Bootstrap only inserts a lineage once; a published/edited v1 row is never touched again.

    See docs/adr/2026-08-03-platform-template-file-based-bootstrap.md — ownership of an
    existing lineage's content passes to the Draft Template Version admin flow.
    """
    with given(_GIVEN) as context:
        service: TemplateService = context.injector.get(TemplateService)
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        service.seed_predefined_templates()

        with when("the seeded v1 diverges from the seed files then we reseed"):
            seeded = repository.get_latest_platform_template("scrum-master")
            assert seeded is not None
            seeded.user_md = "# Admin-edited content"
            repository.save_platform_template(seeded)
            service.seed_predefined_templates()

        with then("the v1 row is left exactly as it was, not reset to the seed files"):
            latest = repository.get_latest_platform_template("scrum-master")
            assert latest is not None
            assert_that(latest.version, equal_to(1))
            assert_that(latest.user_md, equal_to("# Admin-edited content"))


def test_platform_template_update_rebases_org_overrides_and_preserves_agent_pins():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Baseline Skill", global_skill=True),
            there_is_a_skill(name="Organization Override Skill", global_skill=True),
            there_is_a_skill(name="New Platform Skill", global_skill=True),
        ]
    ) as context:
        client: TestClient = context.client
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        skill_repository: SkillRepository = context.injector.get(SkillRepository)
        baseline_skill = skill_repository.get_by_name_global("Baseline Skill")
        override_skill = skill_repository.get_by_name_global("Organization Override Skill")
        new_platform_skill = skill_repository.get_by_name_global("New Platform Skill")
        assert baseline_skill is not None
        assert override_skill is not None
        assert new_platform_skill is not None

        platform_v1 = _platform_version("manual", 1)
        repository.save_platform_template(platform_v1)
        repository.save_platform_template_skills(platform_v1.id, {baseline_skill.id: None})

        with when("an agent is pinned to the original platform version"):
            agent_response = client.post(
                _AGENTS_BASE,
                json={
                    "name": "Pinned Manual Agent",
                    "platform": "slack",
                    "slack_bot_token": "xoxb-token",
                    "slack_app_token": "xapp-1-token",
                    "template_slug": "manual",
                    "skill_ids": [str(baseline_skill.id)],
                },
                headers=_auth(context),
            )

        with then("the agent starts on platform v1"):
            assert_that(agent_response.status_code, equal_to(status.HTTP_201_CREATED))
            agent_id = agent_response.json()["id"]
            assert_that(agent_response.json()["template_version"], equal_to(1))

        with when("the organization creates a fork with a soul and skill override"):
            fork_response = client.patch(
                f"{_BASE}/manual",
                json={
                    "soul_md": "organization soul",
                    "required_skill_ids": [str(override_skill.id)],
                },
                headers=_auth(context),
            )

        with then("the fork is created at org version 2"):
            assert_that(fork_response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(fork_response.json()["version"], equal_to(2))

        platform_v2 = _platform_version(
            "manual",
            2,
            soul_md="platform soul 2",
            tools_md="platform tools 2",
            description="platform description 2",
        )
        repository.save_platform_template(platform_v2)
        repository.save_platform_template_skills(platform_v2.id, {new_platform_skill.id: None})

        with when("the organization applies the available platform update"):
            response = client.post(f"{_BASE}/manual/platform-update", headers=_auth(context))

        with then("changed org fields and skills win over the new platform version"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["version"], equal_to(3))
            assert_that(body["soul_md"], equal_to("organization soul"))
            assert_that(body["tools_md"], equal_to("platform tools 2"))
            assert_that(body["description"], equal_to("platform description 2"))
            assert_that(body["forked_from_platform_template_id"], equal_to(str(platform_v1.id)))
            assert_that(body["fork_baseline_platform_template_id"], equal_to(str(platform_v2.id)))
            assert_that([skill["name"] for skill in body["required_skills"]], equal_to(["Organization Override Skill"]))

        with then("the existing agent pin is unchanged"):
            refreshed_agent = client.get(f"{_AGENTS_BASE}/{agent_id}", headers=_auth(context))
            assert_that(refreshed_agent.status_code, equal_to(status.HTTP_200_OK))
            assert_that(refreshed_agent.json()["template_version"], equal_to(1))


def test_platform_template_update_requires_a_newer_platform_version():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        repository.save_platform_template(_platform_version("manual", 1))

        fork_response = client.patch(
            f"{_BASE}/manual",
            json={"soul_md": "organization soul"},
            headers=_auth(context),
        )
        assert_that(fork_response.status_code, equal_to(status.HTTP_200_OK))

        with when("the organization applies an update while the platform is still at the baseline"):
            response = client.post(f"{_BASE}/manual/platform-update", headers=_auth(context))

        with then("the action returns a conflict and creates no new version"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(len(repository.find_org_versions(context.organization.id, "manual")), equal_to(1))


def test_platform_template_update_rejects_non_fork_templates():
    with given([*_GIVEN, there_is_a_template(slug="custom", name="Custom")]) as context:
        response = context.client.post(f"{_BASE}/custom/platform-update", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_platform_template_update_requires_template_manage_permission():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="custom", name="Custom"),
            _there_is_a_member_actor(),
            role_lacks_permission(OrganizationRole.MEMBER, PermissionKey.TEMPLATE_MANAGE),
        ]
    ) as context:
        response = context.client.post(f"{_BASE}/custom/platform-update", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_seed_predefined_templates_seeds_scrum_master_skills():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira", global_skill=True),
            there_is_a_skill(name="Confluence", global_skill=True),
        ]
    ) as context:
        service: TemplateService = context.injector.get(TemplateService)
        client: TestClient = context.client

        with when("I seed the global predefined catalogue"):
            service.seed_predefined_templates()

        with then("scrum-master has Jira and Confluence as required skills"):
            response = client.get(f"{_BASE}/scrum-master", headers=_auth(context))
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            skill_names = [s["name"] for s in response.json()["required_skills"]]
            assert_that(skill_names, has_items("Jira", "Confluence"))


def test_seed_predefined_templates_does_not_duplicate_skill_rows():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira", global_skill=True),
            there_is_a_skill(name="Confluence", global_skill=True),
        ]
    ) as context:
        service: TemplateService = context.injector.get(TemplateService)
        repository: TemplateRepository = context.injector.get(TemplateRepository)

        with when("I seed twice"):
            service.seed_predefined_templates()
            service.seed_predefined_templates()

        with then("scrum-master still has exactly two required skills"):
            template = repository.get_latest_platform_template("scrum-master")
            assert template is not None
            skill_map = repository.get_platform_required_skill_map(template.id)
            assert_that(len(skill_map), equal_to(2))


def test_seed_predefined_templates_code_reviewer_requires_github_or_bitbucket():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="GitHub", global_skill=True),
            there_is_a_skill(name="Bitbucket", global_skill=True),
        ]
    ) as context:
        service: TemplateService = context.injector.get(TemplateService)
        client: TestClient = context.client

        with when("I seed the global predefined catalogue"):
            service.seed_predefined_templates()

        with then("code-reviewer requires GitHub or Bitbucket as an 'at least one of' group"):
            response = client.get(f"{_BASE}/code-reviewer", headers=_auth(context))
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            required_skills = response.json()["required_skills"]
            skill_names = {s["name"] for s in required_skills}
            assert_that(skill_names, equal_to({"GitHub", "Bitbucket"}))
            group_keys = {s["group_key"] for s in required_skills}
            assert_that(group_keys, equal_to({"github-or-bitbucket"}))


def test_seed_predefined_templates_code_reviewer_seeds_partial_group_when_only_one_host_skill_exists():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="GitHub", global_skill=True),
        ]
    ) as context:
        service: TemplateService = context.injector.get(TemplateService)
        client: TestClient = context.client

        with when("I seed the global predefined catalogue without a Bitbucket skill present"):
            service.seed_predefined_templates()

        with then("code-reviewer requires only the available host skill, as a 1-member group"):
            response = client.get(f"{_BASE}/code-reviewer", headers=_auth(context))
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            required_skills = response.json()["required_skills"]
            assert_that(len(required_skills), equal_to(1))
            assert_that(required_skills[0]["name"], equal_to("GitHub"))
            assert_that(required_skills[0]["group_key"], equal_to("github-or-bitbucket"))


def test_seed_predefined_templates_does_not_restore_cleared_skills_on_existing_lineage():
    """Required-skill sync only runs the moment a lineage is first inserted; an existing
    lineage's skills are left alone on subsequent reseeds, same as its content."""
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="Jira", global_skill=True),
        ]
    ) as context:
        service: TemplateService = context.injector.get(TemplateService)
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        service.seed_predefined_templates()

        with when("the seeded skills are cleared from the DB then we reseed"):
            template = repository.get_latest_platform_template("jira-task-helper")
            assert template is not None
            repository.save_platform_template_skills(template.id, {})
            service.seed_predefined_templates()

        with then("the required skills stay cleared"):
            template = repository.get_latest_platform_template("jira-task-helper")
            assert template is not None
            skill_map = repository.get_platform_required_skill_map(template.id)
            assert_that(len(skill_map), equal_to(0))


def test_seed_predefined_templates_is_idempotent_for_group_keys():
    with given(
        [
            *_GIVEN,
            there_is_a_skill(name="GitHub", global_skill=True),
            there_is_a_skill(name="Bitbucket", global_skill=True),
        ]
    ) as context:
        service: TemplateService = context.injector.get(TemplateService)
        repository: TemplateRepository = context.injector.get(TemplateRepository)

        with when("I seed twice"):
            service.seed_predefined_templates()
            service.seed_predefined_templates()

        with then("code-reviewer still has exactly two required skills in the same group"):
            template = repository.get_latest_platform_template("code-reviewer")
            assert template is not None
            skill_map = repository.get_platform_required_skill_map(template.id)
            assert_that(len(skill_map), equal_to(2))
            assert_that(set(skill_map.values()), equal_to({"github-or-bitbucket"}))


def test_predefined_content_keeps_raw_placeholders():
    with given(_GIVEN) as context:
        service: TemplateService = context.injector.get(TemplateService)
        repository: TemplateRepository = context.injector.get(TemplateRepository)

        with when("I seed the global predefined catalogue"):
            service.seed_predefined_templates()

        with then("scrum-master soul still contains raw placeholders"):
            template = repository.get_latest_platform_template("scrum-master")
            assert template is not None
            assert_that(template.soul_md, contains_string("{{ agent_display_name }}"))


# --- shared lineage lifecycle ---


def test_agent_repin_moves_only_that_agent():
    with given(
        [
            *_GIVEN,
            there_is_a_template(slug="shared", name="Shared", version=1),
            there_is_a_template(slug="shared", name="Shared", version=2),
        ]
    ) as context:
        client: TestClient = context.client
        create_payload = {
            "platform": "slack",
            "slack_bot_token": "xoxb-token",
            "slack_app_token": "xapp-1-token",
            "template_slug": "shared",
        }

        with when("two agents are hired from the same lineage (latest = v2)"):
            first = client.post(
                _AGENTS_BASE,
                json={**create_payload, "name": "First"},
                headers=_auth(context),
            ).json()
            second = client.post(
                _AGENTS_BASE,
                json={
                    **create_payload,
                    "name": "Second",
                    "slack_bot_token": "xoxb-token-2",
                    "slack_app_token": "xapp-1-token-2",
                },
                headers=_auth(context),
            ).json()
            assert_that(first["template_version"], equal_to(2))
            assert_that(second["template_version"], equal_to(2))

        with when("the first agent is re-pinned to v1"):
            response = client.patch(
                f"{_AGENTS_BASE}/{first['id']}",
                json={"template_slug": "shared", "template_version": 1},
                headers=_auth(context),
            )

        with then("only the first agent moves; no new template version is created"):
            assert_that(response.json()["template_version"], equal_to(1))
            second_refreshed = client.get(f"{_AGENTS_BASE}/{second['id']}", headers=_auth(context)).json()
            assert_that(second_refreshed["template_version"], equal_to(2))
            catalog = client.get(f"{_BASE}/shared", headers=_auth(context)).json()
            assert_that(catalog["version"], equal_to(2))


def test_default_soul_md_is_nonempty():
    assert_that(DEFAULT_SOUL_MD, contains_string("SOUL"))

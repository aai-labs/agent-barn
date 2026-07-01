from fastapi import status
from hamcrest import (
    assert_that,
    contains_string,
    equal_to,
    is_not,
    none,
)
from starlette.testclient import TestClient

from api.domains.organizations.models import Organization
from api.domains.organizations.repository import OrganizationRepository
from api.domains.templates.defaults import DEFAULT_SOUL_MD
from api.domains.templates.models import TemplateSource
from api.domains.templates.predefined import PREDEFINED_TEMPLATES
from api.domains.templates.repository import TemplateRepository
from api.domains.templates.service import TemplateService
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
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.template import there_is_a_template

_BASE = "/api/v1/templates"
_AGENTS_BASE = "/api/v1/agents"

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


# --- list ---


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
        org_repository: OrganizationRepository = context.injector.get(
            OrganizationRepository
        )
        other_org = Organization(name="Other Org")
        org_repository.save(other_org)
        there_is_a_template(slug="theirs", name="Theirs", organization_id=other_org.id)(
            context
        )

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
            there_is_a_template(
                slug="seeded", name="Seeded", source=TemplateSource.PRE_DEFINED
            ),
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


# --- get ---


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


# --- versions ---


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


# --- create ---


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
    with given(
        [*_GIVEN, there_is_a_template(slug="my-helper", name="My Helper")]
    ) as context:
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
        there_is_a_template(
            slug="my-helper", name="My Helper", organization_id=other_org.id
        )(context)

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
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


def test_create_template_empty_name_returns_422():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I create a template with an empty name"):
            response = client.post(
                _BASE, json={"template_name": ""}, headers=_auth(context)
            )

        with then("it returns 422"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


# --- update ---


def test_update_template_creates_new_version_with_merge():
    with given(
        [
            *_GIVEN,
            there_is_a_template(
                slug="alpha", name="Alpha", soul_md="# Old Soul", tools_md="# Tools"
            ),
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
            there_is_a_template(
                slug="seeded", name="Seeded", source=TemplateSource.PRE_DEFINED
            ),
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
    with given(
        [*_GIVEN, there_is_a_template(slug="test-template", name="Test Template")]
    ) as context:
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
            agent_response = client.get(
                f"{_AGENTS_BASE}/{agent['id']}", headers=_auth(context)
            )
            assert_that(agent_response.json()["template_version"], equal_to(1))


def test_update_template_unknown_slug_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I update a non-existent template"):
            response = client.patch(
                f"{_BASE}/nope", json={"soul_md": "# X"}, headers=_auth(context)
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_update_template_empty_body_returns_422():
    with given([*_GIVEN, there_is_a_template(slug="alpha", name="Alpha")]) as context:
        client: TestClient = context.client

        with when("I send an empty update"):
            response = client.patch(f"{_BASE}/alpha", json={}, headers=_auth(context))

        with then("it returns 422"):
            assert_that(
                response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY)
            )


# --- seeding ---


def test_seed_predefined_templates_creates_three_lineages():
    with given(_GIVEN) as context:
        service: TemplateService = context.injector.get(TemplateService)
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        org_id = context.organization.id

        with when("I seed the org"):
            service.seed_predefined_templates(org_id)

        with then("the three pre-defined lineages exist at v1"):
            for slug in ("general-purpose", "scrum-master", "code-reviewer"):
                template = repository.get_latest_template(org_id, slug)
                assert_that(template, is_not(none()))
                assert template is not None
                assert_that(template.version, equal_to(1))
                assert_that(
                    template.template_source, equal_to(TemplateSource.PRE_DEFINED)
                )

        with then("the registry and DB agree on the count"):
            assert_that(len(PREDEFINED_TEMPLATES), equal_to(3))


def test_seed_predefined_templates_is_idempotent():
    with given(_GIVEN) as context:
        service: TemplateService = context.injector.get(TemplateService)
        client: TestClient = context.client
        org_id = context.organization.id

        with when("I seed twice"):
            service.seed_predefined_templates(org_id)
            service.seed_predefined_templates(org_id)

        with then("each lineage still has exactly one version"):
            response = client.get(f"{_BASE}?source=pre-defined", headers=_auth(context))
            body = response.json()
            assert_that(body["total"], equal_to(3))
            for item in body["items"]:
                assert_that(item["version"], equal_to(1))


def test_seed_does_not_clobber_edited_predefined_template():
    with given(_GIVEN) as context:
        service: TemplateService = context.injector.get(TemplateService)
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        client: TestClient = context.client
        org_id = context.organization.id
        service.seed_predefined_templates(org_id)

        with when("I edit scrum-master and reseed"):
            client.patch(
                f"{_BASE}/scrum-master",
                json={"soul_md": "# Edited Soul"},
                headers=_auth(context),
            )
            service.seed_predefined_templates(org_id)

        with then("the edited version stays the latest"):
            latest = repository.get_latest_template(org_id, "scrum-master")
            assert latest is not None
            assert_that(latest.version, equal_to(2))
            assert_that(latest.soul_md, equal_to("# Edited Soul"))


def test_seed_refreshes_stale_predefined_v1_in_place():
    with given(_GIVEN) as context:
        service: TemplateService = context.injector.get(TemplateService)
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        org_id = context.organization.id
        service.seed_predefined_templates(org_id)

        with when("the seeded v1 drifts from the code (an old seed) then we reseed"):
            seeded = repository.get_latest_template(org_id, "scrum-master")
            assert seeded is not None
            seeded.user_md = "# STALE - asks for credentials"
            repository.save_template(seeded)
            service.seed_predefined_templates(org_id)

        with then("the v1 row is refreshed in place to the current code content"):
            latest = repository.get_latest_template(org_id, "scrum-master")
            assert latest is not None
            assert_that(latest.version, equal_to(1))
            assert_that(latest.user_md, is_not(contains_string("STALE")))
            assert_that(latest.template_source, equal_to(TemplateSource.PRE_DEFINED))


def test_predefined_content_keeps_raw_placeholders():
    with given(_GIVEN) as context:
        service: TemplateService = context.injector.get(TemplateService)
        repository: TemplateRepository = context.injector.get(TemplateRepository)
        org_id = context.organization.id

        with when("I seed the org"):
            service.seed_predefined_templates(org_id)

        with then("scrum-master soul still contains raw placeholders"):
            template = repository.get_latest_template(org_id, "scrum-master")
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
                json={**create_payload, "name": "Second"},
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
            second_refreshed = client.get(
                f"{_AGENTS_BASE}/{second['id']}", headers=_auth(context)
            ).json()
            assert_that(second_refreshed["template_version"], equal_to(2))
            catalog = client.get(f"{_BASE}/shared", headers=_auth(context)).json()
            assert_that(catalog["version"], equal_to(2))


def test_default_soul_md_is_nonempty():
    assert_that(DEFAULT_SOUL_MD, contains_string("SOUL"))

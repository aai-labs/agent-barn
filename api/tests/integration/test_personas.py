from datetime import UTC, datetime

import pytest
from fastapi import status
from hamcrest import assert_that, equal_to, has_length, is_not, none
from sqlmodel import Session

from api.domains.agents.models import AgentType
from api.domains.personas.models import AgentPersona, AgentPersonaVersion
from api.tests.core.givenpy import given
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

BASE = "/api/v1/organizations/{organization_id}/agents"


def _given(*, flag: str = "true", agent_type: AgentType = AgentType.HERMES, soul_md: str = "# Soul\n\nTest soul."):
    return [
        set_env_variable({"PERSONAS_ENABLED": flag, "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        there_is_an_agent(name="Ada", agent_type=agent_type, soul_md=soul_md),
    ]


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _url(context, suffix: str = "") -> str:
    return f"{BASE}/{context.agent.id}/personas{suffix}"


def _seed(context, key="sales", versions=1, deleted=False) -> AgentPersona:
    with Session(context.postgres_delegate.engine, expire_on_commit=False) as session:
        persona = AgentPersona(
            organization_id=context.organization.id,
            agent_id=context.agent.id,
            key=key,
            display_name=key.title(),
            emoji="💼",
            current_version=versions,
            deleted_at=datetime.now(UTC) if deleted else None,
        )
        session.add(persona)
        session.flush()
        for number in range(1, versions + 1):
            session.add(
                AgentPersonaVersion(
                    organization_id=context.organization.id,
                    persona_id=persona.id,
                    version=number,
                    soul_md=f"{key} soul v{number}",
                    identity_md=f"{key} identity v{number}",
                    author_user_id=context.user.id,
                )
            )
        session.commit()
    return persona


def test_the_list_starts_with_the_default_then_active_personas_without_bodies():
    with given(_given()) as context:
        _seed(context, "sales")
        _seed(context, "lawyer")
        _seed(context, "gone", deleted=True)

        response = context.client.get(_url(context), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["enabled"], equal_to(True))
        assert_that([item["key"] for item in body["personas"]], equal_to(["default", "sales", "lawyer"]))
        default, sales = body["personas"][0], body["personas"][1]
        assert_that(default["id"], none())
        assert_that(default["is_default"], equal_to(True))
        assert_that(default["display_name"], equal_to("Ada"))
        assert_that(default["current_version"], none())
        assert_that(sales["is_default"], equal_to(False))
        assert_that(sales["emoji"], equal_to("💼"))
        assert_that(sales["current_version"], equal_to(1))
        assert_that("soul_md" in sales, equal_to(False))


def test_the_list_reports_disabled_when_the_flag_is_off_but_still_shows_existing_rows():
    with given(_given(flag="false")) as context:
        _seed(context, "sales")

        body = context.client.get(_url(context), headers=_auth(context)).json()

        assert_that(body["enabled"], equal_to(False))
        assert_that([item["key"] for item in body["personas"]], equal_to(["default", "sales"]))


def test_an_openclaw_agent_only_has_the_default_and_is_never_enabled():
    with given(_given(agent_type=AgentType.OPENCLAW)) as context:
        _seed(context, "sales")

        body = context.client.get(_url(context), headers=_auth(context)).json()

        assert_that(body["enabled"], equal_to(False))
        assert_that([item["key"] for item in body["personas"]], equal_to(["default"]))
        response = context.client.get(_url(context, "/sales"), headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_reading_a_persona_returns_its_current_version():
    with given(_given()) as context:
        _seed(context, "sales", versions=2)

        response = context.client.get(_url(context, "/sales"), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["current_version"], equal_to(2))
        assert_that(body["soul_md"], equal_to("sales soul v2"))
        assert_that(body["identity_md"], equal_to("sales identity v2"))


def test_reading_the_default_renders_the_template_placeholders():
    with given(_given(soul_md="You are {{agent_display_name}}.")) as context:
        response = context.client.get(_url(context, "/default"), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that(body["is_default"], equal_to(True))
        assert_that(body["id"], none())
        assert_that(body["soul_md"], equal_to("You are Ada."))
        assert_that(body["identity_md"], is_not(none()))


@pytest.mark.parametrize("key", ["nosuch", "gone"])
def test_an_unknown_or_deleted_persona_is_not_found(key):
    with given(_given()) as context:
        _seed(context, "gone", deleted=True)

        for suffix in (f"/{key}", f"/{key}/versions"):
            response = context.client.get(_url(context, suffix), headers=_auth(context))
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_versions_are_listed_newest_first():
    with given(_given()) as context:
        _seed(context, "sales", versions=3)

        response = context.client.get(_url(context, "/sales/versions"), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        body = response.json()
        assert_that([item["version"] for item in body], equal_to([3, 2, 1]))
        assert_that(body[0]["soul_md"], equal_to("sales soul v3"))
        assert_that(body[0]["author_user_id"], equal_to(str(context.user.id)))


def test_the_default_has_no_versions():
    with given(_given()) as context:
        response = context.client.get(_url(context, "/default/versions"), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), has_length(0))

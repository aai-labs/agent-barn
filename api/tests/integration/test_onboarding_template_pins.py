from unittest.mock import MagicMock
from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_item
from starlette.testclient import TestClient

from api.domains.agents.models import AgentStatus, AgentType
from api.domains.agents.service import AgentService
from api.domains.auth.models import CurrentUserContext
from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import PermissionKey
from api.domains.templates.defaults import ONBOARDING_TEMPLATE_KEY
from api.domains.templates.service import TemplateService
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.kubernetes.client import KubernetesClient
from api.infrastructure.litellm.client import ONE_OFF_BUDGET_WINDOW
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
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.rbac import role_lacks_permission
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_BASE = "/api/v1/organizations/{organization_id}/agents"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_EXTERNAL_URL": "https://api.test.com",
            "HERMES_IMAGE": "nousresearch/hermes-agent:v1.0",
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


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _user_context(context) -> CurrentUserContext:
    return CurrentUserContext(
        user=context.user,
        organization_ids=[context.organization.id],
        user_organization_map={context.organization.id: context.organization_user},
        current_user_organization=context.organization_user,
    )


def _seeded(context) -> None:
    context.injector.get(TemplateService).seed_predefined_templates()


def test_hiring_from_the_onboarding_template_is_not_found():
    with given(_GIVEN) as context:
        _seeded(context)
        client: TestClient = context.client

        with when("I hire an Agent from the onboarding template, with and without a version"):
            latest = client.post(
                _BASE,
                json={"name": "Ava", "agent_type": "hermes", "template_key": ONBOARDING_TEMPLATE_KEY},
                headers=_auth(context),
            )
            pinned = client.post(
                _BASE,
                json={
                    "name": "Ava",
                    "agent_type": "hermes",
                    "template_key": ONBOARDING_TEMPLATE_KEY,
                    "template_version": 1,
                },
                headers=_auth(context),
            )

        with then("both are not found and no Agent exists"):
            assert_that(latest.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(pinned.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(client.get(_BASE, headers=_auth(context)).json()["total"], equal_to(0))


def test_an_agent_cannot_be_repinned_onto_the_onboarding_template():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _seeded(context)

        with when("I re-pin an ordinary Agent to the onboarding template"):
            response = context.client.patch(
                f"{_BASE}/{context.agent.id}",
                json={"template_key": ONBOARDING_TEMPLATE_KEY, "template_version": 1},
                headers=_auth(context),
            )

        with then("it is not found and the Agent keeps its template"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            agent = context.client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()
            assert agent["template_key"] != ONBOARDING_TEMPLATE_KEY


def test_an_agent_cannot_select_the_onboarding_template():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        _seeded(context)
        client: TestClient = context.client
        agent = client.get(f"{_BASE}/{context.agent.id}", headers=_auth(context)).json()

        with when("I select the onboarding template for an ordinary Agent"):
            response = client.post(
                f"{_BASE}/{context.agent.id}/configuration/select",
                json={
                    "selection_type": "platform",
                    "template_key": ONBOARDING_TEMPLATE_KEY,
                    "template_version": 1,
                    "expected_agent_updated_at": agent["updated_at"],
                },
                headers=_auth(context),
            )

        with then("it is not found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_onboarding_creates_a_hermes_agent_on_the_onboarding_template():
    with given(_GIVEN) as context:
        _seeded(context)
        service: AgentService = context.injector.get(AgentService)

        with when("onboarding creates the trial Agent"):
            created = service.create_onboarding_agent("Ava the Assistant", _user_context(context))

        with then("it is a Hermes Agent pinned to the onboarding template"):
            assert_that(created.agent_type, equal_to(AgentType.HERMES))
            assert_that(created.template_key, equal_to(ONBOARDING_TEMPLATE_KEY))
            assert_that(created.template_version, equal_to(1))


def test_the_onboarding_agent_still_reads_and_reselects_its_own_template():
    with given(_GIVEN) as context:
        _seeded(context)
        client: TestClient = context.client
        created = context.injector.get(AgentService).create_onboarding_agent(
            "Ava the Assistant", _user_context(context)
        )

        with when("its owner reads its template and configuration and re-selects its own version"):
            template = client.get(f"{_BASE}/{created.id}/template/1", headers=_auth(context))
            configuration = client.get(f"{_BASE}/{created.id}/configuration", headers=_auth(context))
            agent = client.get(f"{_BASE}/{created.id}", headers=_auth(context)).json()
            reselected = client.post(
                f"{_BASE}/{created.id}/configuration/select",
                json={
                    "selection_type": "platform",
                    "template_key": ONBOARDING_TEMPLATE_KEY,
                    "template_version": 1,
                    "expected_agent_updated_at": agent["updated_at"],
                },
                headers=_auth(context),
            )
            repinned = client.patch(
                f"{_BASE}/{created.id}",
                json={"template_key": ONBOARDING_TEMPLATE_KEY, "template_version": 1},
                headers=_auth(context),
            )

        with then("all of it works for the Agent that is already on it"):
            assert_that(template.status_code, equal_to(status.HTTP_200_OK))
            assert_that(template.json()["bootstrap_md"], contains_string("First conversation"))
            assert_that(configuration.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                [version["source_template_key"] for version in configuration.json()["shared_versions"]],
                has_item(ONBOARDING_TEMPLATE_KEY),
            )
            assert_that(reselected.status_code, equal_to(status.HTTP_200_OK))
            assert_that(repinned.status_code, equal_to(status.HTTP_200_OK))


_READY_MADE = f"{_BASE}/ready-made"


def _the_organization_is_a_trial():
    def step(context):
        organizations = context.injector.get(OrganizationRepository)
        organization = organizations.get(context.organization.id)
        organization.is_trial = True
        organization.created_by_user_id = context.user.id
        organization.llm_budget_usd = 10
        organization.llm_budget_duration = ONE_OFF_BUDGET_WINDOW
        organizations.save(organization)

    return step


def _there_is_a_member_actor():
    def step(context):
        user_id = uuid7()
        there_is_a_user(id=user_id, email="member-ready-made@example.com", role=OrganizationRole.MEMBER)(context)
        there_is_an_access_token_for_user(user_id=user_id)(context)

    return step


def test_a_trial_hires_the_ready_made_assistant_on_the_onboarding_template():
    with given([*_GIVEN, _the_organization_is_a_trial()]) as context:
        _seeded(context)

        with when("the trial hires the ready-made assistant"):
            response = context.client.post(_READY_MADE, json={"name": "Brandon the Assistant"}, headers=_auth(context))

        with then("a Hermes Agent on the Onboarding Template with automatic approval is created"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            body = response.json()
            assert_that(body["name"], equal_to("Brandon the Assistant"))
            assert_that(body["agent_type"], equal_to(AgentType.HERMES.value))
            assert_that(body["template_key"], equal_to(ONBOARDING_TEMPLATE_KEY))
            assert_that(body["approval_mode"], equal_to("auto"))


def test_a_ready_made_assistant_starts_with_the_first_conversation_script():
    with given([*_GIVEN, _the_organization_is_a_trial()]) as context:
        _seeded(context)
        agent = context.client.post(_READY_MADE, json={"name": "Brandon the Assistant"}, headers=_auth(context)).json()

        with when("it starts"):
            started = context.client.post(f"{_BASE}/{agent['id']}/start", headers=_auth(context))

        with then("its ConfigMap carries the script"):
            assert_that(started.status_code, equal_to(status.HTTP_200_OK))
            k8s: MagicMock = context.injector.get(KubernetesClient)
            config_map = k8s.create_config_map.call_args.args[1].data
            assert_that(config_map["BOOTSTRAP.md"], contains_string("First conversation"))


def test_an_organization_that_is_not_on_a_trial_cannot_hire_the_ready_made_assistant():
    with given(_GIVEN) as context:
        _seeded(context)

        with when("an ordinary organization asks for the ready-made assistant"):
            response = context.client.post(_READY_MADE, json={"name": "Brandon the Assistant"}, headers=_auth(context))

        with then("it is refused and no Agent exists"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(context.client.get(_BASE, headers=_auth(context)).json()["total"], equal_to(0))


def test_a_member_who_cannot_create_agents_cannot_hire_the_ready_made_assistant():
    with given(
        [
            *_GIVEN,
            _the_organization_is_a_trial(),
            _there_is_a_member_actor(),
            role_lacks_permission(OrganizationRole.MEMBER, PermissionKey.AGENT_CREATE),
        ]
    ) as context:
        _seeded(context)

        with when("the member asks for the ready-made assistant"):
            response = context.client.post(_READY_MADE, json={"name": "Brandon the Assistant"}, headers=_auth(context))

        with then("it is forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_the_ready_made_assistant_counts_against_the_trial_agent_limit():
    with given([*_GIVEN, _the_organization_is_a_trial()]) as context:
        _seeded(context)
        first = context.client.post(_READY_MADE, json={"name": "Brandon the Assistant"}, headers=_auth(context))

        with when("the trial, at its one-Agent limit, hires another"):
            second = context.client.post(_READY_MADE, json={"name": "Bella the Assistant"}, headers=_auth(context))

        with then("the second is refused"):
            assert_that(first.status_code, equal_to(status.HTTP_201_CREATED))
            assert_that(second.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_the_ready_made_assistant_needs_a_name():
    with given([*_GIVEN, _the_organization_is_a_trial()]) as context:
        _seeded(context)

        response = context.client.post(_READY_MADE, json={"name": ""}, headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))

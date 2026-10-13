"""How many Agents an Organization may run (AF-381).

Every Organization has an Agent limit: its own, set by a Platform Administrator, else the
default for its kind — the trial setting for a trial, the deployment's
`ORGANIZATION_DEFAULT_AGENT_LIMIT` for any other (unset: no limit). Lowering a limit
never removes Agents; it only stops new hires.
"""

import pytest
from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_entries

from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import OrganizationRole
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.integration.test_spend_limits import events_named
from api.tests.integration.test_trial_organizations import AGENTS, CREATE, the_organization_is_a_trial
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, MockK8sModule, MockLiteLLMModule, use_org_for_auth
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.events import event_delivery_tables_are_clean
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

PLATFORM_AGENT_LIMIT = "/api/v1/platform/organizations/{organization_id}/agent-limit"


def _setup(*steps, default: str = ""):
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
                "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
                "ORGANIZATION_DEFAULT_AGENT_LIMIT": default,
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        event_delivery_tables_are_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        there_is_a_template(),
        *steps,
    ]


def the_organization_may_run(limit: int | None):
    def step(context):
        organizations = context.injector.get(OrganizationRepository)
        organization = organizations.get(context.organization.id)
        organization.agent_limit = limit
        organizations.save(organization)

    return step


def auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def hire(context, name: str):
    return context.client.post(AGENTS, json={**CREATE, "name": name}, headers=auth(context))


def a_platform_administrator_is_signed_in():
    def step(context):
        # A plain Member of the Organization, so the platform role alone is what counts.
        there_is_a_user(email="platform@example.com", is_platform_admin=True, role=OrganizationRole.MEMBER)(context)
        there_is_an_access_token_for_user()(context)

    return step


def put_limit(context, payload):
    return context.client.put(
        PLATFORM_AGENT_LIMIT.format(organization_id=context.organization.id), json=payload, headers=auth(context)
    )


# --- the limit in force ------------------------------------------------------------------


def test_the_deployment_default_limits_an_ordinary_organization():
    with given(_setup(default="1")) as context:
        first = hire(context, "First")

        with when("the owner hires past the default"):
            second = hire(context, "Second")

        with then("it is refused, saying why"):
            assert_that(first.status_code, equal_to(status.HTTP_201_CREATED), first.text)
            assert_that(second.status_code, equal_to(status.HTTP_409_CONFLICT))
            assert_that(second.json()["detail"], contains_string("one agent"))


def test_an_organizations_own_limit_beats_the_default():
    with given(_setup(the_organization_may_run(2), default="1")) as context:
        responses = [hire(context, name) for name in ("First", "Second", "Third")]

        assert_that([r.status_code for r in responses], equal_to([201, 201, 409]))
        assert_that(responses[2].json()["detail"], contains_string("2 agents"))


def test_a_trials_own_limit_beats_the_trial_setting():
    with given(_setup(the_organization_is_a_trial(), the_organization_may_run(2))) as context:
        responses = [hire(context, name) for name in ("First", "Second")]

        assert_that([r.status_code for r in responses], equal_to([201, 201]))


def test_no_default_means_no_limit():
    with given(_setup()) as context:
        responses = [hire(context, name) for name in ("First", "Second", "Third")]

        assert_that([r.status_code for r in responses], equal_to([201, 201, 201]))


def test_the_organization_read_gives_the_limit_in_force():
    with given(_setup(default="4")) as context:
        response = context.client.get(f"/api/v1/organizations/{context.organization.id}", headers=auth(context))

        assert_that(response.json(), has_entries(is_trial=False, agent_limit=4))


def test_a_trials_read_gives_the_trial_setting():
    with given(_setup(the_organization_is_a_trial(), default="4")) as context:
        response = context.client.get(f"/api/v1/organizations/{context.organization.id}", headers=auth(context))

        assert_that(response.json(), has_entries(is_trial=True, agent_limit=1))


# --- a Platform Administrator sets it ------------------------------------------------------


def test_a_platform_administrator_sets_an_organizations_limit():
    with given(_setup(a_platform_administrator_is_signed_in(), default="1")) as context:
        with when("they allow the Organization three Agents"):
            response = put_limit(context, {"agent_limit": 3})

        with then("it is stored, shown, and audited"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
            assert_that(response.json(), has_entries(agent_limit=3, agent_limit_in_force=3))
            stored = context.injector.get(OrganizationRepository).get(context.organization.id)
            assert_that(stored.agent_limit, equal_to(3))
            (event,) = events_named(context, "organization.agent_limit.changed")
            assert_that(event.payload, has_entries(agent_limit=3, previous_agent_limit=None))


def test_clearing_an_organizations_limit_returns_it_to_the_default():
    with given(_setup(the_organization_may_run(3), a_platform_administrator_is_signed_in(), default="5")) as context:
        response = put_limit(context, {"agent_limit": None})

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), has_entries(agent_limit=None, agent_limit_in_force=5))


def test_lowering_the_limit_keeps_the_agents_already_running():
    with given(_setup()) as context:
        hire(context, "First")
        hire(context, "Second")
        the_organization_may_run(1)(context)

        with when("the owner tries to hire another"):
            response = hire(context, "Third")

        with then("it is refused, and both Agents are still there"):
            assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
            agents = context.client.get(AGENTS, headers=auth(context)).json()
            assert_that(agents["total"], equal_to(2))


@pytest.mark.parametrize("payload", [{"agent_limit": -1}, {"agent_limit": 1.5}, {}])
def test_an_invalid_limit_is_refused(payload):
    with given(_setup(a_platform_administrator_is_signed_in())) as context:
        response = put_limit(context, payload)

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))


def test_only_a_platform_administrator_sets_it():
    with given(_setup()) as context:
        response = put_limit(context, {"agent_limit": 10})

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

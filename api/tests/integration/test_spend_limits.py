"""Self-service spend limits (AF-337).

The contract under test:

- a platform administrator sets an Organization's ceiling; the Organization may set
  its own limit only at or below it, and lowering the ceiling pulls it down;
- an Organization sets a limit per Agent and a default for Agents without one, never
  above its own limit;
- only people holding `llm_budget.manage` (Owners and Admins) change any of this;
- every change reaches the proxy and leaves an audit Event behind.
"""

from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi import status
from hamcrest import assert_that, equal_to, has_entries, has_item, is_not

from api.domains.agents.repository import AgentRepository
from api.domains.events.models import OutboxMessage
from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import AGENT_OWNER_ROLE_ID, AGENT_VIEWER_ROLE_ID, OrganizationRole
from api.infrastructure.litellm.client import LiteLLMClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    FAKE_LITELLM_KEY,
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_agent_access,
    there_is_an_agent,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

# conftest: ORGANIZATION_DEFAULT_LLM_BUDGET_USD=100, AGENT_DEFAULT_LLM_BUDGET_USD=25.
CEILING = 100.0
AGENT_DEFAULT = 25.0

_ENV = set_env_variable(
    {
        "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
        "LITELLM_BASE_URL": "http://litellm:4000",
        "LITELLM_SECRET_NAME": "litellm",
    }
)
_BASE = [
    _ENV,
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
]

ORG_BUDGET = "/api/v1/organizations/{organization_id}/llm-budget"
PLATFORM_BUDGET = "/api/v1/platform/organizations/{organization_id}/llm-budget"
AGENT_BUDGET = "/api/v1/organizations/{organization_id}/agents/{agent_id}/llm-budget"
SETTINGS = "/api/v1/organizations/{organization_id}/agent-settings"


def as_role(role: OrganizationRole) -> list:
    """An Organization has exactly one Owner, so the Owner exists first and founds it;
    anyone else joins an existing one with `role`."""
    email = f"{role.value.lower()}@example.com"
    if role is OrganizationRole.OWNER:
        return [*_BASE, there_is_a_user(email=email), there_is_an_organization()]
    return [*_BASE, there_is_an_organization(), there_is_a_user(email=email, role=role)]


def signed_in(role: OrganizationRole = OrganizationRole.OWNER) -> list:
    return [*as_role(role), there_is_an_access_token_for_user()]


def platform_admin() -> list:
    return [
        *_BASE,
        there_is_a_user(email="platform@example.com", is_platform_admin=True),
        there_is_an_access_token_for_user(),
        there_is_an_organization(),
    ]


def auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def proxy(context) -> Any:
    return context.injector.get(LiteLLMClient)


def stored_organization(context):
    return context.injector.get(OrganizationRepository).get(context.organization.id)


def stored_agent(context, agent_id=None):
    return context.injector.get(AgentRepository).get_by_id(agent_id or context.agent.id)


def events_named(context, name: str) -> list[OutboxMessage]:
    messages = context.injector.get(PostgresRepositoryDelegate).find_all(OutboxMessage)
    return [message for message in messages if message.event_name == name]


def put_own(context, amount):
    return context.client.put(
        ORG_BUDGET.format(organization_id=context.organization.id), json={"budget_usd": amount}, headers=auth(context)
    )


def put_agent(context, amount, agent_id=None):
    return context.client.put(
        AGENT_BUDGET.format(organization_id=context.organization.id, agent_id=agent_id or context.agent.id),
        json={"budget_usd": amount},
        headers=auth(context),
    )


def put_default(context, amount):
    return context.client.put(
        SETTINGS.format(organization_id=context.organization.id),
        json={"default_agent_llm_budget_usd": amount},
        headers=auth(context),
    )


# --- a new Organization starts capped -------------------------------------------


def test_a_new_organization_starts_at_the_deployment_default():
    with given([*_BASE, there_is_a_user(email="founder@example.com"), there_is_an_access_token_for_user()]) as context:
        with when("someone creates an Organization"):
            response = context.client.post(
                "/api/v1/organizations", json={"name": "Fresh Organization"}, headers=auth(context)
            )

        with then("it is capped at the default, on the row and on its team"):
            assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
            organization_id = response.json()["id"]
            stored = context.injector.get(OrganizationRepository).get(organization_id)
            assert_that((stored.llm_budget_usd, stored.llm_budget_duration), equal_to((CEILING, "30d")))
            proxy(context).apply_team_budget.assert_called_once_with(organization_id, CEILING, "30d")


# --- the Organization's own limit ------------------------------------------------


@pytest.mark.parametrize("role", [OrganizationRole.OWNER, OrganizationRole.ADMIN])
def test_an_owner_or_admin_sets_the_organizations_own_limit(role):
    with given(signed_in(role)) as context:
        with when("they set a limit below the ceiling"):
            response = put_own(context, 40)

        with then("it is the limit in force, on the row and on the team"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                response.json(),
                has_entries(limit_usd=40.0, ceiling_usd=CEILING, own_limit_usd=40.0, window="30d", can_manage=True),
            )
            assert_that(stored_organization(context).llm_own_budget_usd, equal_to(40.0))
            proxy(context).apply_team_budget.assert_called_with(str(context.organization.id), 40.0, "30d")


def test_a_limit_above_the_ceiling_is_refused_not_clamped():
    with given(signed_in()) as context:
        with when("the Organization asks for more than the platform allows"):
            response = put_own(context, CEILING + 1)

        with then("it is refused and nothing changes"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(stored_organization(context).llm_own_budget_usd, equal_to(None))
            proxy(context).apply_team_budget.assert_not_called()


def test_clearing_the_own_limit_falls_back_to_the_ceiling():
    with given(signed_in()) as context:
        put_own(context, 40)

        with when("the Organization clears its own limit"):
            response = put_own(context, None)

        with then("the ceiling is back in force"):
            assert_that(response.json(), has_entries(limit_usd=CEILING, own_limit_usd=None))
            proxy(context).apply_team_budget.assert_called_with(str(context.organization.id), CEILING, "30d")


def test_a_plain_member_cannot_set_the_organizations_limit():
    with given(signed_in(OrganizationRole.MEMBER)) as context:
        response = put_own(context, 10)
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_an_organization_that_sets_nothing_reads_the_ceiling():
    with given(signed_in()) as context:
        response = context.client.get(ORG_BUDGET.format(organization_id=context.organization.id), headers=auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), has_entries(limit_usd=CEILING, ceiling_usd=CEILING, own_limit_usd=None))


def test_changing_the_own_limit_is_audited():
    with given(signed_in()) as context:
        put_own(context, 40)
        (event,) = events_named(context, "organization.llm_budget.changed")
        assert_that(
            event.payload,
            has_entries(ceiling_usd=CEILING, own_limit_usd=40.0, previous_own_limit_usd=None, reason=None),
        )


# --- the platform ceiling --------------------------------------------------------


def test_lowering_the_ceiling_below_the_own_limit_pulls_it_down():
    with given(platform_admin()) as context:
        repository = context.injector.get(OrganizationRepository)
        organization = repository.get(context.organization.id)
        organization.llm_own_budget_usd = 80.0
        repository.save(organization)

        with when("a platform administrator lowers the ceiling beneath it"):
            response = context.client.put(
                PLATFORM_BUDGET.format(organization_id=context.organization.id),
                json={"budget_usd": 50},
                headers=auth(context),
            )

        with then("the Organization is never bound by more than the platform allows"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json(), has_entries(llm_budget_usd=50.0, llm_own_budget_usd=50.0))
            proxy(context).apply_team_budget.assert_called_with(str(context.organization.id), 50.0, "30d")

        with then("the audit trail says why the Organization's own limit moved"):
            (event,) = events_named(context, "organization.llm_budget.changed")
            assert_that(event.payload, has_entries(own_limit_usd=50.0, previous_own_limit_usd=80.0))
            assert_that(event.payload["reason"], is_not(None))


@pytest.mark.parametrize(
    "payload",
    [{"budget_usd": None}, {}, {"budget_usd": -1}, {"budget_usd": 10, "budget_duration": "14d"}],
)
def test_the_ceiling_can_no_longer_be_cleared_or_given_a_drifting_window(payload):
    with given(platform_admin()) as context:
        response = context.client.put(
            PLATFORM_BUDGET.format(organization_id=context.organization.id), json=payload, headers=auth(context)
        )
        assert_that(response.status_code, equal_to(422))


# --- a limit per Agent -----------------------------------------------------------


def test_an_owner_sets_an_agents_limit_and_it_reaches_its_key():
    with given([*signed_in(), there_is_an_agent()]) as context:
        with when("the Owner gives the Agent a limit of its own"):
            response = put_agent(context, 20)

        with then("it is stored and written onto the Agent's key"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json(), has_entries(own_limit_usd=20.0, limit_usd=20.0, source="agent"))
            assert_that(stored_agent(context).llm_budget_usd, equal_to(20.0))
            proxy(context).apply_key_budget.assert_called_with(FAKE_LITELLM_KEY, 20.0, "30d")


def test_an_agent_without_a_limit_follows_the_default():
    with given([*signed_in(), there_is_an_agent()]) as context:
        response = context.client.get(
            AGENT_BUDGET.format(organization_id=context.organization.id, agent_id=context.agent.id),
            headers=auth(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            response.json(),
            has_entries(own_limit_usd=None, limit_usd=AGENT_DEFAULT, source="default", can_manage=True),
        )


def test_an_agents_limit_above_the_organizations_is_refused():
    with given([*signed_in(), there_is_an_agent()]) as context:
        put_own(context, 30)
        response = put_agent(context, 31)
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(stored_agent(context).llm_budget_usd, equal_to(None))


def test_agent_limits_may_add_up_to_more_than_the_organizations():
    with given([*signed_in(), there_is_an_agent(name="First"), there_is_an_agent(name="Second")]) as context:
        agents = context.injector.get(AgentRepository).find_all_with_litellm_keys()
        put_own(context, 30)
        responses = [put_agent(context, 30, agent.id) for agent in agents]
        assert_that([response.status_code for response in responses], equal_to([200, 200]))


def test_an_agents_own_owner_cannot_set_its_limit():
    """Admin only for now: the Organization divides its allowance, not each Agent's Owner."""
    with given(
        [
            *signed_in(OrganizationRole.MEMBER),
            there_is_an_agent(),
            there_is_agent_access(access_role_id=AGENT_OWNER_ROLE_ID),
        ]
    ) as context:
        response = put_agent(context, 5)
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_an_agent_viewer_sees_the_limit_but_cannot_change_it():
    with given(
        [
            *signed_in(OrganizationRole.MEMBER),
            there_is_an_agent(),
            there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID),
        ]
    ) as context:
        response = context.client.get(
            AGENT_BUDGET.format(organization_id=context.organization.id, agent_id=context.agent.id),
            headers=auth(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), has_entries(limit_usd=AGENT_DEFAULT, can_manage=False))


def test_a_member_without_access_cannot_even_see_the_agent():
    with given([*signed_in(OrganizationRole.MEMBER), there_is_an_agent()]) as context:
        response = context.client.get(
            AGENT_BUDGET.format(organization_id=context.organization.id, agent_id=context.agent.id),
            headers=auth(context),
        )
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_changing_an_agents_limit_is_audited():
    with given([*signed_in(), there_is_an_agent()]) as context:
        put_agent(context, 20)
        (event,) = events_named(context, "agent.llm_budget.changed")
        assert_that(event.payload, has_entries(limit_usd=20.0, previous_limit_usd=None, reason=None))


def test_lowering_the_organizations_limit_pulls_agent_limits_down():
    with given([*signed_in(), there_is_an_agent()]) as context:
        put_agent(context, 60)

        with when("the Organization lowers its own limit beneath the Agent's"):
            put_own(context, 40)

        with then("the Agent's limit follows it down, on the row and on the key"):
            assert_that(stored_agent(context).llm_budget_usd, equal_to(40.0))
            proxy(context).apply_key_budget.assert_called_with(FAKE_LITELLM_KEY, 40.0, "30d")

        with then("the audit trail says why"):
            clamped = [e for e in events_named(context, "agent.llm_budget.changed") if e.payload["reason"]]
            assert_that([e.payload["limit_usd"] for e in clamped], equal_to([40.0]))


# --- the default for Agents without a limit of their own -----------------------


def test_changing_the_default_moves_every_inheriting_agent_and_no_other():
    with given([*signed_in(), there_is_an_agent(name="Inherits"), there_is_an_agent(name="Pinned")]) as context:
        pinned = context.agent
        put_agent(context, 15, pinned.id)
        litellm: MagicMock = proxy(context)
        litellm.apply_key_budget.reset_mock()

        with when("the Organization changes its default Agent limit"):
            response = put_default(context, 10)

        with then("the setting reports its reach"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                response.json(),
                has_entries(
                    default_agent_llm_budget_usd=10.0,
                    effective_default_agent_llm_budget_usd=10.0,
                    budget_inheriting_agent_count=1,
                    budget_override_agent_count=1,
                ),
            )

        with then("only the inheriting Agent's key changed"):
            assert_that([c.args[1] for c in litellm.apply_key_budget.call_args_list], equal_to([10.0]))


def test_a_default_above_the_organizations_limit_is_refused():
    with given(signed_in()) as context:
        put_own(context, 30)
        response = put_default(context, 31)
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_changing_the_default_is_audited():
    with given(signed_in()) as context:
        put_default(context, 10)
        events = events_named(context, "organization.agent_settings.changed")
        assert_that(
            [e.payload for e in events],
            has_item(has_entries(setting="default_agent_llm_budget_usd", previous=None, current=10.0)),
        )


# --- every Agent's limit, in one place ---------------------------------------------

AGENT_BUDGETS = "/api/v1/organizations/{organization_id}/agents/llm-budgets"


def list_agent_budgets(context):
    return context.client.get(AGENT_BUDGETS.format(organization_id=context.organization.id), headers=auth(context))


def test_an_owner_sees_every_agents_limit_and_where_it_comes_from():
    with given([*signed_in(), there_is_an_agent(name="Inherits"), there_is_an_agent(name="Pinned")]) as context:
        put_agent(context, 15, context.agent.id)

        with when("the Owner lists the Agents' spend limits"):
            response = list_agent_budgets(context)

        with then("each Agent carries its limit in force and whether it is its own"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            rows = {row["agent_name"]: row for row in response.json()}
            assert_that(rows["Inherits"], has_entries(limit_usd=AGENT_DEFAULT, own_limit_usd=None, source="default"))
            assert_that(rows["Pinned"], has_entries(limit_usd=15.0, own_limit_usd=15.0, source="agent"))


def test_deleted_agents_are_not_listed():
    with given([*signed_in(), there_is_an_agent(name="Live"), there_is_an_agent(name="Gone", deleted=True)]) as context:
        names = [row["agent_name"] for row in list_agent_budgets(context).json()]
        assert_that(names, equal_to(["Live"]))


def test_a_plain_member_cannot_list_agent_limits():
    """The same audience as the Organization's spend figures."""
    with given([*signed_in(OrganizationRole.MEMBER), there_is_an_agent()]) as context:
        assert_that(list_agent_budgets(context).status_code, equal_to(status.HTTP_403_FORBIDDEN))


# --- the renewal date shows straight away ------------------------------------------

RENEWS = "2026-10-01T00:00:00Z"


def test_setting_a_limit_records_when_it_renews_for_the_organization_and_its_agents():
    with given([*signed_in(), there_is_an_agent()]) as context:
        proxy(context).apply_team_budget.return_value = RENEWS

        with when("the Organization sets its own limit"):
            put_own(context, 40)

        with then("its renewal date is known without waiting for the scheduled refresh"):
            org = context.client.get(ORG_BUDGET.format(organization_id=context.organization.id), headers=auth(context))
            assert_that(org.json()["renews_at"], equal_to("2026-10-01T00:00:00Z"))

        with then("its Agents renew with it"):
            agent = context.client.get(
                AGENT_BUDGET.format(organization_id=context.organization.id, agent_id=context.agent.id),
                headers=auth(context),
            )
            assert_that(agent.json()["renews_at"], equal_to("2026-10-01T00:00:00Z"))

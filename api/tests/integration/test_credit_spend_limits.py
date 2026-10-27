"""Spend limits on an Organization that runs on credit (AF-381).

An Organization on credit has a one-off limit: everything it has been granted, never
renewed. Any limit beneath that would be a lifetime cap a top-up could never lift, so
on credit the balance is the only limit:

- the Organization's own limit, a per-Agent limit and the default Agent limit are
  refused;
- one left over from before the Organization ran on credit is ignored and not shown.
"""

from fastapi import status
from hamcrest import assert_that, equal_to, has_entries

from api.domains.agents.repository import AgentRepository
from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import OrganizationRole
from api.infrastructure.litellm.client import ONE_OFF_BUDGET_WINDOW
from api.tests.core.givenpy import given, then, when
from api.tests.integration.test_spend_limits import (
    AGENT_BUDGET,
    ORG_BUDGET,
    auth,
    proxy,
    put_agent,
    put_default,
    put_own,
    signed_in,
    stored_agent,
    stored_organization,
)
from api.tests.steps.agent import there_is_an_agent

CREDIT = 10.0


def the_organization_runs_on_credit(own_limit_usd: float | None = None):
    def step(context):
        organizations = context.injector.get(OrganizationRepository)
        organization = organizations.get(context.organization.id)
        organization.llm_budget_usd = CREDIT
        organization.llm_budget_duration = ONE_OFF_BUDGET_WINDOW
        organization.llm_own_budget_usd = own_limit_usd
        organizations.save(organization)

    return step


def the_agent_has_its_own_limit(amount: float):
    def step(context):
        agents = context.injector.get(AgentRepository)
        agent = agents.get_by_id(context.agent.id)
        agent.llm_budget_usd = amount
        agents.save(agent)

    return step


def on_credit(*steps) -> list:
    return [*signed_in(OrganizationRole.OWNER), the_organization_runs_on_credit(), *steps]


def test_an_organization_on_credit_cannot_set_its_own_limit():
    with given(on_credit()) as context:
        with when("the Owner asks for a limit below the balance"):
            response = put_own(context, 4)

        with then("it is refused and nothing reaches the proxy"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(stored_organization(context).llm_own_budget_usd, equal_to(None))
            proxy(context).apply_team_budget.assert_not_called()


def test_an_agent_on_credit_cannot_be_given_its_own_limit():
    with given(on_credit(there_is_an_agent())) as context:
        with when("the Owner asks for a limit on one Agent"):
            response = put_agent(context, 4)

        with then("it is refused and nothing reaches the key"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(stored_agent(context).llm_budget_usd, equal_to(None))
            proxy(context).apply_key_budget.assert_not_called()


def test_an_organization_on_credit_cannot_set_a_default_agent_limit():
    with given(on_credit()) as context:
        response = put_default(context, 4)
        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_an_own_limit_left_from_before_credit_is_ignored_and_not_shown():
    with given([*signed_in(OrganizationRole.OWNER), the_organization_runs_on_credit(own_limit_usd=4.0)]) as context:
        response = context.client.get(ORG_BUDGET.format(organization_id=context.organization.id), headers=auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            response.json(),
            has_entries(limit_usd=CREDIT, ceiling_usd=CREDIT, own_limit_usd=None, window=ONE_OFF_BUDGET_WINDOW),
        )


def test_an_agent_limit_left_from_before_credit_is_ignored_and_not_shown():
    with given(on_credit(there_is_an_agent(), the_agent_has_its_own_limit(3.0))) as context:
        response = context.client.get(
            AGENT_BUDGET.format(organization_id=context.organization.id, agent_id=context.agent.id),
            headers=auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(response.json(), has_entries(own_limit_usd=None, limit_usd=CREDIT, source="organization"))


def test_the_reconciler_holds_an_organization_on_credit_to_its_balance():
    with given([*signed_in(OrganizationRole.OWNER), the_organization_runs_on_credit(own_limit_usd=4.0)]) as context:
        policies = context.injector.get(OrganizationRepository).list_budget_policies()

        assert_that(policies, equal_to([(context.organization.id, CREDIT, ONE_OFF_BUDGET_WINDOW)]))

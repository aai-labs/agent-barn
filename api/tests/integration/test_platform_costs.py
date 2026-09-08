"""Integration tests for the Platform cost surface (AF-281).

These endpoints are cross-Organization by design: a Platform Administrator reads
them without an Active Organization, so the assertions here seed more than one
Organization and expect both to be counted.
"""

from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, close_to, equal_to, has_length, none, not_none

from api.domains.costs.models import CostRecordSource
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
from api.tests.steps.cost import cost_records_are_clean, there_are_cost_records
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_BASE = "/api/v1/platform/costs"

_BASE_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            # Left empty so the credit poll short-circuits instead of reaching
            # OpenRouter from a test.
            "OPENROUTER_API_KEY": "",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    cost_records_are_clean(),
]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _platform_admin(email: str):
    """A Platform Administrator whose token lands last in context.access_token.

    `there_is_a_user` attaches the new user to `context.organization` as OWNER when
    one is present, which would give this user exactly the Membership these
    endpoints must not need. Hiding the Organization keeps the admin
    membership-free, which is the whole point of Platform View.
    """
    admin_id = uuid7()

    def step(context):
        original_organization = getattr(context, "organization", None)
        context.organization = None
        there_is_a_user(id=admin_id, email=email, is_platform_admin=True)(context)
        context.organization = original_organization
        there_is_an_access_token_for_user(user_id=admin_id)(context)

    return [step]


def _second_organization(email: str, agent_name: str):
    """Another Organization with its own Agent and its own spend.

    Kept as a separate step list so the surrounding scenario ends up back on the
    first Organization, which is what `there_are_cost_records` defaults to.
    """

    def step(context):
        first_organization = context.organization
        first_agent = context.agent
        # Cleared first: `there_is_a_user` attaches a new OWNER to whatever
        # context.organization holds, which would collide with the first org's owner.
        context.organization = None
        there_is_an_organization_with_user_and_access_token(email=email)(context)
        there_is_a_template()(context)
        there_is_an_agent(name=agent_name)(context)
        context.second_organization = context.organization
        context.second_agent = context.agent
        context.organization = first_organization
        context.agent = first_agent

    return step


# --- authorization -------------------------------------------------------


def test_platform_costs_reject_a_regular_user():
    with given(
        [*_BASE_GIVEN, there_is_an_organization_with_user_and_access_token(email="plain@example.com")]
    ) as context:
        with when("a user without Platform Privilege asks for platform costs"):
            summary = context.client.get(f"{_BASE}/summary", headers=_auth(context.access_token))
            rows = context.client.get(_BASE, headers=_auth(context.access_token))
            orgs = context.client.get(f"{_BASE}/organizations", headers=_auth(context.access_token))

        with then("every route on the surface is refused"):
            assert_that(summary.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(rows.status_code, equal_to(status.HTTP_403_FORBIDDEN))
            assert_that(orgs.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_platform_costs_require_authentication():
    with given(_BASE_GIVEN) as context:
        response = context.client.get(f"{_BASE}/summary")
        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


# --- cross-organization reads --------------------------------------------


def test_summary_counts_every_organization():
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-a@example.com"),
            there_is_a_template(),
            there_is_an_agent(name="Agent A"),
            _second_organization("owner-b@example.com", "Agent B"),
            there_are_cost_records(count=2, spend="1.00"),
            *_platform_admin("admin-total@example.com"),
        ]
    ) as context:
        with when("the platform admin asks for the summary"):
            response = context.client.get(f"{_BASE}/summary", headers=_auth(context.access_token))

        with then("spend from every organization is included"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["total_spend"], equal_to(2.0))
            assert_that(body["total_calls"], equal_to(2))


def test_the_organization_filter_narrows_every_figure():
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-c@example.com"),
            there_is_a_template(),
            there_is_an_agent(name="Agent C"),
            _second_organization("owner-d@example.com", "Agent D"),
            there_are_cost_records(count=1, spend="3.00"),
            *_platform_admin("admin-filter@example.com"),
        ]
    ) as context:
        second = context.second_organization
        second_spend = there_are_cost_records(
            count=4,
            spend="5.00",
            agent_id=context.second_agent.id,
            agent_name=context.second_agent.name,
            organization_id=second.id,
            organization_name=second.name,
        )
        second_spend(context)

        with when("the admin filters to the second organization"):
            scoped = f"{_BASE}/summary?organization_id={second.id}"
            summary = context.client.get(scoped, headers=_auth(context.access_token))
            rows = context.client.get(f"{_BASE}?organization_id={second.id}", headers=_auth(context.access_token))
            unscoped = context.client.get(f"{_BASE}/summary", headers=_auth(context.access_token))

        with then("only that organization's spend is counted"):
            assert_that(summary.json()["total_spend"], equal_to(20.0))
            assert_that(rows.json()["total"], equal_to(4))
            assert_that(unscoped.json()["total_spend"], equal_to(23.0))


def test_the_organization_filter_scopes_the_agent_options():
    """Picking an organization must narrow the agent filter, not sit beside it."""
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-e@example.com"),
            there_is_a_template(),
            there_is_an_agent(name="Agent E"),
            _second_organization("owner-f@example.com", "Agent F"),
            there_are_cost_records(count=1, spend="1.00"),
            *_platform_admin("admin-scope@example.com"),
        ]
    ) as context:
        second = context.second_organization
        there_are_cost_records(
            count=1,
            spend="1.00",
            agent_id=context.second_agent.id,
            agent_name=context.second_agent.name,
            organization_id=second.id,
            organization_name=second.name,
        )(context)

        with when("the admin opens the agent filter with and without an organization"):
            everyone = context.client.get(f"{_BASE}/filters/agents", headers=_auth(context.access_token))
            scoped = context.client.get(
                f"{_BASE}/filters/agents?organization_id={second.id}",
                headers=_auth(context.access_token),
            )

        with then("the scoped list holds only that organization's agent"):
            assert_that(everyone.json(), has_length(2))
            assert_that(scoped.json(), has_length(1))
            assert_that(scoped.json()[0]["value"], equal_to(str(context.second_agent.id)))


def test_agent_options_are_labelled_with_their_organization():
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-g@example.com"),
            there_is_a_template(),
            there_is_an_agent(name="Agent G"),
            there_are_cost_records(count=1, spend="1.00"),
            *_platform_admin("admin-label@example.com"),
        ]
    ) as context:
        with when("the admin opens the agent filter"):
            response = context.client.get(f"{_BASE}/filters/agents", headers=_auth(context.access_token))

        with then("each agent is disambiguated by its organization"):
            label = response.json()[0]["label"]
            assert_that(label, equal_to(f"Agent G in {context.organization.name}"))


def test_organizations_are_ranked_by_spend():
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-h@example.com"),
            there_is_a_template(),
            there_is_an_agent(name="Agent H"),
            _second_organization("owner-i@example.com", "Agent I"),
            there_are_cost_records(count=1, spend="1.00"),
            *_platform_admin("admin-rank@example.com"),
        ]
    ) as context:
        second = context.second_organization
        there_are_cost_records(
            count=1,
            spend="9.00",
            agent_id=context.second_agent.id,
            agent_name=context.second_agent.name,
            organization_id=second.id,
            organization_name=second.name,
        )(context)

        with when("the admin asks for organizations by spend"):
            response = context.client.get(f"{_BASE}/organizations", headers=_auth(context.access_token))

        with then("the biggest spender is first"):
            body = response.json()
            assert_that(body, has_length(2))
            assert_that(body[0]["organization_id"], equal_to(str(second.id)))
            assert_that(body[0]["spend"], equal_to(9.0))


def test_unattributed_spend_is_reported_separately_but_still_counted():
    """Spend that resolved to no agent is the honest gap in attribution.

    It stays inside the total — hiding it would make the platform total disagree
    with the sum of the organizations listed beneath it — but it is also called out,
    because a growing number here means attribution has drifted, not that someone is
    spending more.
    """
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-j@example.com"),
            there_is_a_template(),
            there_is_an_agent(name="Agent J"),
            there_are_cost_records(count=1, spend="4.00"),
            *_platform_admin("admin-unattributed@example.com"),
        ]
    ) as context:
        there_are_cost_records(count=2, spend="1.50", unattributed=True)(context)

        with when("the admin asks for the summary"):
            response = context.client.get(f"{_BASE}/summary", headers=_auth(context.access_token))

        with then("the gap is visible and included"):
            body = response.json()
            assert_that(body["unattributed_spend"], equal_to(3.0))
            assert_that(body["unattributed_calls"], equal_to(2))
            assert_that(body["total_spend"], equal_to(7.0))


def test_burn_rate_is_spend_per_day_and_runway_is_unknown_without_credits():
    """Runway must be null rather than a number when credit is unknown.

    OpenRouter reports null for a key with no credit limit, and a failed poll looks
    the same. Inventing a figure on a page about money is worse than admitting the
    gap.
    """
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-k@example.com"),
            there_is_a_template(),
            there_is_an_agent(name="Agent K"),
            there_are_cost_records(count=3, spend="10.00"),
            *_platform_admin("admin-burn@example.com"),
        ]
    ) as context:
        with when("the admin asks for a 30-day summary"):
            response = context.client.get(f"{_BASE}/summary?period=THIRTY_DAYS", headers=_auth(context.access_token))

        with then("burn rate is spend over the window and runway is unknown"):
            body = response.json()
            assert_that(body["total_spend"], equal_to(30.0))
            assert_that(body["daily_burn_rate"], close_to(1.0, 0.01))
            assert_that(body["credits_remaining"], none())
            assert_that(body["runway_days"], none())


def test_platform_rows_carry_the_organization_the_org_surface_must_not_expose():
    with given(
        [
            *_BASE_GIVEN,
            there_is_an_organization_with_user_and_access_token(email="owner-l@example.com"),
            there_is_a_template(),
            there_is_an_agent(name="Agent L"),
            there_are_cost_records(count=1, spend="2.00", source=CostRecordSource.OPENROUTER_BACKFILL),
            *_platform_admin("admin-rows@example.com"),
        ]
    ) as context:
        with when("the admin lists the rows"):
            response = context.client.get(_BASE, headers=_auth(context.access_token))

        with then("the row names its organization and flags the recovered cost"):
            row = response.json()["items"][0]
            assert_that(row["organization_name"], equal_to(context.organization.name))
            assert_that(row["organization_id"], not_none())
            assert_that(row["healed"], equal_to(True))

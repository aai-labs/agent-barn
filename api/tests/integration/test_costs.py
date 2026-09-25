from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid7

from fastapi import status
from hamcrest import (
    assert_that,
    close_to,
    contains_exactly,
    equal_to,
    greater_than,
    has_entries,
    has_length,
    none,
    not_none,
)
from sqlalchemy import text
from starlette.testclient import TestClient

from api.domains.costs.models import CostRecordSource, resolve_monthly_window
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID, PermissionKey
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.litellm.client import LiteLLMClient
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    FAKE_LITELLM_KEY,
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_agent_access,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.cost import cost_records_are_clean, there_are_cost_records
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.rbac import role_lacks_permission
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_BASE = "/api/v1/organizations/{organization_id}/costs"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
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
    there_is_an_agent(),
    cost_records_are_clean(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _there_is_a_member_actor(member_id):
    """Attach a plain MEMBER to the org set up in _GIVEN and switch the token to them."""

    def step(context):
        there_is_a_user(
            id=member_id,
            email="member-costs@example.com",
            role=OrganizationRole.MEMBER,
        )(context)
        there_is_an_access_token_for_user(user_id=member_id)(context)

    return step


def test_admin_with_assigned_cost_scope_cannot_view_organization_summary():
    admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=admin_id,
                email="admin-assigned-costs@example.com",
                role=OrganizationRole.ADMIN,
            ),
            there_is_an_access_token_for_user(user_id=admin_id),
            role_lacks_permission(
                OrganizationRole.ADMIN,
                PermissionKey.COST_READ,
            ),
        ]
    ) as context:
        response = context.client.get(f"{_BASE}/summary", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_without_cost_read_cannot_view_organization_summary():
    admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=admin_id,
                email="admin-no-costs@example.com",
                role=OrganizationRole.ADMIN,
            ),
            there_is_an_access_token_for_user(user_id=admin_id),
            role_lacks_permission(OrganizationRole.ADMIN, PermissionKey.COST_READ),
        ]
    ) as context:
        response = context.client.get(f"{_BASE}/summary", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_admin_with_organization_cost_scope_can_view_summary():
    admin_id = uuid7()
    with given(
        [
            *_GIVEN,
            there_is_a_user(
                id=admin_id,
                email="admin-costs@example.com",
                role=OrganizationRole.ADMIN,
            ),
            there_is_an_access_token_for_user(user_id=admin_id),
        ]
    ) as context:
        response = context.client.get(f"{_BASE}/summary", headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_member_cannot_view_costs_summary():
    """Org spend is sensitive: only owners/admins (and platform_admins) may view it."""
    member_id = uuid7()
    with given([*_GIVEN, _there_is_a_member_actor(member_id)]) as context:
        response = context.client.get(f"{_BASE}/summary", headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_unassigned_member_cannot_view_agent_cost():
    member_id = uuid7()
    with given([*_GIVEN, _there_is_a_member_actor(member_id)]) as context:
        agent_id = str(context.agent.id)
        response = context.client.get(f"{_BASE}/agents/{agent_id}", headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_platform_admin_without_membership_cannot_view_costs_summary():
    """Platform Administrators need real membership for org-scoped costs."""
    super_id = uuid7()
    org_id = uuid7()
    with given(
        [
            set_env_variable(
                {
                    "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                    "LITELLM_BASE_URL": "http://litellm:4000",
                    "LITELLM_SECRET_NAME": "litellm",
                    "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
                    "SKIP_SLACK_TOKEN_VALIDATION": "true",
                }
            ),
            prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
            prepare_api_server(),
            create_test_client(),
            database_repo_is_ready(),
            database_is_clean(),
            # Created before the org exists in context, so the platform admin stays a non-member.
            there_is_a_user(id=super_id, email="super-costs@example.com", is_platform_admin=True),
            there_is_an_organization_with_user_and_access_token(id=org_id, email="owner-super-costs@example.com"),
            use_org_for_auth(),
            there_is_an_access_token_for_user(user_id=super_id),
        ]
    ) as context:
        response = context.client.get(f"{_BASE}/summary", headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_get_costs_summary_returns_200_and_data():
    """The summary reads cost_record, not LiteLLM.

    The old version mocked the proxy's aggregate endpoint. Reading our own table is
    the whole point of the change: a proxy outage now shows as stale data rather than
    a confident $0.00.
    """
    with given([*_GIVEN, there_are_cost_records(count=3, spend="2.50")]) as context:
        client: TestClient = context.client

        with when("I request the costs summary"):
            response = client.get(f"{_BASE}/summary", headers=_auth(context))

        with then("it returns 200 with totals aggregated from the stored rows"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            data = response.json()
            assert_that(data["total_spend"], equal_to(7.5))
            assert_that(data["total_calls"], equal_to(3))
            assert_that(data["active_agents"], equal_to(1))
            assert_that(data["top_model"], equal_to("openrouter/z-ai/glm-5.2"))
            assert_that(data["avg_cost_per_call"], equal_to(2.5))


def test_costs_summary_and_rows_agree_under_the_same_filter():
    """A stat card and the table beneath it must never count different things."""
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=2, spend="1.00", model="openrouter/z-ai/glm-5.2"),
            there_are_cost_records(count=3, spend="4.00", model="openrouter/anthropic/claude-opus-5"),
        ]
    ) as context:
        client: TestClient = context.client
        query = "?model=openrouter/anthropic/claude-opus-5"

        with when("I filter both the summary and the rows by one model"):
            summary = client.get(f"{_BASE}/summary{query}", headers=_auth(context))
            rows = client.get(f"{_BASE}{query}", headers=_auth(context))

        with then("both describe the same three calls"):
            assert_that(summary.json()["total_calls"], equal_to(3))
            assert_that(summary.json()["total_spend"], equal_to(12.0))
            assert_that(rows.json()["total"], equal_to(3))
            assert_that(rows.json()["items"], has_length(3))


def test_costs_rows_are_paginated_without_repeating_a_row():
    with given([*_GIVEN, there_are_cost_records(count=5, spend="1.00")]) as context:
        client: TestClient = context.client

        with when("I page through the rows two at a time"):
            first = client.get(f"{_BASE}?page=1&page_size=2", headers=_auth(context))
            second = client.get(f"{_BASE}?page=2&page_size=2", headers=_auth(context))

        with then("the pages are disjoint and the total is stable"):
            assert_that(first.json()["total"], equal_to(5))
            first_ids = {row["request_id"] for row in first.json()["items"]}
            second_ids = {row["request_id"] for row in second.json()["items"]}
            assert_that(first_ids & second_ids, equal_to(set()))


def test_healed_rows_are_flagged_so_a_rising_total_is_explainable():
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=1, spend="3.00", source=CostRecordSource.OPENROUTER_BACKFILL),
            there_are_cost_records(count=1, spend="1.00"),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I list the rows"):
            response = client.get(f"{_BASE}", headers=_auth(context))

        with then("exactly the recovered row is marked healed"):
            healed = [row for row in response.json()["items"] if row["healed"]]
            assert_that(healed, has_length(1))
            assert_that(healed[0]["spend"], equal_to(3.0))


def test_filter_options_come_from_spend_that_actually_happened():
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=1, spend="1.00", model="openrouter/z-ai/glm-5.2"),
            there_are_cost_records(count=1, spend="9.00", model="openrouter/anthropic/claude-opus-5"),
        ]
    ) as context:
        client: TestClient = context.client

        with when("I request the model and agent filter options"):
            models = client.get(f"{_BASE}/filters/models", headers=_auth(context))
            agents = client.get(f"{_BASE}/filters/agents", headers=_auth(context))

        with then("models are ranked by spend and the agent is offered by name"):
            assert_that([option["value"] for option in models.json()], has_length(2))
            assert_that(models.json()[0]["value"], equal_to("openrouter/anthropic/claude-opus-5"))
            assert_that(agents.json(), has_length(1))
            assert_that(agents.json()[0]["value"], equal_to(str(context.agent.id)))


def test_get_agent_cost_returns_200_and_data():
    with given([*_GIVEN, there_are_cost_records(count=2, spend="2.50")]) as context:
        client: TestClient = context.client
        agent_id = str(context.agent.id)

        with when("I request the individual agent cost"):
            response = client.get(f"{_BASE}/agents/{agent_id}", headers=_auth(context))

        with then("it returns 200 with the agent's cost over the window"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            data = response.json()
            assert_that(data["total_cost"], equal_to(5.0))
            assert_that(data["agent_id"], equal_to(agent_id))
            assert_that(data["prompt_tokens"], equal_to(200))
            assert_that(data["models_breakdown"], has_length(1))


def test_agent_spend_list_ranks_agents_by_spend():
    with given([*_GIVEN, there_are_cost_records(count=2, spend="1.25")]) as context:
        client: TestClient = context.client

        with when("I list agent spend for the organization"):
            response = client.get(f"{_BASE}/agents", headers=_auth(context))

        with then("it returns one row per agent with its totals"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            rows = response.json()
            assert_that(rows, has_length(1))
            assert_that(rows[0]["agent_id"], equal_to(str(context.agent.id)))
            assert_that(rows[0]["spend"], close_to(2.5, 0.0001))
            assert_that(rows[0]["calls"], equal_to(2))
            assert_that(rows[0]["prompt_tokens"], greater_than(0))


def test_member_cannot_list_agent_spend():
    """The ranked table is Organization-wide, so it takes the Organization `cost.read`
    the summary takes rather than a per-Agent check."""
    member_id = uuid7()
    with given([*_GIVEN, _there_is_a_member_actor(member_id)]) as context:
        response = context.client.get(f"{_BASE}/agents", headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_agent_cost_includes_a_spend_trend_for_the_agent():
    """The per-Agent surface carries its own trend.

    The organization summary also has one, but it is gated on the Organization-wide
    `cost.read` an Agent Access Role never grants, so a per-Agent view cannot source
    its chart from there.
    """
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=1, spend="3.00", minutes_ago=5),
            there_are_cost_records(count=1, spend="1.00", minutes_ago=60 * 24 * 3),
        ]
    ) as context:
        client: TestClient = context.client
        agent_id = str(context.agent.id)

        with when("I request the individual agent cost"):
            response = client.get(f"{_BASE}/agents/{agent_id}", headers=_auth(context))

        with then("it returns a bucketed series and the window it was grouped at"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            data = response.json()
            assert_that(data["granularity"], not_none())
            assert_that(data["from_date"], not_none())
            assert_that(data["to_date"], not_none())
            series = data["spend_over_time"]
            assert_that(len(series), greater_than(0))
            assert_that(sum(point["spend"] for point in series), close_to(4.0, 0.0001))
            assert_that(sum(point["calls"] for point in series), equal_to(2))


def test_agent_cost_respects_the_requested_window():
    """The old implementation read /key/info, which is lifetime spend and ignored the
    date range entirely — so this endpoint answered a different question from the one
    it was asked."""
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=1, spend="4.00", minutes_ago=5),
            there_are_cost_records(count=1, spend="99.00", minutes_ago=60 * 24 * 200),
        ]
    ) as context:
        client: TestClient = context.client
        agent_id = str(context.agent.id)

        with when("I ask for a narrow window and then a wide one"):
            narrow = client.get(f"{_BASE}/agents/{agent_id}?period=SEVEN_DAYS", headers=_auth(context))
            # params=, not an f-string: the "+" in an ISO offset decodes as a space.
            wide = client.get(
                f"{_BASE}/agents/{agent_id}",
                params={"from_date": (datetime.now(UTC) - timedelta(days=365)).isoformat()},
                headers=_auth(context),
            )

        with then("the window changes the answer in both directions"):
            assert_that(narrow.json()["total_cost"], equal_to(4.0))
            assert_that(wide.json()["total_cost"], equal_to(103.0))


def test_deleted_agent_cost_attribution_remains_available_after_key_is_blocked():
    with given([*_GIVEN, there_are_cost_records(count=1, spend="5.00")]) as context:
        client: TestClient = context.client
        litellm: MagicMock = context.injector.get(LiteLLMClient)
        agent_id = str(context.agent.id)

        with when("I delete the Agent and request its historical cost"):
            delete_response = client.delete(
                f"/api/v1/organizations/{context.organization.id}/agents/{agent_id}",
                headers=_auth(context),
            )
            response = client.get(f"{_BASE}/agents/{agent_id}", headers=_auth(context))

        with then("the deleted Agent's spend remains attributable"):
            assert_that(delete_response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["status"], equal_to("deleted"))
            assert_that(response.json()["total_cost"], equal_to(5.0))
            litellm.block_key.assert_called_once_with(FAKE_LITELLM_KEY)
            litellm.delete_key.assert_not_called()


def test_cost_history_survives_a_hard_deleted_agent():
    """Cost rows carry no foreign key to the agent on purpose.

    The names captured at write time are the only remaining record of who spent the
    money once the agent row is gone.
    """
    with given([*_GIVEN, there_are_cost_records(count=1, spend="6.00")]) as context:
        client: TestClient = context.client
        delegate = context.injector.get(PostgresRepositoryDelegate)

        with when("the agent row is removed outright"):
            with delegate.engine.begin() as connection:
                connection.execute(text("DELETE FROM agent WHERE id = :id"), {"id": context.agent.id})
            response = client.get(f"{_BASE}", headers=_auth(context))

        with then("the spend and the captured agent name are still there"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            items = response.json()["items"]
            assert_that(items, has_length(1))
            assert_that(items[0]["spend"], equal_to(6.0))
            assert_that(items[0]["agent_name"], equal_to(context.agent.name))


def test_an_org_caller_cannot_widen_scope_with_an_organization_id_param():
    """The org surface pins the organization itself.

    `get_cost_filter` does not accept organization_id at all, and the service
    overwrites it regardless — two layers, because this is the one parameter that
    would turn an org-scoped page into a platform-wide one.
    """
    with given([*_GIVEN, there_are_cost_records(count=1, spend="2.00")]) as context:
        client: TestClient = context.client
        someone_else = uuid7()

        with when("I pass another organization's id"):
            response = client.get(f"{_BASE}?organization_id={someone_else}", headers=_auth(context))
            summary = client.get(f"{_BASE}/summary?organization_id={someone_else}", headers=_auth(context))

        with then("the parameter is ignored and my own organization is returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["total"], equal_to(1))
            assert_that(summary.json()["total_spend"], equal_to(2.0))


def test_get_costs_summary_requires_auth():
    with given(_GIVEN) as context:
        client: TestClient = context.client

        with when("I request costs summary without auth"):
            response = client.get(f"{_BASE}/summary")

        with then("it returns 401 Unauthorized"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_get_agent_cost_requires_auth():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        agent_id = str(context.agent.id)

        with when("I request agent cost without auth"):
            response = client.get(f"{_BASE}/agents/{agent_id}")

        with then("it returns 401 Unauthorized"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_get_agent_cost_not_found_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        fake_id = "11111111-1111-1111-1111-111111111111"

        with when("I request an agent that does not exist"):
            response = client.get(f"{_BASE}/agents/{fake_id}", headers=_auth(context))

        with then("it returns 404 Not Found"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --- The Agent's own cost page ------------------------------------------------


def _a_second_agent_with_spend(spend: str):
    """Another Agent in the same Organization, with calls of its own.

    Leaves ``context.agent`` on the first Agent, so the scenario still reads the
    Agent it set up and the second one is only there to be excluded.
    """

    def step(context):
        first_agent = context.agent
        there_is_an_agent(name="Other Agent")(context)
        context.other_agent = context.agent
        there_are_cost_records(count=1, spend=spend)(context)
        context.agent = first_agent

    return step


def _there_is_an_agent_viewer(member_id):
    """A plain Member who holds only Agent Viewer on the scenario's Agent."""

    def step(context):
        _there_is_a_member_actor(member_id)(context)
        there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID)(context)

    return step


def test_agent_cost_reports_calls_failures_and_averages():
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=3, spend="2.00", prompt_tokens=400),
            there_are_cost_records(count=1, spend="0", status="failure", prompt_tokens=0, completion_tokens=0),
            there_are_cost_records(count=1, spend="4.00", source=CostRecordSource.OPENROUTER_BACKFILL),
        ]
    ) as context:
        agent_id = str(context.agent.id)

        with when("I request the individual agent cost"):
            response = context.client.get(f"{_BASE}/agents/{agent_id}", headers=_auth(context))

        with then("it counts every call and separates failed and recovered ones"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                response.json(),
                has_entries(
                    total_calls=5,
                    failed_calls=1,
                    healed_calls=1,
                    avg_cost_per_call=close_to(2.0, 0.0001),
                    avg_duration_ms=close_to(1234, 0.01),
                    first_call_at=not_none(),
                    last_call_at=not_none(),
                ),
            )

        with then("the per-model breakdown carries its call count"):
            assert_that(response.json()["models_breakdown"][0]["calls"], equal_to(5))

        with then("the page's charts come with it"):
            assert_that(response.json()["avg_prompt_tokens_over_time"], not_none())
            histogram = response.json()["cost_per_call_histogram"]
            assert_that(sum(band["calls"] for band in histogram), equal_to(5))


def test_agent_cost_narrows_by_model():
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=2, spend="1.00", model="openrouter/z-ai/glm-5.2"),
            there_are_cost_records(count=1, spend="5.00", model="openrouter/anthropic/claude-opus-5"),
        ]
    ) as context:
        agent_id = str(context.agent.id)

        with when("I filter the agent's cost to one model"):
            response = context.client.get(
                f"{_BASE}/agents/{agent_id}",
                params={"model": "openrouter/anthropic/claude-opus-5"},
                headers=_auth(context),
            )

        with then("only that model's calls are counted"):
            assert_that(response.json(), has_entries(total_cost=5.0, total_calls=1))


def test_agent_calls_list_only_that_agents_calls():
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=3, spend="1.00"),
            _a_second_agent_with_spend("7.00"),
        ]
    ) as context:
        agent_id = str(context.agent.id)

        with when("I list the agent's calls"):
            response = context.client.get(f"{_BASE}/agents/{agent_id}/calls", headers=_auth(context))

        with then("the other agent's call is not among them"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["total"], equal_to(3))
            assert_that({row["agent_id"] for row in response.json()["items"]}, equal_to({agent_id}))


def test_agent_calls_ignore_an_agent_id_param():
    """The Agent is pinned from the path; the query string cannot re-point the read."""
    with given([*_GIVEN, there_are_cost_records(count=1, spend="1.00"), _a_second_agent_with_spend("7.00")]) as context:
        agent_id = str(context.agent.id)

        with when("I pass another agent's id alongside the path"):
            response = context.client.get(
                f"{_BASE}/agents/{agent_id}/calls",
                params={"agent_id": str(context.other_agent.id)},
                headers=_auth(context),
            )

        with then("the path's agent is still the one read"):
            assert_that(response.json()["total"], equal_to(1))
            assert_that(response.json()["items"][0]["agent_id"], equal_to(agent_id))


def test_agent_summary_and_calls_agree_under_the_same_filter():
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=2, spend="1.00", model="openrouter/z-ai/glm-5.2"),
            there_are_cost_records(count=3, spend="4.00", model="openrouter/anthropic/claude-opus-5"),
        ]
    ) as context:
        agent_id = str(context.agent.id)
        params = {"model": "openrouter/z-ai/glm-5.2"}

        with when("I filter both the agent's summary and its calls by one model"):
            summary = context.client.get(f"{_BASE}/agents/{agent_id}", params=params, headers=_auth(context))
            calls = context.client.get(f"{_BASE}/agents/{agent_id}/calls", params=params, headers=_auth(context))

        with then("both describe the same two calls"):
            assert_that(summary.json()["total_calls"], equal_to(2))
            assert_that(calls.json()["total"], equal_to(2))


def test_agent_model_options_list_only_that_agents_models():
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=1, spend="1.00", model="openrouter/z-ai/glm-5.2"),
            _a_second_agent_with_spend("7.00"),
        ]
    ) as context:
        agent_id = str(context.agent.id)

        with when("I request the agent's model options"):
            response = context.client.get(f"{_BASE}/agents/{agent_id}/filters/models", headers=_auth(context))

        with then("only the models this agent used are offered"):
            assert_that([option["value"] for option in response.json()], equal_to(["openrouter/z-ai/glm-5.2"]))


def test_agent_viewer_can_read_the_agents_calls_and_months():
    """Agent Viewer grants the Agent's costs, not the Organization's."""
    member_id = uuid7()
    with given(
        [*_GIVEN, there_are_cost_records(count=2, spend="1.00"), _there_is_an_agent_viewer(member_id)]
    ) as context:
        agent_id = str(context.agent.id)

        with when("the viewer reads the agent's calls, months and the organization's months"):
            calls = context.client.get(f"{_BASE}/agents/{agent_id}/calls", headers=_auth(context))
            monthly = context.client.get(f"{_BASE}/agents/{agent_id}/monthly", headers=_auth(context))
            options = context.client.get(f"{_BASE}/agents/{agent_id}/filters/models", headers=_auth(context))
            org_monthly = context.client.get(f"{_BASE}/monthly", headers=_auth(context))

        with then("the agent's reads succeed and the organization's is refused"):
            assert_that(calls.status_code, equal_to(status.HTTP_200_OK))
            assert_that(calls.json()["total"], equal_to(2))
            assert_that(monthly.status_code, equal_to(status.HTTP_200_OK))
            assert_that(options.status_code, equal_to(status.HTTP_200_OK))
            assert_that(org_monthly.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_unassigned_member_cannot_read_the_agents_calls_or_months():
    member_id = uuid7()
    with given([*_GIVEN, _there_is_a_member_actor(member_id)]) as context:
        agent_id = str(context.agent.id)

        for path in ("calls", "monthly", "filters/models"):
            response = context.client.get(f"{_BASE}/agents/{agent_id}/{path}", headers=_auth(context))
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND), path)


# --- Monthly aggregates -------------------------------------------------------


def _month_start(months_back: int) -> datetime:
    return resolve_monthly_window(months_back + 1).start


def test_monthly_costs_group_by_calendar_month_and_fill_quiet_months():
    this_month = _month_start(0)
    two_months_ago = _month_start(2)
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=2, spend="3.00", occurred_at=this_month + timedelta(minutes=1)),
            there_are_cost_records(count=1, spend="5.00", occurred_at=two_months_ago + timedelta(days=3)),
        ]
    ) as context:
        with when("I request three months of the organization's spend"):
            response = context.client.get(f"{_BASE}/monthly", params={"months": 3}, headers=_auth(context))

        with then("every month is present, oldest first, the quiet one at zero"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            months = response.json()
            assert_that([month["spend"] for month in months], contains_exactly(5.0, 0.0, 6.0))
            assert_that([month["calls"] for month in months], contains_exactly(1, 0, 2))
            assert_that(months[0]["month"], equal_to(two_months_ago.isoformat().replace("+00:00", "Z")))

        with then("only the month in progress is marked current and projected"):
            assert_that(months[0], has_entries(is_current=False, projected_spend=none()))
            assert_that(months[2], has_entries(is_current=True, projected_spend=greater_than(0)))


def test_monthly_costs_are_not_cut_by_the_date_range():
    """The table compares whole months, so a date range picked for the charts must
    not reach it — a range mid-month would otherwise report a partial month."""
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=1, spend="2.00", occurred_at=_month_start(1) + timedelta(days=1)),
        ]
    ) as context:
        with when("I pass a seven-day period alongside the months"):
            response = context.client.get(
                f"{_BASE}/monthly", params={"months": 2, "period": "SEVEN_DAYS"}, headers=_auth(context)
            )

        with then("last month's spend is still counted"):
            assert_that(response.json()[0]["spend"], equal_to(2.0))


def test_monthly_costs_respect_the_agent_filter():
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=1, spend="1.00", occurred_at=_month_start(0) + timedelta(minutes=1)),
            _a_second_agent_with_spend("7.00"),
        ]
    ) as context:
        with when("I filter the organization's months to one agent"):
            response = context.client.get(
                f"{_BASE}/monthly",
                params={"months": 1, "agent_id": str(context.agent.id)},
                headers=_auth(context),
            )

        with then("only that agent's spend is counted"):
            assert_that(response.json()[0], has_entries(spend=1.0, active_agents=1))


def test_agent_monthly_costs_count_only_that_agent():
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=2, spend="1.50", occurred_at=_month_start(0) + timedelta(minutes=1)),
            _a_second_agent_with_spend("7.00"),
        ]
    ) as context:
        agent_id = str(context.agent.id)

        with when("I request the agent's months"):
            response = context.client.get(
                f"{_BASE}/agents/{agent_id}/monthly", params={"months": 1}, headers=_auth(context)
            )

        with then("the other agent's spend is left out"):
            assert_that(response.json(), has_length(1))
            assert_that(response.json()[0], has_entries(spend=3.0, calls=2))


def test_monthly_costs_bound_the_number_of_months():
    with given(_GIVEN) as context:
        for months in (0, 25):
            response = context.client.get(f"{_BASE}/monthly", params={"months": months}, headers=_auth(context))
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY), str(months))


def test_member_cannot_view_monthly_costs():
    member_id = uuid7()
    with given([*_GIVEN, _there_is_a_member_actor(member_id)]) as context:
        response = context.client.get(f"{_BASE}/monthly", headers=_auth(context))
        assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))

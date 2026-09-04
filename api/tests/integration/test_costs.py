from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, equal_to, has_length
from sqlalchemy import text
from starlette.testclient import TestClient

from api.domains.costs.models import CostRecordSource
from api.domains.rbac.catalog import PermissionKey
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

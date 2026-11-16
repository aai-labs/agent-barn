"""Reading an Agent's Anomalies and its learned normal (AF-453).

Only Organization Owners and Admins may read either. A Member who owns the Agent can
see the Agent but not this; a Member without access cannot see the Agent at all.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import status
from hamcrest import (
    assert_that,
    contains_exactly,
    equal_to,
    has_entries,
    has_item,
    has_length,
)
from sqlmodel import Session

from api.domains.anomalies.models import (
    AgentActivitySeen,
    AgentAnomaly,
    AnomalySignal,
    OrganizationAnomalySettings,
    SeenKind,
)
from api.domains.costs.models import CostSyncState
from api.domains.rbac.catalog import AGENT_OWNER_ROLE_ID, OrganizationRole
from api.domains.tool_calls.models import ToolCall, ToolCallStatus
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_agent_access,
    there_is_an_agent,
)
from api.tests.steps.cost import cost_records_are_clean
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_BASE = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    cost_records_are_clean(),
]

ANOMALIES = "/api/v1/organizations/{organization_id}/agents/{agent_id}/anomalies"
NORMAL = "/api/v1/organizations/{organization_id}/agents/{agent_id}/normal-behaviour"


def signed_in(role: OrganizationRole = OrganizationRole.OWNER) -> list:
    email = f"{role.value.lower()}@example.com"
    if role is OrganizationRole.OWNER:
        people = [there_is_a_user(email=email), there_is_an_organization()]
    else:
        people = [there_is_an_organization(), there_is_a_user(email=email, role=role)]
    return [*_BASE, *people, there_is_an_access_token_for_user()]


def auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _save(context, *rows) -> None:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        for row in rows:
            session.add(row)
            session.flush()
        session.commit()


def get(context, path: str, **params):
    return context.client.get(
        path.format(organization_id=context.organization.id, agent_id=context.agent.id),
        params=params,
        headers=auth(context),
    )


def there_are_anomalies(count: int):
    def step(context):
        start = datetime(2026, 11, 1, tzinfo=UTC)
        _save(
            context,
            *[
                AgentAnomaly(
                    organization_id=context.organization.id,
                    agent_id=context.agent.id,
                    signal=AnomalySignal.NEW_DESTINATION.value,
                    subject=f"host-{index}.example.com",
                    observed_value=1,
                    started_at=start + timedelta(hours=index),
                    last_observed_at=start + timedelta(hours=index),
                    ended_at=start + timedelta(hours=index),
                )
                for index in range(count)
            ],
        )

    return step


def test_an_owner_lists_an_agents_anomalies_newest_first():
    with given([*signed_in(), there_is_an_agent(), there_are_anomalies(3)]) as context:
        response = get(context, ANOMALIES)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            [item["subject"] for item in response.json()["items"]],
            equal_to(["host-2.example.com", "host-1.example.com", "host-0.example.com"]),
        )


def test_anomalies_come_a_page_at_a_time():
    with given([*signed_in(), there_is_an_agent(), there_are_anomalies(3)]) as context:
        response = get(context, ANOMALIES, page=2, page_size=2)

        assert_that(response.json(), has_entries(total=3, items=has_length(1)))


def test_an_anomaly_carries_what_was_seen_and_what_is_usual():
    with given([*signed_in(), there_is_an_agent(), there_are_anomalies(1)]) as context:
        (item,) = get(context, ANOMALIES).json()["items"]

        assert_that(
            item,
            has_entries(
                signal="NEW_DESTINATION",
                subject="host-0.example.com",
                observed_value=1.0,
                usual_value=None,
                classification_state="STATISTICS_ONLY",
            ),
        )


def test_an_admin_lists_anomalies():
    with given([*signed_in(OrganizationRole.ADMIN), there_is_an_agent(), there_are_anomalies(1)]) as context:
        assert_that(get(context, ANOMALIES).status_code, equal_to(status.HTTP_200_OK))


def test_a_member_who_owns_the_agent_cannot_read_its_anomalies():
    with given(
        [
            *signed_in(OrganizationRole.MEMBER),
            there_is_an_agent(),
            there_is_agent_access(access_role_id=AGENT_OWNER_ROLE_ID),
        ]
    ) as context:
        assert_that(get(context, ANOMALIES).status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_member_without_access_cannot_even_see_the_agent():
    with given([*signed_in(OrganizationRole.MEMBER), there_is_an_agent()]) as context:
        assert_that(get(context, ANOMALIES).status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_a_member_who_owns_the_agent_cannot_read_its_normal():
    with given(
        [
            *signed_in(OrganizationRole.MEMBER),
            there_is_an_agent(),
            there_is_agent_access(access_role_id=AGENT_OWNER_ROLE_ID),
        ]
    ) as context:
        assert_that(get(context, NORMAL).status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_a_new_agent_has_no_normal_yet():
    with given([*signed_in(), there_is_an_agent()]) as context:
        response = get(context, NORMAL)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            response.json(),
            has_entries(
                detection_enabled=False,
                enough_history=False,
                active_days=0,
                rates=[],
                override=has_entries(sensitivity="NORMAL", max_llm_tokens_per_hour=None),
                can_manage=True,
            ),
        )


def usual_tool_activity():
    """Ten tool calls in one hour on each of four recent days."""

    def step(context):
        now = datetime.now(UTC)
        rows = []
        for day in (2, 3, 4, 5):
            hour = (now - timedelta(days=day)).replace(minute=0, second=0, microsecond=0)
            for minute in range(10):
                row = ToolCall(
                    organization_id=context.organization.id,
                    agent_id=context.agent.id,
                    session_id="s",
                    external_id=f"tc-{uuid4().hex}",
                    tool_name="web_fetch",
                    arguments={},
                    status=ToolCallStatus.SUCCESS,
                    occurred_at=hour + timedelta(minutes=minute),
                )
                row.created_at = row.occurred_at
                rows.append(row)
        _save(context, *rows)
        with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
            session.merge(CostSyncState(source="litellm", completed_at=now))
            session.commit()

    return step


def test_the_learned_rates_show_the_usual_value_and_what_would_be_flagged():
    with given([*signed_in(), there_is_an_agent(), usual_tool_activity()]) as context:
        body = get(context, NORMAL).json()

        with then("there is enough history, and tool calls usually run at ten an hour"):
            assert_that(body, has_entries(enough_history=True, active_days=4))
            assert_that(
                body["rates"],
                has_item(has_entries(signal="TOOL_CALLS_PER_HOUR", usual=10.0, threshold=30.0, active_hours=4)),
            )


def test_what_the_agent_used_in_its_baseline_window_is_listed():
    with given([*signed_in(), there_is_an_agent()]) as context:
        now = datetime.now(UTC)
        _save(
            context,
            OrganizationAnomalySettings(organization_id=context.organization.id, enabled=True),
            *[
                AgentActivitySeen(
                    organization_id=context.organization.id,
                    agent_id=context.agent.id,
                    kind=kind.value,
                    subject=subject,
                    first_seen_at=at,
                    last_seen_at=at,
                )
                for kind, subject, at in (
                    (SeenKind.TOOL, "web_fetch", now - timedelta(days=1)),
                    (SeenKind.DESTINATION, "docs.example.com", now - timedelta(days=2)),
                    (SeenKind.DESTINATION, "stale.example.com", now - timedelta(days=30)),
                    (SeenKind.INTEGRATION, "crm", now - timedelta(days=1)),
                    (SeenKind.INTEGRATION_ACTION, "crm read", now - timedelta(days=1)),
                )
            ],
        )

        body = get(context, NORMAL).json()

        assert_that(
            (
                body["detection_enabled"],
                body["tools"],
                body["destinations"],
                body["integrations"],
                body["integration_actions"],
            ),
            contains_exactly(True, ["web_fetch"], ["docs.example.com"], ["crm"], ["crm read"]),
        )

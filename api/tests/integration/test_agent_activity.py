from datetime import UTC, datetime, timedelta
from uuid import uuid7

from fastapi import status
from hamcrest import assert_that, close_to, equal_to, has_length, is_not, none
from starlette.testclient import TestClient

from api.domains.agents.repository import AgentRepository
from api.domains.communications.models import CommunicationConnection
from api.domains.conversations.models import AgentChatMessage, MessageDirection
from api.domains.conversations.repository import ConversationRepository
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID, PERMISSION_ID_BY_KEY, PermissionKey
from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
from api.domains.users.organization_users.models import OrganizationRole
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
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
    there_is_agent_access,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.cost import cost_records_are_clean, there_are_cost_records
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.template import there_is_a_template
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

_BASE = "/api/v1/organizations/{organization_id}/agents"

# Pinned rather than relative to now: the wake grouping is about the distance
# between calls, and a fixed anchor keeps every assertion reproducible.
_ANCHOR = datetime(2026, 9, 15, 12, 30, 0, tzinfo=UTC)

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


def _url(context, suffix: str = "") -> str:
    base = _BASE.format(organization_id=context.organization.id)
    return f"{base}/{context.agent.id}/activity{suffix}"


def _window() -> dict:
    """A range wide enough to hold the anchor, narrow enough to bucket by hour."""
    return {
        "from_date": (_ANCHOR - timedelta(hours=6)).isoformat(),
        "to_date": (_ANCHOR + timedelta(hours=1)).isoformat(),
    }


def _there_is_an_inbound_message(context, *, occurred_at: datetime) -> AgentChatMessage:
    delegate: PostgresRepositoryDelegate = context.injector.get(PostgresRepositoryDelegate)
    if not hasattr(context, "communication_connection"):
        context.communication_connection = CommunicationConnection(
            organization_id=context.agent.organization_id,
            agent_id=context.agent.id,
            platform_key="slack",
            display_name="Test Slack",
            credentials_encrypted="test-credentials",
            driver_key_encrypted="test-driver-key",
        )
        delegate.save(context.communication_connection)
    message = AgentChatMessage(
        agent_id=context.agent.id,
        connection_id=context.communication_connection.id,
        openclaw_msg_id=f"activity-{occurred_at.isoformat()}",
        session_key="agent:main:slack:channel:c1",
        channel_id="C1",
        direction=MessageDirection.INBOUND,
        sender_id="U1",
        content="can you look at this?",
        occurred_at=occurred_at,
    )
    context.injector.get(ConversationRepository).upsert_messages([message])
    return message


# --- authorization ---------------------------------------------------------


def test_activity_without_auth_returns_401():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I read activity without a token"):
            response = client.get(_url(context))
        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def _switch_to_member():
    """Replace the authenticated actor with a plain MEMBER of the same org.

    Organization Owners and Admins hold implicit Agent Owner authority, which
    bypasses the fixed-Role grants entirely — so a permission this endpoint
    requires can only be withheld from someone whose authority comes from an
    Agent Access Role.
    """

    def step(context):
        member_id = uuid7()
        there_is_a_user(
            id=member_id,
            email=f"member-activity-{member_id}@example.com",
            role=OrganizationRole.MEMBER,
            organization_id=context.organization.id,
        )(context)
        there_is_an_access_token_for_user(member_id)(context)

    return step


def _there_is_agent_access_with(context, permissions: set[PermissionKey]) -> None:
    repository: AgentRepository = context.injector.get(AgentRepository)
    role = AgentAccessRole(
        organization_id=context.organization.id,
        name=f"CUSTOM-{uuid7()}",
        is_system=False,
    )
    repository.delegate.save(role)
    for permission in permissions:
        repository.delegate.save(
            AgentAccessRolePermission(role_id=role.id, permission_id=PERMISSION_ID_BY_KEY[permission])
        )
    there_is_agent_access(access_role_id=role.id)(context)


def test_an_agent_viewer_can_read_activity():
    with given([*_GIVEN, _switch_to_member()]) as context:
        there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID)(context)
        client: TestClient = context.client
        with when("an assigned viewer reads the agent's activity"):
            response = client.get(_url(context), params=_window(), headers=_auth(context))
        with then("they are allowed"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))


def test_activity_requires_cost_read():
    with given([*_GIVEN, _switch_to_member()]) as context:
        _there_is_agent_access_with(context, {PermissionKey.AGENT_READ, PermissionKey.ACTIVITY_READ})
        client: TestClient = context.client
        with when("a reader without cost.read asks what the agent has been doing"):
            response = client.get(_url(context), params=_window(), headers=_auth(context))
        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_activity_requires_activity_read():
    with given([*_GIVEN, _switch_to_member()]) as context:
        _there_is_agent_access_with(context, {PermissionKey.AGENT_READ, PermissionKey.COST_READ})
        client: TestClient = context.client
        with when("a reader without activity.read asks what the agent has been doing"):
            response = client.get(_url(context), params=_window(), headers=_auth(context))
        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


def test_unassigned_member_cannot_read_activity():
    with given([*_GIVEN, _switch_to_member()]) as context:
        client: TestClient = context.client
        with when("a member with no Agent Access reads the agent's activity"):
            response = client.get(_url(context), params=_window(), headers=_auth(context))
        with then("the agent is not acknowledged"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --- summary ---------------------------------------------------------------


def test_summary_reports_nothing_for_a_quiet_window():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I read activity for an agent that has made no calls"):
            response = client.get(_url(context), params=_window(), headers=_auth(context))
        with then("every total is zero and both triggers are still described"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["totals"]["calls"], equal_to(0))
            assert_that(body["totals"]["wakes"], equal_to(0))
            assert_that(body["wake_cadence_seconds"], none())
            assert_that(body["last_call_at"], none())
            assert_that([entry["trigger"] for entry in body["by_trigger"]], equal_to(["user", "background"]))


def test_summary_totals_and_prompt_token_spread():
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=3, spend="2.00", prompt_tokens=100_000, occurred_at=_ANCHOR),
            there_are_cost_records(
                count=1, spend="1.00", prompt_tokens=10_000, occurred_at=_ANCHOR - timedelta(hours=2)
            ),
        ]
    ) as context:
        client: TestClient = context.client
        with when("I read the activity summary"):
            response = client.get(_url(context), params=_window(), headers=_auth(context))
        with then("it counts the calls, the money, and how big the prompts were"):
            body = response.json()
            assert_that(body["totals"]["calls"], equal_to(4))
            assert_that(body["totals"]["spend"], close_to(7.0, 0.001))
            assert_that(body["totals"]["prompt_tokens"], equal_to(310_000))
            assert_that(body["prompt_tokens_per_call"]["max"], equal_to(100_000))
            assert_that(body["prompt_tokens_per_call"]["median"], equal_to(100_000))


def test_summary_buckets_calls_over_time():
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=2, occurred_at=_ANCHOR),
            there_are_cost_records(count=1, occurred_at=_ANCHOR - timedelta(hours=3)),
        ]
    ) as context:
        client: TestClient = context.client
        with when("I read the activity summary over an hourly window"):
            response = client.get(_url(context), params=_window(), headers=_auth(context))
        with then("quiet hours are present at zero rather than missing"):
            body = response.json()
            assert_that(body["granularity"], equal_to("hour"))
            counted = [bucket for bucket in body["by_bucket"] if bucket["calls"] > 0]
            assert_that(counted, has_length(2))
            assert_that(sum(bucket["calls"] for bucket in body["by_bucket"]), equal_to(3))
            assert_that(len(body["by_bucket"]), equal_to(8))
        with then("each bucket names the zone it was grouped in"):
            assert_that(body["by_bucket"][0]["bucket"].endswith(("Z", "+00:00")), equal_to(True))


def test_summary_separates_work_nobody_asked_for():
    with given(
        [
            *_GIVEN,
            # Two bursts half an hour apart, neither preceded by a message.
            there_are_cost_records(count=4, spend="1.50", occurred_at=_ANCHOR),
            there_are_cost_records(count=4, spend="1.50", occurred_at=_ANCHOR - timedelta(minutes=30)),
        ]
    ) as context:
        client: TestClient = context.client
        with when("I read the activity summary"):
            response = client.get(_url(context), params=_window(), headers=_auth(context))
        with then("all of it is attributed to background work"):
            body = response.json()
            by_trigger = {entry["trigger"]: entry for entry in body["by_trigger"]}
            assert_that(by_trigger["user"]["calls"], equal_to(0))
            assert_that(by_trigger["user"]["spend"], close_to(0.0, 0.001))
            assert_that(by_trigger["background"]["wakes"], equal_to(2))
            assert_that(by_trigger["background"]["calls"], equal_to(8))
            assert_that(by_trigger["background"]["spend"], close_to(12.0, 0.001))
        with then("the schedule behind it is reported as a cadence"):
            assert_that(body["wake_cadence_seconds"], equal_to(1800))


def test_summary_credits_a_burst_to_the_person_who_started_it():
    with given([*_GIVEN, there_are_cost_records(count=3, spend="0.50", occurred_at=_ANCHOR)]) as context:
        _there_is_an_inbound_message(context, occurred_at=_ANCHOR - timedelta(seconds=30))
        client: TestClient = context.client
        with when("I read the activity summary"):
            response = client.get(_url(context), params=_window(), headers=_auth(context))
        with then("the burst counts as user-triggered"):
            by_trigger = {entry["trigger"]: entry for entry in response.json()["by_trigger"]}
            assert_that(by_trigger["user"]["wakes"], equal_to(1))
            assert_that(by_trigger["user"]["calls"], equal_to(3))
            assert_that(by_trigger["background"]["calls"], equal_to(0))


def test_a_message_long_before_a_burst_does_not_claim_it():
    with given([*_GIVEN, there_are_cost_records(count=2, occurred_at=_ANCHOR)]) as context:
        # Well outside the lead window: the agent woke on its own long afterwards.
        _there_is_an_inbound_message(context, occurred_at=_ANCHOR - timedelta(hours=1))
        client: TestClient = context.client
        with when("I read the activity summary"):
            response = client.get(_url(context), params=_window(), headers=_auth(context))
        with then("the burst is still background work"):
            by_trigger = {entry["trigger"]: entry for entry in response.json()["by_trigger"]}
            assert_that(by_trigger["user"]["calls"], equal_to(0))
            assert_that(by_trigger["background"]["calls"], equal_to(2))


# --- wakes -----------------------------------------------------------------


def test_wakes_group_calls_into_bursts():
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=4, prompt_tokens=117_000, occurred_at=_ANCHOR),
            there_are_cost_records(count=3, prompt_tokens=23_000, occurred_at=_ANCHOR - timedelta(minutes=30)),
        ]
    ) as context:
        client: TestClient = context.client
        with when("I list the agent's wakes"):
            response = client.get(_url(context, "/wakes"), params=_window(), headers=_auth(context))
        with then("each burst is one row, newest first"):
            body = response.json()
            assert_that(body["total"], equal_to(2))
            assert_that(body["items"], has_length(2))
            assert_that(body["items"][0]["calls"], equal_to(4))
            assert_that(body["items"][0]["prompt_tokens"], equal_to(468_000))
            assert_that(body["items"][0]["min_prompt_tokens"], equal_to(117_000))
            assert_that(body["items"][1]["calls"], equal_to(3))
            assert_that(body["items"][0]["trigger"], equal_to("background"))


def test_calls_far_apart_are_never_one_wake():
    with given(
        [
            *_GIVEN,
            # Six minutes apart — past the gap that separates two pieces of work.
            there_are_cost_records(count=2, occurred_at=_ANCHOR, spacing_seconds=360),
        ]
    ) as context:
        client: TestClient = context.client
        with when("I list the agent's wakes"):
            response = client.get(_url(context, "/wakes"), params=_window(), headers=_auth(context))
        with then("they are two"):
            assert_that(response.json()["total"], equal_to(2))


def test_wakes_can_be_narrowed_to_background_work():
    with given([*_GIVEN, there_are_cost_records(count=2, occurred_at=_ANCHOR)]) as context:
        _there_is_an_inbound_message(context, occurred_at=_ANCHOR - timedelta(seconds=30))
        there_are_cost_records(count=2, occurred_at=_ANCHOR - timedelta(minutes=30))(context)
        client: TestClient = context.client
        with when("I list only the wakes nobody asked for"):
            response = client.get(
                _url(context, "/wakes"),
                params={**_window(), "trigger": "background"},
                headers=_auth(context),
            )
        with then("the user-triggered burst is left out"):
            body = response.json()
            assert_that(body["total"], equal_to(1))
            assert_that(body["items"][0]["trigger"], equal_to("background"))


# --- calls -----------------------------------------------------------------


def test_calls_list_the_individual_requests():
    with given([*_GIVEN, there_are_cost_records(count=3, spend="0.25", occurred_at=_ANCHOR)]) as context:
        client: TestClient = context.client
        with when("I drill into the calls"):
            response = client.get(_url(context, "/calls"), params=_window(), headers=_auth(context))
        with then("each billed request is a row"):
            body = response.json()
            assert_that(body["total"], equal_to(3))
            first = body["items"][0]
            assert_that(first["spend"], close_to(0.25, 0.001))
            assert_that(first["request_id"], is_not(none()))
            assert_that(first["request_duration_ms"], equal_to(1234))


def test_calls_narrow_to_the_window_they_are_asked_for():
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=2, occurred_at=_ANCHOR),
            there_are_cost_records(count=5, occurred_at=_ANCHOR - timedelta(hours=3)),
        ]
    ) as context:
        client: TestClient = context.client
        with when("I ask only for the minutes around one burst"):
            response = client.get(
                _url(context, "/calls"),
                params={
                    "from_date": (_ANCHOR - timedelta(minutes=1)).isoformat(),
                    "to_date": (_ANCHOR + timedelta(minutes=1)).isoformat(),
                },
                headers=_auth(context),
            )
        with then("only that burst's calls come back"):
            assert_that(response.json()["total"], equal_to(2))


def test_calls_can_be_narrowed_to_background_work():
    with given([*_GIVEN, there_are_cost_records(count=2, occurred_at=_ANCHOR)]) as context:
        _there_is_an_inbound_message(context, occurred_at=_ANCHOR - timedelta(seconds=30))
        there_are_cost_records(count=3, occurred_at=_ANCHOR - timedelta(minutes=30))(context)
        client: TestClient = context.client
        with when("I list only the calls nobody asked for"):
            response = client.get(
                _url(context, "/calls"),
                params={**_window(), "trigger": "background"},
                headers=_auth(context),
            )
        with then("the calls from the user-triggered burst are left out"):
            assert_that(response.json()["total"], equal_to(3))


def test_another_agents_calls_are_never_counted():
    with given([*_GIVEN, there_are_cost_records(count=2, occurred_at=_ANCHOR)]) as context:
        there_are_cost_records(count=9, agent_id=uuid7(), agent_name="Someone else", occurred_at=_ANCHOR)(context)
        client: TestClient = context.client
        with when("I read the activity summary"):
            response = client.get(_url(context), params=_window(), headers=_auth(context))
        with then("only this agent's calls are counted"):
            assert_that(response.json()["totals"]["calls"], equal_to(2))


def test_last_recorded_call_is_window_scoped_and_utc():
    with given(
        [
            *_GIVEN,
            there_are_cost_records(count=1, occurred_at=_ANCHOR),
            there_are_cost_records(count=1, occurred_at=_ANCHOR + timedelta(days=2)),
        ]
    ) as context:
        response = context.client.get(_url(context), params=_window(), headers=_auth(context))
        assert_that(response.status_code, equal_to(200))
        assert_that(response.json()["last_call_at"], equal_to(_ANCHOR.isoformat().replace("+00:00", "Z")))


def test_runtime_diagnostics_requires_activity_permission():
    with given([*_GIVEN, _switch_to_member()]) as context:
        _there_is_agent_access_with(context, {PermissionKey.AGENT_READ, PermissionKey.COST_READ})
        response = context.client.get(_url(context).removesuffix("activity") + "diagnostics", headers=_auth(context))
        assert_that(response.status_code, equal_to(403))


def test_runtime_diagnostics_does_not_require_cost_permission():
    with given([*_GIVEN, _switch_to_member()]) as context:
        _there_is_agent_access_with(context, {PermissionKey.AGENT_READ, PermissionKey.ACTIVITY_READ})
        response = context.client.get(_url(context).removesuffix("activity") + "diagnostics", headers=_auth(context))
        assert_that(response.status_code, equal_to(200))

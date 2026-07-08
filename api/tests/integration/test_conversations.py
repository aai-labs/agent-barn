"""Integration tests for the per-channel Conversations API."""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import status
from hamcrest import assert_that, equal_to, has_length
from starlette.testclient import TestClient

from api.domains.agents.models import AgentStatus
from api.domains.conversations.models import AgentChatMessage, MessageDirection
from api.domains.conversations.repository import ConversationRepository
from api.domains.conversations.service import ConversationService
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
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)

_BASE = "/api/v1/agents"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _seed_message(
    context,
    *,
    direction,
    channel_id,
    thread_id=None,
    content="msg",
    occurred_at: datetime | None = None,
    channel_name: str | None = None,
):
    repo: ConversationRepository = context.injector.get(ConversationRepository)
    ts = occurred_at or datetime(2025, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    msg = AgentChatMessage(
        agent_id=context.agent.id,
        openclaw_msg_id=f"test-{direction}-{channel_id}-{thread_id}-{content[:8]}-{ts.isoformat()}",
        session_key=f"agent:main:slack:channel:{channel_id.lower()}",
        channel_id=channel_id,
        channel_name=channel_name,
        thread_id=thread_id,
        direction=direction,
        sender_id="U12345" if direction == MessageDirection.INBOUND else None,
        content=content,
        occurred_at=ts,
    )
    repo.upsert_messages([msg])
    return msg


# --- /conversations/channels ---


def test_list_channels_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        with when("I list channels without auth"):
            response = client.get(f"{_BASE}/{context.agent.id}/conversations/channels")
        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_list_channels_unknown_agent_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        fake_id = "00000000-0000-0000-0000-000000000099"
        with when("I list channels for a non-existent agent"):
            response = client.get(
                f"{_BASE}/{fake_id}/conversations/channels", headers=_auth(context)
            )
        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_list_channels_stopped_agent_returns_db_channels():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        client: TestClient = context.client
        _seed_message(
            context,
            direction=MessageDirection.INBOUND,
            channel_id="CAAA",
            content="msg1",
            channel_name="general",
        )
        _seed_message(
            context,
            direction=MessageDirection.OUTBOUND,
            channel_id="CBBB",
            content="msg2",
        )

        with when("I list channels for a stopped agent"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/conversations/channels",
                headers=_auth(context),
            )

        with then("both DB channels appear"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body, has_length(2))
            ids = {c["channel_id"] for c in body}
            assert_that(ids, equal_to({"CAAA", "CBBB"}))
            general = next(c for c in body if c["channel_id"] == "CAAA")
            assert_that(general["channel_name"], equal_to("general"))


def test_list_channels_idle_agent_resolves_null_channel_names_from_directory():
    # A channel the agent only posted to has no persisted name; an idle agent must
    # still resolve it from the Slack directory rather than render the raw C... id.
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        client: TestClient = context.client
        _seed_message(
            context,
            direction=MessageDirection.INBOUND,
            channel_id="CAAA",
            content="msg1",
            channel_name="general",
        )
        _seed_message(
            context,
            direction=MessageDirection.OUTBOUND,
            channel_id="CBBB",
            content="msg2",
        )

        with when("I list channels with the directory resolving CBBB"):
            with patch.object(
                ConversationService,
                "_platform_maps",
                return_value=({}, {"CBBB": "ops-alerts"}),
            ):
                response = client.get(
                    f"{_BASE}/{context.agent.id}/conversations/channels",
                    headers=_auth(context),
                )

        with then("the null-named channel gets its directory name, others untouched"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            by_id = {c["channel_id"]: c["channel_name"] for c in response.json()}
            assert_that(by_id["CBBB"], equal_to("ops-alerts"))
            assert_that(by_id["CAAA"], equal_to("general"))


def test_list_channels_returns_db_channels():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client

        _seed_message(
            context,
            direction=MessageDirection.INBOUND,
            channel_id="CDB1",
            content="db-only-channel",
            channel_name="db-known",
        )

        with when("I list channels"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/conversations/channels",
                headers=_auth(context),
            )

        with then("DB channels are returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            ids = {c["channel_id"] for c in response.json()}
            assert_that(ids, equal_to({"CDB1"}))


# --- /conversations/channels/{channel_id}/messages ---


def test_list_messages_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client
        with when("I list messages without auth"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/conversations/channels/CABC/messages"
            )
        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_list_messages_unknown_agent_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        fake_id = "00000000-0000-0000-0000-000000000099"
        with when("I list messages for a non-existent agent"):
            response = client.get(
                f"{_BASE}/{fake_id}/conversations/channels/CABC/messages",
                headers=_auth(context),
            )
        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_list_messages_returns_latest_page_first_with_default_page_size():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        client: TestClient = context.client
        base = datetime(2025, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(10):
            _seed_message(
                context,
                direction=MessageDirection.INBOUND,
                channel_id="CABC",
                content=f"msg-{i}",
                occurred_at=base + timedelta(minutes=i),
            )

        with when("I list messages with default page_size=6"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/conversations/channels/CABC/messages",
                headers=_auth(context),
            )

        with then("the latest 6 threads are returned oldest-first, has_more=True"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["threads"], has_length(6))
            contents = [t["root"]["content"] for t in body["threads"]]
            # oldest-first within page, last 6 of 10 (msg-4 .. msg-9)
            assert_that(contents, equal_to([f"msg-{i}" for i in range(4, 10)]))
            assert_that(body["has_more"], equal_to(True))
            assert_that(body["next_cursor"] is not None, equal_to(True))


def test_list_messages_cursor_pagination_returns_older_page():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        client: TestClient = context.client
        base = datetime(2025, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(10):
            _seed_message(
                context,
                direction=MessageDirection.INBOUND,
                channel_id="CABC",
                content=f"msg-{i}",
                occurred_at=base + timedelta(minutes=i),
            )

        first = client.get(
            f"{_BASE}/{context.agent.id}/conversations/channels/CABC/messages",
            headers=_auth(context),
        ).json()
        cursor = first["next_cursor"]

        with when("I list messages with the cursor"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/conversations/channels/CABC/messages",
                params={
                    "before_occurred_at": cursor["before_occurred_at"],
                    "before_id": cursor["before_id"],
                },
                headers=_auth(context),
            )

        with then("the older page is returned and has_more=False"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            contents = [t["root"]["content"] for t in body["threads"]]
            assert_that(contents, equal_to([f"msg-{i}" for i in range(0, 4)]))
            assert_that(body["has_more"], equal_to(False))
            assert_that(body["next_cursor"] is None, equal_to(True))


def test_list_messages_date_range_filter():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        client: TestClient = context.client
        base = datetime(2025, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
        for i in range(5):
            _seed_message(
                context,
                direction=MessageDirection.INBOUND,
                channel_id="CABC",
                content=f"m{i}",
                occurred_at=base + timedelta(hours=i),
            )

        with when("I filter by from_date / to_date for the middle hours"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/conversations/channels/CABC/messages",
                params={
                    "from_date": (base + timedelta(hours=1)).isoformat(),
                    "to_date": (base + timedelta(hours=4)).isoformat(),
                },
                headers=_auth(context),
            )

        with then("only the in-range messages are returned"):
            body = response.json()
            contents = [t["root"]["content"] for t in body["threads"]]
            assert_that(contents, equal_to(["m1", "m2", "m3"]))


def test_list_messages_bundles_thread_messages_within_page_window():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        client: TestClient = context.client
        # thread_id must match root's occurred_at unix ts within 5 seconds
        root_ts = 1746100800
        root_dt = datetime.fromtimestamp(root_ts, tz=timezone.utc)
        thread_id = f"{root_ts}.000000"
        _seed_message(
            context,
            direction=MessageDirection.INBOUND,
            channel_id="CABC",
            content="parent",
            occurred_at=root_dt,
        )
        _seed_message(
            context,
            direction=MessageDirection.OUTBOUND,
            channel_id="CABC",
            thread_id=thread_id,
            content="thread-reply",
            occurred_at=root_dt + timedelta(minutes=1),
        )

        with when("I list messages for the channel"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/conversations/channels/CABC/messages",
                headers=_auth(context),
            )

        with then("thread reply is nested under the root in a single thread"):
            body = response.json()
            assert_that(body["threads"], has_length(1))
            thread = body["threads"][0]
            assert_that(thread["root"]["content"], equal_to("parent"))
            assert_that(thread["replies"], has_length(1))
            assert_that(thread["replies"][0]["content"], equal_to("thread-reply"))


def test_list_messages_running_agent_submits_sync_does_not_block():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        _seed_message(
            context,
            direction=MessageDirection.INBOUND,
            channel_id="CABC",
            content="cached",
        )

        with when("I list messages for a running agent"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/conversations/channels/CABC/messages",
                headers=_auth(context),
            )

        with then("the cached message is returned without waiting for sync"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["threads"], has_length(1))
            assert_that(body["threads"][0]["root"]["content"], equal_to("cached"))

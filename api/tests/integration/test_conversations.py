"""Integration tests for GET /agents/{id}/conversations."""

import json
from unittest.mock import MagicMock, patch
from uuid import UUID

from fastapi import status
from hamcrest import assert_that, equal_to, has_length
from starlette.testclient import TestClient

from api.domains.agents.models import AgentStatus
from api.domains.conversations.models import AgentChatMessage, MessageDirection
from api.domains.conversations.repository import ConversationRepository
from api.infrastructure.kubernetes.client import KubernetesClient
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


def _seed_message(context, *, direction, channel_id, thread_id=None, content="msg"):
    repo: ConversationRepository = context.injector.get(ConversationRepository)
    from datetime import datetime, timezone

    msg = AgentChatMessage(
        agent_id=context.agent.id,
        openclaw_msg_id=f"test-{direction}-{channel_id}-{thread_id}-{content[:8]}",
        session_key=f"agent:main:slack:channel:{channel_id.lower()}",
        channel_id=channel_id,
        thread_id=thread_id,
        direction=direction,
        sender_id="U12345" if direction == MessageDirection.INBOUND else None,
        content=content,
        occurred_at=datetime(2025, 5, 1, 12, 0, 0, tzinfo=timezone.utc),
    )
    repo.upsert_messages([msg])
    return msg


def test_get_conversations_no_auth_returns_401():
    with given([*_GIVEN, there_is_an_agent()]) as context:
        client: TestClient = context.client

        with when("I get conversations without auth"):
            response = client.get(f"{_BASE}/{context.agent.id}/conversations")

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_get_conversations_stopped_agent_returns_persisted_messages():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        client: TestClient = context.client
        _seed_message(
            context,
            direction=MessageDirection.INBOUND,
            channel_id="CABC123",
            content="Hello from Slack",
        )

        with when("I get conversations for a stopped agent"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/conversations", headers=_auth(context)
            )

        with then("it returns 200 with the persisted channel and message"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            channels = response.json()["channels"]
            assert_that(channels, has_length(1))
            assert_that(channels[0]["channel_id"], equal_to("CABC123"))
            sessions = channels[0]["sessions"]
            assert_that(sessions, has_length(1))
            messages = sessions[0]["messages"]
            assert_that(messages, has_length(1))
            assert_that(messages[0]["content"], equal_to("Hello from Slack"))
            assert_that(messages[0]["direction"], equal_to("INBOUND"))


def test_get_conversations_groups_by_channel():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        client: TestClient = context.client
        _seed_message(
            context,
            direction=MessageDirection.INBOUND,
            channel_id="CAAA",
            content="ch1",
        )
        _seed_message(
            context,
            direction=MessageDirection.OUTBOUND,
            channel_id="CBBB",
            content="ch2",
        )

        with when("I get conversations with two channels"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/conversations", headers=_auth(context)
            )

        with then("both channels are returned"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            channels = response.json()["channels"]
            channel_ids = {c["channel_id"] for c in channels}
            assert_that(channel_ids, equal_to({"CAAA", "CBBB"}))


def test_get_conversations_thread_has_non_null_thread_id():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        client: TestClient = context.client
        _seed_message(
            context,
            direction=MessageDirection.INBOUND,
            channel_id="CABC123",
            thread_id="1779269814.824809",
            content="Thread message",
        )

        with when("I get conversations with a thread message"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/conversations", headers=_auth(context)
            )

        with then("the session has the thread_id set"):
            sessions = response.json()["channels"][0]["sessions"]
            assert_that(sessions[0]["thread_id"], equal_to("1779269814.824809"))


def test_get_conversations_running_agent_triggers_sync():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)

        sessions_json = json.dumps(
            {
                "agent:main:slack:channel:cabc": {
                    "sessionId": "sess-uuid-001",
                    "origin": {"nativeChannelId": "CABC", "threadId": None},
                }
            }
        )
        inbound_jsonl = json.dumps(
            {
                "id": "live-msg-001",
                "type": "custom_message",
                "customType": "openclaw.runtime-context",
                "content": "[2025-05-01 12:00:00 UTC] Slack message in #general from U999: Live message",
            }
        )

        k8s.get_pod_name_for_deployment.return_value = "agent-pod-xyz"
        k8s.exec_command.side_effect = [sessions_json, inbound_jsonl]

        with when("I get conversations for a running agent"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/conversations", headers=_auth(context)
            )

        with then("it returns 200 and the live message from the pod appears"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            channels = response.json()["channels"]
            assert_that(channels, has_length(1))
            assert_that(channels[0]["channel_id"], equal_to("CABC"))
            messages = channels[0]["sessions"][0]["messages"]
            assert_that(messages, has_length(1))
            assert_that(messages[0]["content"], equal_to("Live message"))


def test_get_conversations_running_agent_sync_failure_still_returns_200():
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        k8s: KubernetesClient = context.injector.get(KubernetesClient)
        k8s.get_pod_name_for_deployment.return_value = "pod-xyz"
        k8s.exec_command.side_effect = RuntimeError("pod exec failed")

        _seed_message(
            context,
            direction=MessageDirection.INBOUND,
            channel_id="CABC123",
            content="Old cached message",
        )

        with when("I get conversations but sync fails"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/conversations", headers=_auth(context)
            )

        with then("it returns 200 with the cached messages from DB"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            channels = response.json()["channels"]
            assert_that(channels, has_length(1))
            assert_that(
                channels[0]["sessions"][0]["messages"][0]["content"],
                equal_to("Old cached message"),
            )


def test_get_conversations_unknown_agent_returns_404():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        fake_id = "00000000-0000-0000-0000-000000000099"

        with when("I get conversations for a non-existent agent"):
            response = client.get(
                f"{_BASE}/{fake_id}/conversations", headers=_auth(context)
            )

        with then("it returns 404"):
            assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

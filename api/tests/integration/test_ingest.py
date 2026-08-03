from datetime import UTC, datetime

from fastapi import status
from hamcrest import assert_that, equal_to, has_length
from starlette.testclient import TestClient

from api.domains.agents.repository import AgentRepository
from api.domains.conversations.models import (
    ConversationsFilter,
)
from api.domains.conversations.repository import ConversationRepository
from api.domains.rbac.policy import AuthorizationScope
from api.domains.tool_calls.repository import ToolCallRepository
from api.infrastructure.crypto import encrypt_token
from api.ingest_app import create_ingest_app
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    prepare_injector,
    set_env_variable,
)
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)

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
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
]


def _create_ingest_client():
    def step(context):
        app = create_ingest_app(injector=context.injector)
        context.ingest_client = TestClient(app)

    return step


def _set_ingest_key(key="test-ingest-key-abc"):
    def step(context):
        repo: AgentRepository = context.injector.get(AgentRepository)
        agent = repo.get_by_id(context.agent.id)
        assert agent is not None
        agent.ingest_key_encrypted = encrypt_token(key, TEST_ENCRYPTION_KEY)
        repo.save(agent)
        context.agent = agent
        context.ingest_key = key

    return step


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.ingest_key}"}


def _url(context) -> str:
    return f"/ingest/v1/agents/{context.agent.id}/events"


def _message_payload(msg_id="msg-1", content="hello"):
    return {
        "messages": [
            {
                "msg_id": msg_id,
                "session_key": "agent:main:slack:dm:U123",
                "channel_id": "D123",
                "direction": "INBOUND",
                "conversation_type": "DM",
                "sender_id": "U123",
                "content": content,
                "occurred_at": datetime.now(UTC).isoformat(),
            }
        ]
    }


def _tool_call_payload(external_id="tc-1"):
    now = datetime.now(UTC).isoformat()
    return {
        "tool_calls": [
            {
                "external_id": external_id,
                "session_id": "session-abc",
                "tool_name": "read",
                "arguments": {"path": "/tmp/x"},
                "occurred_at": now,
            }
        ],
        "tool_results": [
            {
                "external_id": external_id,
                "result": "file contents",
                "is_error": False,
                "completed_at": now,
            }
        ],
    }


# --- auth ---


def test_ingest_no_auth_returns_422():
    with given([*_GIVEN, there_is_an_agent(), _set_ingest_key(), _create_ingest_client()]) as context:
        with when("I post without authorization header"):
            response = context.ingest_client.post(_url(context), json={"messages": []})

        with then("it returns 422"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_ingest_wrong_key_returns_401():
    with given([*_GIVEN, there_is_an_agent(), _set_ingest_key(), _create_ingest_client()]) as context:
        with when("I post with a wrong key"):
            response = context.ingest_client.post(
                _url(context),
                json=_message_payload(),
                headers={"Authorization": "Bearer wrong-key"},
            )

        with then("it returns 401"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


# --- messages ---


def test_ingest_messages_returns_204_and_persists():
    with given([*_GIVEN, there_is_an_agent(), _set_ingest_key(), _create_ingest_client()]) as context:
        with when("I post a message event"):
            response = context.ingest_client.post(
                _url(context),
                json=_message_payload(),
                headers=_auth(context),
            )

        with then("it returns 204 and the message is in the DB"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            conv_repo: ConversationRepository = context.injector.get(ConversationRepository)
            channels = conv_repo.distinct_channels(
                context.agent.id,
                AuthorizationScope(organization_id=context.organization.id),
            )
            assert_that(channels, has_length(1))


def test_ingest_duplicate_messages_are_idempotent():
    with given([*_GIVEN, there_is_an_agent(), _set_ingest_key(), _create_ingest_client()]) as context:
        payload = _message_payload(msg_id="dup-1")

        with when("I post the same message twice"):
            context.ingest_client.post(_url(context), json=payload, headers=_auth(context))
            response = context.ingest_client.post(_url(context), json=payload, headers=_auth(context))

        with then("both return 204 and only one row exists"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            conv_repo: ConversationRepository = context.injector.get(ConversationRepository)
            messages = conv_repo.find_all_channel_messages(
                agent_id=context.agent.id,
                channel_id="D123",
                filter=ConversationsFilter(),
                authorization_scope=AuthorizationScope(organization_id=context.organization.id),
            )
            assert_that(messages, has_length(1))


# --- tool calls ---


def test_ingest_tool_calls_returns_204_and_persists():
    with given([*_GIVEN, there_is_an_agent(), _set_ingest_key(), _create_ingest_client()]) as context:
        with when("I post a tool call + result"):
            response = context.ingest_client.post(
                _url(context),
                json=_tool_call_payload(),
                headers=_auth(context),
            )

        with then("it returns 204 and the tool call is in the DB"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            tc_repo: ToolCallRepository = context.injector.get(ToolCallRepository)
            from api.domains.tool_calls.models import ToolCallFilter
            from api.infrastructure.shared.models import Pagination

            page = tc_repo.find_by_agent(
                context.agent.id,
                ToolCallFilter(),
                Pagination(page=1, size=10),
                AuthorizationScope(organization_id=context.organization.id),
            )
            assert_that(page.total, equal_to(1))
            assert_that(page.items[0].tool_name, equal_to("read"))
            assert_that(page.items[0].status, equal_to("SUCCESS"))


# --- empty batch ---


def test_ingest_empty_batch_returns_204():
    with given([*_GIVEN, there_is_an_agent(), _set_ingest_key(), _create_ingest_client()]) as context:
        with when("I post an empty batch"):
            response = context.ingest_client.post(
                _url(context),
                json={},
                headers=_auth(context),
            )

        with then("it returns 204"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))

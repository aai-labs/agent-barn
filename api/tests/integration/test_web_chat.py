"""Integration tests for the built-in Web Chat channel."""

from fastapi import status
from hamcrest import assert_that, contains_inanyorder, equal_to, has_length
from starlette.testclient import TestClient

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

_BASE = "/api/v1/organizations/{organization_id}/agents"

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
    there_is_an_agent(),
]


def _auth(context) -> dict:
    return {"Authorization": f"Bearer {context.access_token}"}


def _send(context, text: str, thread_id: str | None = None) -> None:
    client: TestClient = context.client
    body = {"text": text} if thread_id is None else {"text": text, "thread_id": thread_id}
    response = client.post(
        f"{_BASE}/{context.agent.id}/web-chat/messages",
        headers=_auth(context),
        json=body,
    )
    assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))


def test_send_then_list_messages_round_trips_on_the_default_thread():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I send a message without specifying a thread"):
            _send(context, "hello there")
        with when("I list messages"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/web-chat/messages",
                headers=_auth(context),
            )
        with then("the message I sent comes back"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            messages = response.json()
            assert_that(messages, has_length(1))
            assert_that(messages[0]["content"], equal_to("hello there"))
            assert_that(messages[0]["direction"], equal_to("INBOUND"))


def test_messages_sent_to_different_threads_stay_isolated():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I send a message on thread a and thread b"):
            _send(context, "message on a", thread_id="thread-a")
            _send(context, "message on b", thread_id="thread-b")
        with when("I list messages scoped to thread a"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/web-chat/messages",
                headers=_auth(context),
                params={"thread_id": "thread-a"},
            )
        with then("only thread a's message is visible"):
            messages = response.json()
            assert_that(messages, has_length(1))
            assert_that(messages[0]["content"], equal_to("message on a"))


def test_list_threads_returns_every_thread_the_user_has_started():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I send messages on two separate threads"):
            _send(context, "first thread", thread_id="thread-a")
            _send(context, "second thread", thread_id="thread-b")
        with when("I list threads"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/web-chat/threads",
                headers=_auth(context),
            )
        with then("both threads are returned with their last message preview"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            threads = response.json()
            assert_that(threads, has_length(2))
            assert_that(
                [t["thread_id"] for t in threads],
                contains_inanyorder("thread-a", "thread-b"),
            )
            previews = {t["thread_id"]: t["last_content"] for t in threads}
            assert_that(previews["thread-a"], equal_to("first thread"))
            assert_that(previews["thread-b"], equal_to("second thread"))


def test_sending_across_multiple_threads_reuses_one_web_connection():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I send messages on two separate threads"):
            _send(context, "first thread", thread_id="thread-a")
            _send(context, "second thread", thread_id="thread-b")
        with when("I list the agent's Communication Connections"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/connections",
                headers=_auth(context),
            )
        with then("exactly one Web Chat connection was auto-provisioned"):
            connections = [c for c in response.json() if c["platform_key"] == "web"]
            assert_that(connections, has_length(1))

"""Integration tests for the built-in Web Chat channel."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from fastapi import status
from hamcrest import assert_that, contains_inanyorder, equal_to, has_length, is_, none, not_
from sqlmodel import Session, select
from starlette.testclient import TestClient

from api.domains.agents.models import AgentStatus
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.models import (
    ApprovalRequest,
    CommunicationConnection,
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    RuntimeReplyCreate,
)
from api.domains.conversations.models import AgentChatMessage, ConversationType, MessageDirection
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.web_chat.models import MAIN_THREAD_ID
from api.domains.web_chat.repository import WebChatRepository
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
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import (
    there_is_an_organization_with_user_and_access_token,
)
from api.tests.steps.user import there_is_a_user, there_is_an_access_token_for_user

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


def _send(context, text: str, thread_id: str | None = None) -> dict[str, object]:
    client: TestClient = context.client
    body = {"text": text} if thread_id is None else {"text": text, "thread_id": thread_id}
    response = client.post(
        f"{_BASE}/{context.agent.id}/web-chat/messages",
        headers=_auth(context),
        json=body,
    )
    assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
    return response.json()


def test_send_then_list_messages_round_trips_on_the_default_thread():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I send a message without specifying a thread"):
            sent_message = _send(context, "hello there")
        with when("I list messages"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/web-chat/messages",
                headers=_auth(context),
            )
        with then("the message I sent comes back"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            messages = response.json()
            assert_that(messages, has_length(1))
            assert_that(messages[0]["id"], equal_to(sent_message["id"]))
            assert_that(messages[0]["content"], equal_to("hello there"))
            assert_that(messages[0]["direction"], equal_to("INBOUND"))
            assert_that(messages[0]["delivery_status"], equal_to("UNAVAILABLE"))


def test_failed_web_chat_message_exposes_the_safe_error_summary():
    error_summary = (
        "The provider reports exhausted credits or billing; add credits to the provider account, then retry (HTTP 402)"
    )
    with given(_GIVEN) as context:
        with when("I record a terminal provider failure for the sent message"):
            sent_message = _send(context, "hello there")
            delegate = context.injector.get(PostgresRepositoryDelegate)
            with Session(delegate.engine) as session:
                delivery = session.exec(
                    select(CommunicationDelivery).where(
                        CommunicationDelivery.message_id == UUID(str(sent_message["id"]))
                    )
                ).one()
                delivery.status = CommunicationDeliveryStatus.DEAD_LETTERED
                delivery.last_error_message = error_summary
                session.add(delivery)
                session.commit()

        with when("I list the Web Chat messages"):
            response = context.client.get(
                f"{_BASE}/{context.agent.id}/web-chat/messages",
                headers=_auth(context),
            )

        with then("the recent failure exposes the safe provider summary"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()[0]["delivery_status"], equal_to("DEAD_LETTERED"))
            assert_that(response.json()[0]["error_message"], equal_to(error_summary))


def test_reading_web_chat_does_not_auto_provision_a_connection():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        messages_response = client.get(
            f"{_BASE}/{context.agent.id}/web-chat/messages",
            headers=_auth(context),
        )
        threads_response = client.get(
            f"{_BASE}/{context.agent.id}/web-chat/threads",
            headers=_auth(context),
        )

        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            web_connection = session.exec(
                select(CommunicationConnection).where(
                    CommunicationConnection.agent_id == context.agent.id,
                    CommunicationConnection.platform_key == "web",
                )
            ).one_or_none()

        assert_that(messages_response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(messages_response.json(), equal_to([]))
        assert_that(threads_response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(threads_response.json(), equal_to([]))
        assert_that(web_connection, none())


def test_thread_mutation_paths_reject_overlong_thread_ids():
    with given(_GIVEN) as context:
        thread_id = "x" * 129
        headers = _auth(context)
        base = f"{_BASE}/{context.agent.id}/web-chat/threads/{thread_id}"

        rename_response = context.client.patch(
            base,
            headers=headers,
            json={"display_name": "Too long"},
        )
        delete_response = context.client.delete(base, headers=headers)
        stop_response = context.client.post(f"{base}/stop", headers=headers)

        assert_that(rename_response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))
        assert_that(delete_response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))
        assert_that(stop_response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_stop_generation_cancels_the_active_thread_delivery_idempotently():
    with given([*_GIVEN[:-1], there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        _send(context, "please stop this", thread_id="thread-a")

        first_stop = client.post(
            f"{_BASE}/{context.agent.id}/web-chat/threads/thread-a/stop",
            headers=_auth(context),
        )
        second_stop = client.post(
            f"{_BASE}/{context.agent.id}/web-chat/threads/thread-a/stop",
            headers=_auth(context),
        )
        messages_response = client.get(
            f"{_BASE}/{context.agent.id}/web-chat/messages",
            headers=_auth(context),
            params={"thread_id": "thread-a"},
        )

        assert_that(first_stop.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that(second_stop.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that(messages_response.json()[0]["delivery_status"], equal_to("CANCELLED"))


def test_processing_stop_exposes_cancel_request_before_runtime_completion():
    with given([*_GIVEN[:-1], there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        sent_message = _send(context, "please stop this while it runs", thread_id="thread-a")
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            delivery = session.exec(
                select(CommunicationDelivery).where(CommunicationDelivery.message_id == UUID(str(sent_message["id"])))
            ).one()
        claimed = context.injector.get(CommunicationDeliveryRepository).claim_next_inbound(agent_id=context.agent.id)

        stop_response = client.post(
            f"{_BASE}/{context.agent.id}/web-chat/threads/thread-a/stop",
            headers=_auth(context),
        )
        messages_response = client.get(
            f"{_BASE}/{context.agent.id}/web-chat/messages",
            headers=_auth(context),
            params={"thread_id": "thread-a"},
        )

        assert_that(claimed.delivery_id if claimed is not None else None, equal_to(delivery.id))
        assert_that(stop_response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        assert_that(messages_response.json()[0]["delivery_status"], equal_to("PROCESSING"))
        assert_that(messages_response.json()[0]["cancel_requested_at"], is_(not_(none())))


def _switch_to_viewer():
    def step(context):
        member_id = uuid7()
        there_is_a_user(
            id=member_id,
            email=f"viewer-{member_id}@example.com",
            role=OrganizationRole.MEMBER,
            organization_id=context.organization.id,
        )(context)
        there_is_an_access_token_for_user(member_id)(context)
        there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID)(context)

    return step


def _agent_replies(context, text: str, approval: ApprovalRequest | None = None) -> None:
    deliveries = context.injector.get(CommunicationDeliveryRepository)
    claimed = deliveries.claim_next_inbound(agent_id=context.agent.id)
    assert_that(claimed, is_(not_(none())))
    deliveries.enqueue_runtime_reply(
        agent_id=context.agent.id,
        source_delivery_id=claimed.delivery_id,
        reply=RuntimeReplyCreate(idempotency_key=f"{claimed.delivery_id}:reply", text=text, approval=approval),
    )


def _list(context) -> list[dict]:
    response = context.client.get(f"{_BASE}/{context.agent.id}/web-chat/messages", headers=_auth(context))
    assert_that(response.status_code, equal_to(status.HTTP_200_OK))
    return response.json()


_APPROVAL = ApprovalRequest(approval_id="run_1:1726051234.5", command="rm -rf build", choices=["once", "deny"])


def test_an_approval_prompt_carries_its_approval_to_the_browser():
    with given([*_GIVEN[:-1], there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _send(context, "clean the build")

        with when("the agent asks to approve a command"):
            _agent_replies(context, "```\nrm -rf build\n```\nReply with one of: once, deny", approval=_APPROVAL)

        with then("the prompt exposes the approval and the question does not"):
            messages = _list(context)
            assert_that(messages[0]["approval"], none())
            assert_that(
                messages[1]["approval"],
                equal_to(
                    {
                        "approval_id": "run_1:1726051234.5",
                        "command": "rm -rf build",
                        "choices": ["once", "deny"],
                        "choice_labels": {
                            "once": "Allow once",
                            "session": "Allow for session",
                            "always": "Always allow",
                            "deny": "Deny",
                        },
                    }
                ),
            )


def test_a_live_stream_refresh_keeps_the_approval():
    with given([*_GIVEN[:-1], there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _send(context, "clean the build")
        _agent_replies(context, "Reply with one of: once, deny", approval=_APPROVAL)
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            prompt = session.exec(
                select(CommunicationDelivery).where(CommunicationDelivery.direction == "OUTBOUND")
            ).one()

        with when("the stream refreshes the prompt's delivery"):
            refreshed = context.injector.get(WebChatRepository).get_message_for_delivery(
                delivery_id=prompt.id,
                connection_id=prompt.connection_id,
                channel_id=str(context.user.id),
                thread_id=MAIN_THREAD_ID,
            )

        with then("the approval survives the refresh"):
            assert_that(refreshed, is_(not_(none())))
            assert_that(refreshed[1].approval, equal_to(_APPROVAL))


def test_an_ordinary_reply_carries_no_approval():
    with given([*_GIVEN[:-1], there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _send(context, "hello")

        with when("the agent replies normally"):
            _agent_replies(context, "hi there")

        with then("no approval is exposed"):
            assert_that([message["approval"] for message in _list(context)], equal_to([None, None]))


def test_an_approval_answer_is_recorded_against_the_approval_it_answers():
    with given([*_GIVEN[:-1], there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        with when("I answer an approval from the browser"):
            response = context.client.post(
                f"{_BASE}/{context.agent.id}/web-chat/messages",
                headers=_auth(context),
                json={"text": "once", "approval_id": "run_1:1726051234.5"},
            )

        with then("the inbound delivery carries the approval id the runtime matches on"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            delegate = context.injector.get(PostgresRepositoryDelegate)
            with Session(delegate.engine) as session:
                delivery = session.exec(
                    select(CommunicationDelivery).where(
                        CommunicationDelivery.message_id == UUID(str(response.json()["id"]))
                    )
                ).one()
            assert_that(delivery.envelope["provider_metadata"], equal_to({"approval_id": "run_1:1726051234.5"}))


def test_an_unreadable_stored_approval_does_not_break_the_thread():
    with given([*_GIVEN[:-1], there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        _send(context, "clean the build")
        _agent_replies(context, "Reply with one of: once, deny", approval=_APPROVAL)
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            prompt = session.exec(
                select(CommunicationDelivery).where(CommunicationDelivery.direction == "OUTBOUND")
            ).one()
            prompt.envelope = {
                **prompt.envelope,
                "approval": {"run_id": "run_1", "command": "rm -rf build", "choices": ["once", "deny"]},
            }
            session.add(prompt)
            session.commit()

        with when("I list the thread"):
            messages = _list(context)

        with then("the prompt still loads, without buttons"):
            assert_that(messages, has_length(2))
            assert_that(messages[1]["content"], equal_to("Reply with one of: once, deny"))
            assert_that(messages[1]["approval"], none())


def test_a_viewer_cannot_answer_an_approval():
    with given([*_GIVEN[:-1], there_is_an_agent(status=AgentStatus.RUNNING), _switch_to_viewer()]) as context:
        with when("a viewer tries to answer an approval"):
            response = context.client.post(
                f"{_BASE}/{context.agent.id}/web-chat/messages",
                headers=_auth(context),
                json={"text": "once", "approval_id": "run_1:1726051234.5"},
            )

        with then("it is forbidden"):
            assert_that(response.status_code, equal_to(status.HTTP_403_FORBIDDEN))


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


def test_list_messages_returns_the_newest_500_messages_in_chronological_order():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        seed = _send(context, "seed", thread_id="thread-a")
        seed_id = UUID(str(seed["id"]))
        history_ids = [uuid7() for _ in range(501)]
        content_by_id = {seed_id: "seed"}
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            connection = session.exec(
                select(CommunicationConnection).where(
                    CommunicationConnection.agent_id == context.agent.id,
                    CommunicationConnection.platform_key == "web",
                )
            ).one()

        messages = []
        for index, message_id in enumerate(history_ids):
            content = f"history-{index}"
            content_by_id[message_id] = content
            messages.append(
                AgentChatMessage(
                    id=message_id,
                    agent_id=context.agent.id,
                    connection_id=connection.id,
                    openclaw_msg_id=f"history-{index}",
                    session_key="web-chat:thread-a",
                    channel_id=str(context.user.id),
                    thread_id="thread-a",
                    direction=MessageDirection.INBOUND,
                    conversation_type=ConversationType.DM,
                    content=content,
                    occurred_at=datetime.now(UTC),
                )
            )

        with Session(delegate.engine) as session:
            session.add_all(messages)
            session.commit()

        response = client.get(
            f"{_BASE}/{context.agent.id}/web-chat/messages",
            headers=_auth(context),
            params={"thread_id": "thread-a"},
        )

        expected_ids = sorted([seed_id, *history_ids])[-500:]
        returned_ids = [UUID(message["id"]) for message in response.json()]
        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(returned_ids, equal_to(expected_ids))
        assert_that(
            [message["content"] for message in response.json()],
            equal_to([content_by_id[message_id] for message_id in expected_ids]),
        )


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


def test_list_threads_applies_the_limit_before_returning_rows():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        _send(context, "oldest", thread_id="thread-000")
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            connection = session.exec(
                select(CommunicationConnection).where(
                    CommunicationConnection.agent_id == context.agent.id,
                    CommunicationConnection.platform_key == "web",
                )
            ).one()

        now = datetime.now(UTC)
        messages = [
            AgentChatMessage(
                id=uuid7(),
                agent_id=context.agent.id,
                connection_id=connection.id,
                openclaw_msg_id=f"thread-{index:03d}",
                session_key=f"web-chat:thread-{index:03d}",
                channel_id=str(context.user.id),
                thread_id=f"thread-{index:03d}",
                direction=MessageDirection.INBOUND,
                conversation_type=ConversationType.DM,
                content=f"message-{index}",
                occurred_at=now.replace(microsecond=0) + timedelta(seconds=index),
            )
            for index in range(1, 102)
        ]
        with Session(delegate.engine) as session:
            session.add_all(messages)
            session.commit()

        response = client.get(
            f"{_BASE}/{context.agent.id}/web-chat/threads",
            headers=_auth(context),
        )

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            [thread["thread_id"] for thread in response.json()],
            equal_to([f"thread-{index:03d}" for index in range(101, 1, -1)]),
        )


def test_thread_title_falls_back_to_the_first_message_when_unrenamed():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I send a couple of messages on a thread I never rename"):
            _send(context, "what can you help me with today?", thread_id="thread-a")
            _send(context, "a follow-up", thread_id="thread-a")
        with when("I list threads"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/web-chat/threads",
                headers=_auth(context),
            )
        with then("the title is derived from the first message, not the last"):
            threads = response.json()
            assert_that(threads[0]["title"], equal_to("what can you help me with today?"))


def test_renaming_a_thread_overrides_the_derived_title():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I send a message on a thread"):
            _send(context, "original opener", thread_id="thread-a")
        with when("I rename it"):
            rename_response = client.patch(
                f"{_BASE}/{context.agent.id}/web-chat/threads/thread-a",
                headers=_auth(context),
                json={"display_name": "My renamed thread"},
            )
        with then("the rename call returns the new title"):
            assert_that(rename_response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(rename_response.json()["title"], equal_to("My renamed thread"))
        with when("I list threads again"):
            list_response = client.get(
                f"{_BASE}/{context.agent.id}/web-chat/threads",
                headers=_auth(context),
            )
        with then("the custom name sticks, overriding the derived title"):
            threads = list_response.json()
            assert_that(threads[0]["title"], equal_to("My renamed thread"))


def test_renaming_a_thread_with_no_messages_yet_still_persists():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I rename a thread before sending anything to it"):
            response = client.patch(
                f"{_BASE}/{context.agent.id}/web-chat/threads/thread-a",
                headers=_auth(context),
                json={"display_name": "Pre-named thread"},
            )
        with then("the rename still succeeds"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["title"], equal_to("Pre-named thread"))
        with when("I later send a message on that thread and list threads"):
            _send(context, "hello", thread_id="thread-a")
            list_response = client.get(
                f"{_BASE}/{context.agent.id}/web-chat/threads",
                headers=_auth(context),
            )
        with then("the custom name is still there"):
            threads = list_response.json()
            assert_that(threads[0]["title"], equal_to("Pre-named thread"))


def test_deleting_a_thread_hides_it_from_the_list():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I send messages on two threads"):
            _send(context, "keep me", thread_id="thread-a")
            _send(context, "delete me", thread_id="thread-b")
        with when("I delete thread-b"):
            delete_response = client.delete(
                f"{_BASE}/{context.agent.id}/web-chat/threads/thread-b",
                headers=_auth(context),
            )
        with then("the delete call succeeds"):
            assert_that(delete_response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        with when("I list threads"):
            list_response = client.get(
                f"{_BASE}/{context.agent.id}/web-chat/threads",
                headers=_auth(context),
            )
        with then("only the thread I kept is visible"):
            threads = list_response.json()
            assert_that([t["thread_id"] for t in threads], equal_to(["thread-a"]))


def test_sending_a_message_revives_a_deleted_thread():
    with given(_GIVEN) as context:
        client: TestClient = context.client
        with when("I send a message, delete the thread, then message it again"):
            _send(context, "first", thread_id="thread-a")
            client.delete(
                f"{_BASE}/{context.agent.id}/web-chat/threads/thread-a",
                headers=_auth(context),
            )
            _send(context, "I'm back", thread_id="thread-a")
        with when("I list threads"):
            response = client.get(
                f"{_BASE}/{context.agent.id}/web-chat/threads",
                headers=_auth(context),
            )
        with then("the thread is visible again"):
            threads = response.json()
            assert_that([t["thread_id"] for t in threads], equal_to(["thread-a"]))


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

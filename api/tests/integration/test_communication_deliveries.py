from datetime import UTC, datetime
from uuid import UUID

from hamcrest import assert_that, contains_string, equal_to, has_entries, has_key, is_, none, not_
from sqlmodel import Session, col, select
from starlette.testclient import TestClient

from api.domains.agents.models import AgentStatus
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.models import (
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationJournalEntry,
    CommunicationSender,
    ConnectionObservedStatus,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
    RuntimeReplyCreate,
)
from api.domains.communications.repository import CommunicationConnectionRepository
from api.domains.conversations.models import AgentChatMessage
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
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "SKIP_DISCORD_TOKEN_VALIDATION": "true",
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


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _create_connection(
    context,
    bot_token: str = "gateway-token",
    display_name: str = "Gateway Discord",
) -> UUID:
    client: TestClient = context.client
    response = client.post(
        f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections",
        json={
            "platform_key": "discord",
            "display_name": display_name,
            "settings": {"guild_ids": ["guild-one"]},
            "credentials": {"bot_token": bot_token},
        },
        headers=_auth(context),
    )
    assert_that(response.status_code, equal_to(201))
    return UUID(response.json()["id"])


def _envelope(message_id: str) -> NormalizedCommunicationEnvelope:
    return NormalizedCommunicationEnvelope(
        provider_message_id=message_id,
        occurred_at=datetime.now(UTC),
        location=ConversationLocation(id="channel-one", type="CHANNEL", thread_id="thread-one"),
        sender=CommunicationSender(id="person-one", display_name="Person One"),
        text=f"message {message_id}",
    )


def _message(context, message_id: UUID) -> AgentChatMessage:
    delegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        message = session.get(AgentChatMessage, message_id)
        assert message is not None
        return message


def _delivery(context, delivery_id: UUID) -> CommunicationDelivery:
    delegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        delivery = session.get(CommunicationDelivery, delivery_id)
        assert delivery is not None
        return delivery


def test_inbound_acceptance_is_idempotent() -> None:
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        connection_id = _create_connection(context)
        repository = context.injector.get(CommunicationDeliveryRepository)

        with when("the provider retries one inbound message"):
            first = repository.accept_inbound(connection_id=connection_id, envelope=_envelope("provider-1"))
            duplicate = repository.accept_inbound(connection_id=connection_id, envelope=_envelope("provider-1"))

        with then("one canonical message and delivery identity are returned"):
            assert_that(first.status, equal_to(CommunicationDeliveryStatus.PENDING))
            assert_that(duplicate.message_id, equal_to(first.message_id))
            assert_that(duplicate.delivery_id, equal_to(first.delivery_id))
            assert_that(duplicate.duplicate, is_(True))


def test_runtime_claim_serializes_one_conversation() -> None:
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        connection_id = _create_connection(context)
        repository = context.injector.get(CommunicationDeliveryRepository)
        repository.accept_inbound(connection_id=connection_id, envelope=_envelope("provider-1"))
        repository.accept_inbound(connection_id=connection_id, envelope=_envelope("provider-2"))

        with when("the runtime claims work for the same conversation"):
            first = repository.claim_next_inbound(agent_id=context.agent.id)
            blocked = repository.claim_next_inbound(agent_id=context.agent.id)
            completed = repository.complete_runtime_delivery(
                first.delivery_id if first is not None else UUID(int=0),
                agent_id=context.agent.id,
                succeeded=True,
            )
            second = repository.claim_next_inbound(agent_id=context.agent.id)

        with then("the second message waits for the first delivery"):
            assert_that(first, is_(not_(none())))
            assert_that(blocked, none())
            assert_that(completed, is_(True))
            assert_that(second, is_(not_(none())))
            assert_that(
                second.envelope.provider_message_id if second is not None else None,
                equal_to("provider-2"),
            )


def test_thread_state_is_durable_and_connection_scoped() -> None:
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        connection_id = _create_connection(context, bot_token="gateway-token-one")
        second_connection_id = _create_connection(
            context,
            bot_token="gateway-token-two",
            display_name="Gateway Discord Two",
        )
        repository = context.injector.get(CommunicationDeliveryRepository)
        envelope = _envelope("provider-owned")

        repository.accept_inbound(connection_id=connection_id, envelope=envelope)

        with then("only the accepted Connection owns the persisted thread"):
            assert_that(
                repository.thread_has_agent_state(connection_id=connection_id, location=envelope.location), is_(True)
            )
            assert_that(
                repository.thread_has_agent_state(connection_id=second_connection_id, location=envelope.location),
                is_(False),
            )
            assert_that(
                repository.thread_has_agent_state(
                    connection_id=connection_id,
                    location=ConversationLocation(id="other-channel", type="CHANNEL", thread_id="thread-one"),
                ),
                is_(False),
            )


def test_message_for_intentionally_stopped_agent_is_terminally_unavailable() -> None:
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.STOPPED)]) as context:
        connection_id = _create_connection(context)
        repository = context.injector.get(CommunicationDeliveryRepository)

        with when("a message arrives while the Agent is deliberately stopped"):
            accepted = repository.accept_inbound(
                connection_id=connection_id,
                envelope=_envelope("provider-stopped"),
            )

        with then("it is recorded but never queued for later execution"):
            assert_that(accepted.status, equal_to(CommunicationDeliveryStatus.UNAVAILABLE))
            assert_that(repository.claim_next_inbound(agent_id=context.agent.id), none())


def test_duplicate_delivery_backfills_a_previously_missing_name() -> None:
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        connection_id = _create_connection(context)
        repository = context.injector.get(CommunicationDeliveryRepository)
        nameless = _envelope("provider-1").model_copy(
            update={"sender": CommunicationSender(id="person-one", display_name=None)}
        )

        with when("the first delivery arrives before the sender name could be resolved"):
            first = repository.accept_inbound(connection_id=connection_id, envelope=nameless)

        with then("the message is stored without a sender name"):
            assert_that(_message(context, first.message_id).sender_name, none())

        resolved = _envelope("provider-1").model_copy(
            update={
                "location": ConversationLocation(
                    id="channel-one",
                    type="CHANNEL",
                    thread_id="thread-one",
                    display_name="general",
                )
            }
        )

        with when("the provider retries the same message and names are now available"):
            retried = repository.accept_inbound(connection_id=connection_id, envelope=resolved)

        with then("the message and runtime envelope are backfilled without a duplicate"):
            assert_that(retried.duplicate, is_(True))
            assert_that(retried.message_id, equal_to(first.message_id))
            assert_that(_message(context, first.message_id).sender_name, equal_to("Person One"))
            stored_envelope = _delivery(context, first.delivery_id).envelope
            assert_that(stored_envelope["sender"]["display_name"], equal_to("Person One"))
            assert_that(stored_envelope["location"]["display_name"], equal_to("general"))


def test_duplicate_delivery_does_not_erase_a_known_name_with_null() -> None:
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        connection_id = _create_connection(context)
        repository = context.injector.get(CommunicationDeliveryRepository)

        with when("the first delivery arrives with a resolved sender name"):
            first = repository.accept_inbound(connection_id=connection_id, envelope=_envelope("provider-1"))

        nameless_retry = _envelope("provider-1").model_copy(
            update={"sender": CommunicationSender(id="person-one", display_name=None)}
        )

        with when("a later retry arrives without a resolved name"):
            retried = repository.accept_inbound(connection_id=connection_id, envelope=nameless_retry)

        with then("the already-known name is preserved rather than cleared"):
            assert_that(retried.duplicate, is_(True))
            assert_that(_message(context, first.message_id).sender_name, equal_to("Person One"))


def test_outbound_reply_inherits_channel_name_from_source_inbound_location() -> None:
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        connection_id = _create_connection(context)
        repository = context.injector.get(CommunicationDeliveryRepository)
        envelope = _envelope("provider-1").model_copy(
            update={
                "location": ConversationLocation(
                    id="channel-one", type="CHANNEL", thread_id="thread-one", display_name="general"
                )
            }
        )
        accepted = repository.accept_inbound(connection_id=connection_id, envelope=envelope)

        with when("the runtime replies to that inbound delivery"):
            outbound_delivery_id = repository.enqueue_runtime_reply(
                agent_id=context.agent.id,
                source_delivery_id=accepted.delivery_id,
                reply=RuntimeReplyCreate(idempotency_key="reply-1", text="hello back"),
            )

        with then("the outbound message carries the source channel's name"):
            outbound_message_id = _delivery(context, outbound_delivery_id).message_id
            assert_that(_message(context, outbound_message_id).channel_name, equal_to("general"))


def test_diagnostics_reports_pipeline_transitions_without_message_content() -> None:
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        connection_id = _create_connection(context)
        repository = context.injector.get(CommunicationDeliveryRepository)
        connections = context.injector.get(CommunicationConnectionRepository)
        connections.record_health(connection_id, ConnectionObservedStatus.CONNECTED)

        accepted = repository.accept_inbound(connection_id=connection_id, envelope=_envelope("provider-1"))
        claimed = repository.claim_next_inbound(agent_id=context.agent.id)
        assert claimed is not None
        assert repository.complete_runtime_delivery(
            claimed.delivery_id,
            agent_id=context.agent.id,
            succeeded=True,
        )
        outbound_id = repository.enqueue_runtime_reply(
            agent_id=context.agent.id,
            source_delivery_id=accepted.delivery_id,
            reply=RuntimeReplyCreate(idempotency_key="reply-1", text="private response"),
        )
        assert repository.claim_next_outbound() is not None
        assert repository.complete_outbound(outbound_id, provider_message_id="provider-reply")

        with when("I inspect the completed Connection pipeline"):
            response = context.client.get(
                f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections/{connection_id}/summary",
                headers=_auth(context),
            )
            journal = context.client.get(
                f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections/{connection_id}/journal?kind=delivery",
                headers=_auth(context),
            )

        with then("the diagnostics are complete and content-free"):
            assert_that(response.status_code, equal_to(200))
            body = response.json()
            assert_that(body["provider_connectivity"], equal_to("CONNECTED"))
            assert_that(body["end_to_end_health"], equal_to("healthy"))
            assert_that(
                body["pipeline"],
                equal_to(
                    {
                        "provider_observed": 0,
                        "policy_admitted": 0,
                        "queued": 1,
                        "agent_claimed": 1,
                        "model_completed": 1,
                        "reply_queued": 1,
                        "provider_delivered": 1,
                        "dead_lettered": 0,
                    }
                ),
            )
            assert_that(body["delivery_counts"]["succeeded"], equal_to(2))
            assert_that(body, not_(has_key("latest_transitions")))
            assert_that(journal.status_code, equal_to(200))
            assert_that(journal.json()["total"], not_(equal_to(0)))
            assert_that(
                journal.json()["items"][0],
                has_entries(
                    direction="OUTBOUND",
                    delivery_status="SUCCEEDED",
                    queue_wait_ms=not_(none()),
                    processing_ms=not_(none()),
                    next_retry_at=none(),
                ),
            )
            assert_that(repr(body), not_(contains_string("message provider-1")))
            assert_that(repr(body), not_(contains_string("private response")))
            assert_that(repr(journal.json()), not_(contains_string("message provider-1")))
            assert_that(repr(journal.json()), not_(contains_string("private response")))


def test_dead_letter_retry_reuses_one_delivery_and_is_idempotent() -> None:
    with given([*_GIVEN, there_is_an_agent(status=AgentStatus.RUNNING)]) as context:
        client: TestClient = context.client
        connection_id = _create_connection(context)
        repository = context.injector.get(CommunicationDeliveryRepository)
        accepted = repository.accept_inbound(connection_id=connection_id, envelope=_envelope("provider-1"))
        outbound_id = repository.enqueue_runtime_reply(
            agent_id=context.agent.id,
            source_delivery_id=accepted.delivery_id,
            reply=RuntimeReplyCreate(idempotency_key="reply-1", text="retry me"),
        )
        claimed = repository.claim_next_outbound()
        assert claimed is not None
        assert repository.complete_outbound(
            outbound_id,
            error_code="provider_timeout",
            error_message="temporary provider failure",
            max_attempts=1,
        )
        original = _delivery(context, outbound_id)
        original_message_id = original.message_id

        with when("I retry the one dead-lettered delivery"):
            retried = client.post(
                f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections/{connection_id}/deliveries/{outbound_id}/retry",
                headers=_auth(context),
            )
            duplicate_retry = client.post(
                f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections/{connection_id}/deliveries/{outbound_id}/retry",
                headers=_auth(context),
            )

        with then("the existing delivery is requeued once without a duplicate message"):
            assert_that(retried.status_code, equal_to(202))
            assert_that(
                retried.json(),
                has_entries(
                    delivery_id=str(outbound_id),
                    status="PENDING",
                    attempt_count=0,
                ),
            )
            assert_that(duplicate_retry.status_code, equal_to(409))
            current = _delivery(context, outbound_id)
            assert_that(current.message_id, equal_to(original_message_id))
            assert_that(current.status, equal_to(CommunicationDeliveryStatus.PENDING))
            assert_that(current.id, equal_to(original.id))
            with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
                journal = list(
                    session.exec(
                        select(CommunicationJournalEntry)
                        .where(CommunicationJournalEntry.delivery_id == outbound_id)
                        .order_by(col(CommunicationJournalEntry.occurred_at), col(CommunicationJournalEntry.id))
                    ).all()
                )
            assert_that(
                [getattr(entry.stage, "value", entry.stage) for entry in journal],
                equal_to(
                    [
                        "reply_queued",
                        "provider_delivery_attempted",
                        "provider_delivery_attempted",
                        "dead_lettered",
                        "retry_requested",
                    ]
                ),
            )

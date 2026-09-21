"""End to end: an external system triggers an Agent over HTTP with no human involved.

These cover what a user can actually do when this ships -- point Jira automation at a
URL, copy the secret shown once, and have the Agent run the job named in the caller's
own prompt -- plus the contract guarantees a machine caller depends on: dedupe,
ordering, and never being told a job ran when it did not.
"""

import hashlib
import hmac
import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_item, has_length, is_, less_than_or_equal_to, not_
from sqlmodel import Session, col, select
from starlette.testclient import TestClient

from api.core.config import get_config
from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.execution_policy import DeliveryLimits
from api.domains.communications.gateway_routes import MAX_WEBHOOK_BODY_BYTES
from api.domains.communications.models import (
    CommunicationConnection,
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationDirection,
    CommunicationJournalEntry,
    CommunicationJournalStage,
    CommunicationSender,
    ConversationLocation,
    DeliveryKind,
    NormalizedCommunicationEnvelope,
)
from api.domains.communications.plugins.webhook import EVENT_HEADER_PREFIX, SIGNATURE_HEADER, VERSION_HEADER
from api.domains.conversations.models import AgentChatMessage, ConversationType
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import (
    create_test_client,
    prepare_api_server,
    prepare_communications_server,
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

PROMPT = "Write release notes for PROJ-1."

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "API_EXTERNAL_URL": "https://api.agentbarn.test",
            "SKIP_DISCORD_TOKEN_VALIDATION": "true",
        }
    ),
    prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
    prepare_api_server(),
    create_test_client(),
    prepare_communications_server(),
    database_repo_is_ready(),
    database_is_clean(),
    there_is_an_organization_with_user_and_access_token(),
    use_org_for_auth(),
    there_is_an_agent(status=AgentStatus.RUNNING),
]


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _create_webhook_connection(context) -> dict[str, Any]:
    """No secret is supplied -- the server mints one and reveals it once, in the
    create response, exactly as it would for a real user."""
    response = context.client.post(
        f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections",
        json={"platform_key": "webhook", "display_name": "Jira automation", "credentials": {}},
        headers=_auth(context),
    )
    assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
    return response.json()


def _body(event_id: str = "evt-1", **overrides) -> dict:
    return {"event_id": event_id, "prompt": PROMPT, **overrides}


def _sign(secret: str, raw: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()


def _fire(context, connection_id: str, secret: str, body: dict | None = None, *, version: str = "1"):
    payload = _body() if body is None else body
    raw = json.dumps(payload).encode()
    headers = {VERSION_HEADER: version, SIGNATURE_HEADER: _sign(secret, raw)}
    return context.communications_client.post(
        f"/communications/v1/webhooks/{connection_id}",
        content=raw,
        headers={**headers, "Content-Type": "application/json"},
    )


def _runtime_auth(context, version: str = "3") -> dict[str, str]:
    runtime_key = "runtime-communications-key"
    agent_repository: AgentRepository = context.injector.get(AgentRepository)
    context.agent.communication_key_encrypted = encrypt_token(runtime_key, TEST_ENCRYPTION_KEY)
    agent_repository.save(context.agent)
    return {"Authorization": f"Bearer {runtime_key}", "X-AgentBarn-Communications-Version": version}


def _deliveries(context) -> list[CommunicationDelivery]:
    delegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        return list(
            session.exec(
                select(CommunicationDelivery)
                .where(col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND)
                .order_by(col(CommunicationDelivery.created_at))
            ).all()
        )


_GIVEN_STOPPED = [*_GIVEN[:-1], there_is_an_agent(status=AgentStatus.STOPPED)]


def _start_agent(context) -> None:
    context.agent.status = AgentStatus.RUNNING
    context.injector.get(AgentRepository).save(context.agent)


def _claim(context):
    return context.communications_client.post(
        f"/communications/v1/agents/{context.agent.id}/deliveries/claim",
        headers=_runtime_auth(context),
    )


def _complete(context, delivery_id: str, *, succeeded: bool, error_code: str | None = None):
    body: dict[str, Any] = {"succeeded": succeeded}
    if error_code is not None:
        body.update(error_code=error_code, error_message="the run failed")
    return context.communications_client.post(
        f"/communications/v1/agents/{context.agent.id}/deliveries/{delivery_id}/complete",
        json=body,
        headers=_runtime_auth(context),
    )


def _fire_events(context, connection: dict[str, Any], count: int, *, prefix: str = "evt") -> None:
    secret = connection["credential_reveal"]["signing_secret"]
    for number in range(1, count + 1):
        response = _fire(context, connection["id"], secret, _body(f"{prefix}-{number}"))
        assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))


def _edit_delivery(context, delivery_id: str, **changes) -> None:
    delegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        row = session.get(CommunicationDelivery, UUID(delivery_id))
        assert row is not None
        for name, value in changes.items():
            setattr(row, name, value)
        session.add(row)
        session.commit()


def _expire_lease(context, delivery_id: str) -> None:
    _edit_delivery(context, delivery_id, lease_expires_at=datetime.now(UTC) - timedelta(seconds=1))


def _clear_backoff(context, delivery_id: str) -> None:
    _edit_delivery(context, delivery_id, available_at=datetime.now(UTC) - timedelta(seconds=1))


def _create_chat_connection(context) -> UUID:
    response = context.client.post(
        f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections",
        json={
            "platform_key": "discord",
            "display_name": "Team Discord",
            "settings": {"allowed_channel_ids": ["channel-one"]},
            "credentials": {"bot_token": "chat-token"},
        },
        headers=_auth(context),
    )
    assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
    return UUID(response.json()["id"])


def _chat_envelope(message_id: str) -> NormalizedCommunicationEnvelope:
    # One thread per message, so chat messages do not queue behind each other.
    return NormalizedCommunicationEnvelope(
        provider_message_id=message_id,
        occurred_at=datetime.now(UTC),
        location=ConversationLocation(id="channel-one", type="CHANNEL", thread_id=f"thread-{message_id}"),
        sender=CommunicationSender(id="person-one", display_name="Person One"),
        text=f"message {message_id}",
    )


def _event_envelope(event_id: str) -> NormalizedCommunicationEnvelope:
    return NormalizedCommunicationEnvelope(
        provider_message_id=event_id,
        occurred_at=datetime.now(UTC),
        location=ConversationLocation(id="events", type="EVENT", display_name="Events"),
        text=PROMPT,
        provider_metadata={"event_id": event_id},
    )


def _small_backlog(cap: int) -> DeliveryLimits:
    return replace(DeliveryLimits.from_config(get_config()), backlog_cap=cap)


def _journal_stages(context, delivery_id: UUID) -> list[CommunicationJournalStage]:
    delegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        rows = session.exec(
            select(CommunicationJournalEntry).where(col(CommunicationJournalEntry.delivery_id) == delivery_id)
        ).all()
    return [CommunicationJournalStage(row.stage) for row in rows]


def test_a_user_gets_a_url_and_a_secret_to_paste_into_the_calling_system() -> None:
    with given(_GIVEN) as context:
        with when("a user adds a webhook trigger to their agent"):
            connection = _create_webhook_connection(context)

        with then("the connection shows where the caller should send events, and its secret once"):
            assert_that(
                connection["webhook_url"],
                equal_to(f"https://api.agentbarn.test/communications/v1/webhooks/{connection['id']}"),
            )
            secret = connection["credential_reveal"]["signing_secret"]
            assert_that(len(secret) >= 32, is_(True))


def test_the_secret_is_never_shown_a_second_time() -> None:
    with given(_GIVEN) as context:
        _create_webhook_connection(context)

        with when("the connection is read back"):
            listed = context.client.get(
                f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections",
                headers=_auth(context),
            )

        with then("there is no path back to the plaintext secret"):
            [read_back] = listed.json()
            assert_that(read_back.get("credential_reveal"), is_(None))


def test_a_signed_event_makes_the_agent_run_the_job() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]

        with when("an external system posts a signed event"):
            response = _fire(context, connection["id"], secret)

        with then("it is accepted for processing and queued as a machine event"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            [delivery] = _deliveries(context)
            assert_that(delivery.status, equal_to(CommunicationDeliveryStatus.PENDING))
            assert_that(delivery.kind, equal_to(DeliveryKind.EVENT))
            # The caller's prompt IS the message text -- no template, no payload object.
            assert_that(delivery.envelope["text"], equal_to(PROMPT))


def test_the_claimed_delivery_tells_the_agent_it_was_triggered_and_carries_the_callers_prompt() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        _fire(context, connection["id"], secret)

        with when("the agent claims its pending delivery"):
            response = _claim(context)

        with then("the runtime is told the run was triggered, then given exactly what the caller asked for"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            delivery = response.json()
            assert_that(delivery["kind"], equal_to("EVENT"))
            assert_that(delivery["envelope"]["text"].startswith(EVENT_HEADER_PREFIX), is_(True))
            assert_that(delivery["envelope"]["text"].endswith(f"\n\n{PROMPT}"), is_(True))
            assert_that(delivery["progress_updates"], is_(False))
            execution = delivery["execution"]
            assert_that(execution["resume_session"], is_(False))
            assert_that(execution["approvals_enabled"], is_(False))
            assert_that(execution["busy_releases"], is_(True))
            assert_that(execution["busy_notice"], is_(None))
            # An event has no conversation to reply into.
            assert_that(execution["session_key"].startswith("connection:"), is_(False))

        with then("the caller's own view of the call still shows only their prompt"):
            calls = context.client.get(_calls_url(context, connection["id"]), headers=_auth(context))
            [call] = calls.json()["items"]
            assert_that(call["prompt"], equal_to(PROMPT))


def test_an_agent_on_the_previous_protocol_is_never_handed_an_event() -> None:
    """A pod started before this shipped runs an adapter that would treat the event as a
    chat turn and complete it as succeeded when busy. Withhold it instead."""
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        _fire(context, connection["id"], secret)

        with when("a pod speaking the previous protocol version claims"):
            response = context.communications_client.post(
                f"/communications/v1/agents/{context.agent.id}/deliveries/claim",
                headers=_runtime_auth(context, version="2"),
            )

        with then("it gets nothing, and the event is still waiting"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            [delivery] = _deliveries(context)
            assert_that(delivery.status, equal_to(CommunicationDeliveryStatus.PENDING))


def test_the_same_event_twice_produces_one_delivery() -> None:
    """A caller that retries after a timeout must not run the job twice."""
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]

        with when("the caller sends the same event id twice"):
            first = _fire(context, connection["id"], secret)
            second = _fire(context, connection["id"], secret)

        with then("both are accepted but only one job exists"):
            assert_that(first.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(second.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(_deliveries(context), has_length(1))


def test_events_without_an_ordering_key_never_wait_for_each_other() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]

        with when("two unrelated events arrive"):
            _fire(context, connection["id"], secret, _body("evt-1"))
            _fire(context, connection["id"], secret, _body("evt-2"))

        with then("neither serialises against the other"):
            first, second = _deliveries(context)
            assert_that(first.ordering_key, not_(equal_to(second.ordering_key)))


def test_events_sharing_an_ordering_key_run_one_after_another() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]

        with when("two events declare the same ordering key"):
            _fire(context, connection["id"], secret, _body("evt-1", ordering_key="PROJ-1"))
            _fire(context, connection["id"], secret, _body("evt-2", ordering_key="PROJ-1"))

        with then("they share an ordering key, so the queue runs them in turn"):
            first, second = _deliveries(context)
            assert_that(first.ordering_key, equal_to(second.ordering_key))

        with when("the agent claims"):
            claimed = context.communications_client.post(
                f"/communications/v1/agents/{context.agent.id}/deliveries/claim",
                headers=_runtime_auth(context),
            )
            blocked = context.communications_client.post(
                f"/communications/v1/agents/{context.agent.id}/deliveries/claim",
                headers=_runtime_auth(context),
            )

        with then("only one is in flight at a time"):
            assert_that(claimed.status_code, equal_to(status.HTTP_200_OK))
            assert_that(blocked.status_code, equal_to(status.HTTP_204_NO_CONTENT))


def test_a_released_delivery_goes_back_without_spending_an_attempt() -> None:
    """Never acknowledge work that did not happen."""
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        _fire(context, connection["id"], secret)
        claimed = context.communications_client.post(
            f"/communications/v1/agents/{context.agent.id}/deliveries/claim",
            headers=_runtime_auth(context),
        ).json()
        assert_that(_deliveries(context)[0].attempt_count, equal_to(1))

        with when("the runtime hands it back because it could not start"):
            response = context.communications_client.post(
                f"/communications/v1/agents/{context.agent.id}/deliveries/{claimed['delivery_id']}/release",
                headers=_runtime_auth(context),
            )

        with then("it is pending again and the attempt is given back"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            [delivery] = _deliveries(context)
            assert_that(delivery.status, equal_to(CommunicationDeliveryStatus.PENDING))
            assert_that(delivery.attempt_count, equal_to(0))
            assert_that(delivery.completed_at, is_(None))


def test_releasing_a_cancelled_delivery_ends_it_as_cancelled() -> None:
    """A cancel request wins over a release, and must not be recorded as the Agent being busy."""
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        _fire(context, connection["id"], secret)
        claimed = context.communications_client.post(
            f"/communications/v1/agents/{context.agent.id}/deliveries/claim",
            headers=_runtime_auth(context),
        ).json()
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            row = session.get(CommunicationDelivery, UUID(claimed["delivery_id"]))
            assert row is not None
            row.cancel_requested_at = datetime.now(UTC)
            session.add(row)
            session.commit()

        with when("the runtime releases the delivery"):
            response = context.communications_client.post(
                f"/communications/v1/agents/{context.agent.id}/deliveries/{claimed['delivery_id']}/release",
                headers=_runtime_auth(context),
            )

        with then("it ends as cancelled, not requeued and not blamed on a busy Agent"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            [delivery] = _deliveries(context)
            assert_that(delivery.status, equal_to(CommunicationDeliveryStatus.CANCELLED))
            assert_that(delivery.last_error_code, equal_to("CANCELLED"))


def test_the_event_is_recorded_as_a_machine_event_but_not_surfaced_as_a_conversation() -> None:
    """The transcript row is still written (a delivery needs one), but a webhook call is
    listed on the webhook's own calls list, not as a conversation."""
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        _fire(context, connection["id"], secret)

        with then("the transcript row exists and is marked as an EVENT"):
            delegate = context.injector.get(PostgresRepositoryDelegate)
            with Session(delegate.engine) as session:
                [message] = session.exec(select(AgentChatMessage)).all()
            assert_that(message.conversation_type, equal_to(ConversationType.EVENT))

        with then("but it does not appear in the conversations list"):
            response = context.client.get(
                f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/conversations/channels",
                headers=_auth(context),
            )
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json(), equal_to([]))


def test_a_wrong_secret_is_rejected() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)

        with when("a caller signs with the wrong secret"):
            response = _fire(context, connection["id"], "w" * 40)

        with then("it is refused and nothing is queued"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
            assert_that(_deliveries(context), has_length(0))


def test_a_body_altered_after_signing_is_rejected() -> None:
    """The whole point of HMAC over raw bytes: the signature covers what was sent."""
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        signature = _sign(secret, json.dumps(_body()).encode())

        with when("the body is changed but the signature is kept"):
            response = context.communications_client.post(
                f"/communications/v1/webhooks/{connection['id']}",
                content=json.dumps(_body("evt-tampered")).encode(),
                headers={VERSION_HEADER: "1", SIGNATURE_HEADER: signature, "Content-Type": "application/json"},
            )

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
            assert_that(_deliveries(context), has_length(0))


def test_an_unsupported_contract_version_says_so() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]

        with when("a caller sends a version this server does not speak"):
            response = _fire(context, connection["id"], secret, version="99")

        with then("it is a clear rejection, not a silent accept"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("Unsupported webhook contract version"))


def test_a_body_that_is_not_json_is_rejected() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]

        with when("the caller sends something that is not JSON"):
            response = context.communications_client.post(
                f"/communications/v1/webhooks/{connection['id']}",
                content=b"not json at all",
                headers={
                    VERSION_HEADER: "1",
                    SIGNATURE_HEADER: _sign(secret, b"not json at all"),
                    "Content-Type": "application/json",
                },
            )

        with then("it is a 400 naming the problem"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_an_event_missing_its_id_is_told_why() -> None:
    """A machine caller cannot read a 202 and work out that nothing happened."""
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]

        with when("the caller omits event_id"):
            response = _fire(context, connection["id"], secret, {"prompt": PROMPT})

        with then("the reason comes back"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("event_id is required"))


def test_an_event_missing_its_prompt_is_told_why() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]

        with when("the caller omits prompt"):
            response = _fire(context, connection["id"], secret, {"event_id": "evt-1"})

        with then("the reason comes back"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("prompt is required"))


def test_an_unknown_connection_is_not_a_probe_oracle() -> None:
    with given(_GIVEN) as context:
        with when("someone posts to a connection id that does not exist"):
            response = _fire(context, str(UUID(int=0)), "w" * 40)

        with then("it looks exactly like a failed authentication"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_a_reply_inherits_the_contract_and_the_thread_of_what_it_answers() -> None:
    """Both halves of one exchange must agree. Nothing reads either field on an outbound
    row today, which is exactly why a wrong value here would go unnoticed until the
    reply path is built on top of it."""
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        _fire(context, connection["id"], secret)
        claimed = context.communications_client.post(
            f"/communications/v1/agents/{context.agent.id}/deliveries/claim",
            headers=_runtime_auth(context),
        ).json()

        with when("the agent replies to the event"):
            response = context.communications_client.post(
                f"/communications/v1/agents/{context.agent.id}/deliveries/{claimed['delivery_id']}/replies",
                headers=_runtime_auth(context),
                json={"idempotency_key": claimed["delivery_id"], "text": "the release notes"},
            )

        with then("the reply is an EVENT too, and sits in the same transcript thread"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            inbound = _deliveries(context)[0]
            delegate = context.injector.get(PostgresRepositoryDelegate)
            with Session(delegate.engine) as session:
                outbound = session.exec(
                    select(CommunicationDelivery).where(
                        col(CommunicationDelivery.direction) == CommunicationDirection.OUTBOUND
                    )
                ).one()
                messages = session.exec(select(AgentChatMessage).order_by(col(AgentChatMessage.occurred_at))).all()
            assert_that(outbound.kind, equal_to(DeliveryKind.EVENT))
            assert_that(inbound.kind, equal_to(DeliveryKind.EVENT))
            # One exchange, one thread: the reply must not be filed under the caller's
            # concurrency key, which has nothing to do with where the event lives.
            assert_that(len(messages), equal_to(2))
            assert_that(messages[0].session_key, equal_to(messages[1].session_key))


def test_the_signing_secret_cannot_be_chosen_through_an_update() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        chosen = "c" * 40

        with when("a user tries to set their own secret with a PATCH"):
            response = context.client.patch(
                f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}"
                f"/connections/{connection['id']}",
                json={"revision": connection["revision"], "credentials": {"signing_secret": chosen}},
                headers=_auth(context),
            )

        with then("it is refused, pointing at rotate-credentials"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("rotate-credentials"))

        with then("the generated secret still works and the chosen one does not"):
            assert_that(_fire(context, connection["id"], chosen).status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
            assert_that(_fire(context, connection["id"], secret).status_code, equal_to(status.HTTP_202_ACCEPTED))


def test_an_unsigned_request_never_gets_a_stored_credential_echoed_back() -> None:
    """Stored credentials are validated before the signature is checked. When one no
    longer fits its model, pydantic's message quotes it, and that must not reach a caller
    who has not authenticated."""
    stale_secret = "stale-secret-" + "x" * 30
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            row = session.get(CommunicationConnection, UUID(connection["id"]))
            assert row is not None
            row.credentials_encrypted = encrypt_token(
                json.dumps({"auth_mode": "hmac", "secret": stale_secret}), TEST_ENCRYPTION_KEY
            )
            session.add(row)
            session.commit()

        with when("an unsigned request arrives"):
            client = TestClient(context.communications_app, raise_server_exceptions=False)
            response = client.post(
                f"/communications/v1/webhooks/{connection['id']}",
                content=json.dumps(_body()).encode(),
                headers={VERSION_HEADER: "1", "Content-Type": "application/json"},
            )

        with then("nothing about the stored credential comes back"):
            assert_that(response.text, not_(contains_string(stale_secret)))
            assert_that(response.status_code, not_(equal_to(status.HTTP_400_BAD_REQUEST)))


def test_a_body_that_declares_it_is_too_large_is_refused_without_being_read() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)

        with when("Content-Length is over the cap but the body is tiny"):
            response = context.communications_client.post(
                f"/communications/v1/webhooks/{connection['id']}",
                content=b"{}",
                headers={"Content-Length": str(MAX_WEBHOOK_BODY_BYTES + 1), "Content-Type": "application/json"},
            )

        with then("it is refused as too large; a body that had been read would be a 400 or 401"):
            assert_that(response.status_code, equal_to(status.HTTP_413_CONTENT_TOO_LARGE))


def test_a_body_with_no_declared_length_is_still_capped_after_it_is_read() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)

        with when("an oversized body is sent chunked, so there is no Content-Length"):
            response = context.communications_client.post(
                f"/communications/v1/webhooks/{connection['id']}",
                content=iter([b"x" * (MAX_WEBHOOK_BODY_BYTES + 1)]),
                headers={"Content-Type": "application/json"},
            )

        with then("it is still refused"):
            assert_that(response.status_code, equal_to(status.HTTP_413_CONTENT_TOO_LARGE))


def test_regenerating_the_secret_keeps_the_url_but_retires_the_old_signature() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        old_secret = connection["credential_reveal"]["signing_secret"]

        with when("the secret is regenerated"):
            rotated = context.client.post(
                f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}"
                f"/connections/{connection['id']}/rotate-credentials",
                params={"revision": connection["revision"]},
                headers=_auth(context),
            )

        with then("a new secret is revealed once and the URL is unchanged"):
            assert_that(rotated.status_code, equal_to(status.HTTP_200_OK))
            new_secret = rotated.json()["credential_reveal"]["signing_secret"]
            assert_that(new_secret, not_(equal_to(old_secret)))
            assert_that(rotated.json()["webhook_url"], equal_to(connection["webhook_url"]))

        with when("a caller signs with the old secret"):
            old_signed = _fire(context, connection["id"], old_secret)

        with then("it is refused"):
            assert_that(old_signed.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))

        with when("a caller signs with the new secret"):
            new_signed = _fire(context, connection["id"], new_secret)

        with then("it is accepted"):
            assert_that(new_signed.status_code, equal_to(status.HTTP_202_ACCEPTED))


def test_two_webhooks_on_one_agent_fire_independently() -> None:
    with given(_GIVEN) as context:
        first_connection = _create_webhook_connection(context)
        second_response = context.client.post(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections",
            json={"platform_key": "webhook", "display_name": "CI pipeline", "credentials": {}},
            headers=_auth(context),
        )
        assert_that(second_response.status_code, equal_to(status.HTTP_201_CREATED))
        second_connection = second_response.json()

        with when("each fires with its own secret"):
            first_fired = _fire(
                context, first_connection["id"], first_connection["credential_reveal"]["signing_secret"]
            )
            second_fired = _fire(
                context, second_connection["id"], second_connection["credential_reveal"]["signing_secret"]
            )

        with then("both are accepted, each queuing its own delivery"):
            assert_that(first_fired.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(second_fired.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(_deliveries(context), has_length(2))

        with when("one connection's secret is used against the other's URL"):
            crossed = _fire(
                context,
                first_connection["id"],
                second_connection["credential_reveal"]["signing_secret"],
                _body("evt-2"),
            )

        with then("it is refused -- each webhook's secret is its own"):
            assert_that(crossed.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


# --- /connections/{connection_id}/calls ---


def _calls_url(context, connection_id: str) -> str:
    return (
        f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections/{connection_id}/calls"
    )


def test_a_fired_event_appears_as_a_call_with_its_prompt() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        _fire(context, connection["id"], secret, _body("evt-1", ordering_key="PROJ-1"))

        with when("the webhook's calls are listed"):
            response = context.client.get(_calls_url(context, connection["id"]), headers=_auth(context))

        with then("the call carries the event's contract and the caller's prompt"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            [call] = response.json()["items"]
            assert_that(call["event_id"], equal_to("evt-1"))
            assert_that(call["prompt"], equal_to(PROMPT))
            assert_that(call["ordering_key"], equal_to("PROJ-1"))
            assert_that(call["status"], equal_to("PENDING"))
            assert_that(call["responses"], equal_to([]))


def test_a_reply_appears_on_the_same_call() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        _fire(context, connection["id"], secret)
        claimed = context.communications_client.post(
            f"/communications/v1/agents/{context.agent.id}/deliveries/claim",
            headers=_runtime_auth(context),
        ).json()

        with when("the agent replies and the calls are listed again"):
            context.communications_client.post(
                f"/communications/v1/agents/{context.agent.id}/deliveries/{claimed['delivery_id']}/replies",
                headers=_runtime_auth(context),
                json={"idempotency_key": "reply-1", "text": "the release notes"},
            )
            response = context.client.get(_calls_url(context, connection["id"]), headers=_auth(context))

        with then("the response is attached to the call it answers"):
            [call] = response.json()["items"]
            [reply] = call["responses"]
            assert_that(reply["text"], equal_to("the release notes"))


def test_two_replies_to_one_call_both_appear() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        _fire(context, connection["id"], secret)
        claimed = context.communications_client.post(
            f"/communications/v1/agents/{context.agent.id}/deliveries/claim",
            headers=_runtime_auth(context),
        ).json()

        with when("the agent sends two replies to the same event"):
            for idx, text in enumerate(("first reply", "second reply")):
                context.communications_client.post(
                    f"/communications/v1/agents/{context.agent.id}/deliveries/{claimed['delivery_id']}/replies",
                    headers=_runtime_auth(context),
                    json={"idempotency_key": f"reply-{idx}", "text": text},
                )
            response = context.client.get(_calls_url(context, connection["id"]), headers=_auth(context))

        with then("both replies show up on the one call"):
            [call] = response.json()["items"]
            assert_that([r["text"] for r in call["responses"]], equal_to(["first reply", "second reply"]))


def test_a_failed_call_carries_its_error() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        _fire(context, connection["id"], secret)
        [delivery] = _deliveries(context)
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            row = session.get(CommunicationDelivery, delivery.id)
            assert row is not None
            row.status = CommunicationDeliveryStatus.DEAD_LETTERED
            row.last_error_code = "RUNTIME_ERROR"
            row.last_error_message = "the runtime crashed"
            session.add(row)
            session.commit()

        with when("the webhook's calls are listed"):
            response = context.client.get(_calls_url(context, connection["id"]), headers=_auth(context))

        with then("the failure is visible on the call"):
            [call] = response.json()["items"]
            assert_that(call["status"], equal_to("DEAD_LETTERED"))
            assert_that(call["last_error_code"], equal_to("RUNTIME_ERROR"))
            assert_that(call["last_error_message"], equal_to("the runtime crashed"))


def test_calls_are_paged_newest_first() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        for event_id in ("evt-1", "evt-2", "evt-3"):
            _fire(context, connection["id"], secret, _body(event_id))

        with when("the first page is requested with page_size=2"):
            first_page = context.client.get(
                _calls_url(context, connection["id"]),
                params={"page": 1, "page_size": 2},
                headers=_auth(context),
            ).json()
            second_page = context.client.get(
                _calls_url(context, connection["id"]),
                params={"page": 2, "page_size": 2},
                headers=_auth(context),
            ).json()

        with then("all three calls are covered across the two pages, newest first"):
            assert_that(first_page["total"], equal_to(3))
            assert_that([c["event_id"] for c in first_page["items"]], equal_to(["evt-3", "evt-2"]))
            assert_that([c["event_id"] for c in second_page["items"]], equal_to(["evt-1"]))


def test_a_webhook_with_no_calls_yet_has_an_empty_list() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)

        with when("the calls are listed before anything has fired"):
            response = context.client.get(_calls_url(context, connection["id"]), headers=_auth(context))

        with then("the list is simply empty"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json()["items"], equal_to([]))


# --- AF-321: never lose a triggered event ------------------------------------------------------


def test_an_event_for_a_stopped_agent_waits_while_a_chat_message_is_still_dropped() -> None:
    with given(_GIVEN_STOPPED) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        chat_connection_id = _create_chat_connection(context)
        deliveries = context.injector.get(CommunicationDeliveryRepository)

        with when("an event and a chat message both arrive while the agent is stopped"):
            response = _fire(context, connection["id"], secret)
            chat = deliveries.accept_inbound(connection_id=chat_connection_id, envelope=_chat_envelope("chat-1"))

        with then("the event waits, and the chat message is dropped as before"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            [event_row] = [row for row in _deliveries(context) if row.kind == DeliveryKind.EVENT]
            assert_that(event_row.status, equal_to(CommunicationDeliveryStatus.PENDING))
            assert_that(event_row.completed_at, is_(None))
            assert_that(event_row.last_error_code, is_(None))
            assert_that(chat.status, equal_to(CommunicationDeliveryStatus.UNAVAILABLE))
            [chat_row] = [row for row in _deliveries(context) if row.kind == DeliveryKind.CONVERSATION]
            assert_that(chat_row.last_error_code, equal_to("AGENT_STOPPED"))
            assert_that(chat_row.completed_at, is_(not_(None)))

        with when("the agent starts"):
            _start_agent(context)
            claimed = _claim(context)
            nothing_else = _claim(context)

        with then("only the event is handed to it"):
            assert_that(claimed.status_code, equal_to(status.HTTP_200_OK))
            assert_that(claimed.json()["kind"], equal_to("EVENT"))
            assert_that(nothing_else.status_code, equal_to(status.HTTP_204_NO_CONTENT))


def test_a_backlog_built_up_while_stopped_runs_oldest_first_once_the_agent_starts() -> None:
    with given(_GIVEN_STOPPED) as context:
        connection = _create_webhook_connection(context)
        _fire_events(context, connection, 3)
        _start_agent(context)

        with when("the agent starts and drains its queue"):
            claimed = [_claim(context).json()["envelope"]["provider_message_id"] for _ in range(3)]

        with then("events run in the order they arrived"):
            assert_that(claimed, equal_to(["evt-1", "evt-2", "evt-3"]))


def test_past_the_backlog_cap_the_oldest_waiting_event_is_dead_lettered() -> None:
    with given(_GIVEN_STOPPED) as context:
        connection = _create_webhook_connection(context)
        connection_id = UUID(connection["id"])
        deliveries = context.injector.get(CommunicationDeliveryRepository)

        with when("a third event arrives at a webhook that keeps at most two waiting"):
            for event_id in ("evt-1", "evt-2", "evt-3"):
                deliveries.accept_inbound(
                    connection_id=connection_id,
                    envelope=_event_envelope(event_id),
                    limits=_small_backlog(2),
                )

        with then("the oldest is dropped with a code that names the cap, and the newest two still wait"):
            oldest, middle, newest = _deliveries(context)
            assert_that(oldest.status, equal_to(CommunicationDeliveryStatus.DEAD_LETTERED))
            assert_that(oldest.last_error_code, equal_to("BACKLOG_CAP_EXCEEDED"))
            assert_that(oldest.completed_at, is_(not_(None)))
            assert_that(oldest.attempt_count, equal_to(0))
            assert_that(middle.status, equal_to(CommunicationDeliveryStatus.PENDING))
            assert_that(newest.status, equal_to(CommunicationDeliveryStatus.PENDING))
            assert_that(_journal_stages(context, oldest.id), has_item(CommunicationJournalStage.DEAD_LETTERED))

        with then("the caller can read why on the call"):
            calls = context.client.get(_calls_url(context, connection["id"]), headers=_auth(context))
            dropped = next(call for call in calls.json()["items"] if call["event_id"] == "evt-1")
            assert_that(dropped["status"], equal_to("DEAD_LETTERED"))
            assert_that(dropped["last_error_code"], equal_to("BACKLOG_CAP_EXCEEDED"))
            assert_that(dropped["last_error_message"], contains_string("Too many events were waiting"))


def test_the_newest_event_is_never_the_one_dropped() -> None:
    with given(_GIVEN_STOPPED) as context:
        connection = _create_webhook_connection(context)
        connection_id = UUID(connection["id"])
        deliveries = context.injector.get(CommunicationDeliveryRepository)

        with when("two events arrive at a webhook that keeps only one waiting"):
            for event_id in ("evt-1", "evt-2"):
                deliveries.accept_inbound(
                    connection_id=connection_id,
                    envelope=_event_envelope(event_id),
                    limits=_small_backlog(1),
                )

        with then("the older one goes and the one just accepted stays"):
            older, newer = _deliveries(context)
            assert_that(older.status, equal_to(CommunicationDeliveryStatus.DEAD_LETTERED))
            assert_that(newer.status, equal_to(CommunicationDeliveryStatus.PENDING))


def test_a_chat_backlog_is_never_dropped_by_the_event_cap() -> None:
    with given(_GIVEN) as context:
        chat_connection_id = _create_chat_connection(context)
        deliveries = context.injector.get(CommunicationDeliveryRepository)

        with when("more chat messages wait than an event backlog would be allowed"):
            for message_id in ("chat-1", "chat-2", "chat-3"):
                deliveries.accept_inbound(
                    connection_id=chat_connection_id,
                    envelope=_chat_envelope(message_id),
                    limits=_small_backlog(1),
                )

        with then("every one of them is still waiting"):
            statuses = [row.status for row in _deliveries(context)]
            assert_that(statuses, equal_to([CommunicationDeliveryStatus.PENDING] * 3))


def test_queued_events_end_when_their_agent_is_deleted() -> None:
    with given(_GIVEN_STOPPED) as context:
        connection = _create_webhook_connection(context)
        _fire_events(context, connection, 2)

        with when("the agent is deleted while they wait"):
            response = context.client.delete(
                f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}",
                headers=_auth(context),
            )

        with then("nothing is left waiting for an agent that no longer exists"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            rows = _deliveries(context)
            assert_that(rows, has_length(2))
            for row in rows:
                assert_that(row.status, equal_to(CommunicationDeliveryStatus.CANCELLED))
                assert_that(row.last_error_code, equal_to("CONNECTION_RETIRED"))


def test_queued_events_end_when_their_webhook_is_removed() -> None:
    with given(_GIVEN_STOPPED) as context:
        connection = _create_webhook_connection(context)
        _fire_events(context, connection, 2)

        with when("the webhook is removed while they wait"):
            response = context.client.delete(
                f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}"
                f"/connections/{connection['id']}?revision={connection['revision']}",
                headers=_auth(context),
            )

        with then("nothing is left waiting on a webhook that no longer exists"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            rows = _deliveries(context)
            assert_that(rows, has_length(2))
            for row in rows:
                assert_that(row.status, equal_to(CommunicationDeliveryStatus.CANCELLED))


def test_an_event_whose_run_reports_failure_runs_exactly_once() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        _fire_events(context, connection, 1)
        claimed = _claim(context).json()

        # A timeout is classified as retryable, so it is the kind of failure chat retries five times.
        # An unrecognised error would be final for any delivery and would not show the new cap at work.
        with when("the run reports that it failed with a transient-looking error"):
            response = _complete(context, claimed["delivery_id"], succeeded=False, error_code="TimeoutError")

        with then("the event is final after one attempt, and the reason is kept"):
            assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            [delivery] = _deliveries(context)
            assert_that(delivery.status, equal_to(CommunicationDeliveryStatus.DEAD_LETTERED))
            assert_that(delivery.attempt_count, equal_to(1))
            assert_that(delivery.completed_at, is_(not_(None)))
            assert_that(delivery.last_error_code, is_(not_(None)))

        with then("no second run is ever handed out"):
            _clear_backoff(context, claimed["delivery_id"])
            assert_that(_claim(context).status_code, equal_to(status.HTTP_204_NO_CONTENT))

        with then("the caller can read the reason afterwards"):
            calls = context.client.get(_calls_url(context, connection["id"]), headers=_auth(context))
            [call] = calls.json()["items"]
            assert_that(call["status"], equal_to("DEAD_LETTERED"))
            assert_that(call["last_error_code"], equal_to(delivery.last_error_code))


def test_an_event_whose_pod_dies_is_run_again_and_ends_after_two_attempts() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        _fire_events(context, connection, 1)
        first = _claim(context).json()

        with when("the pod dies mid-run and the claim's lease runs out"):
            _expire_lease(context, first["delivery_id"])
            reclaim = _claim(context)

        with then("the event is waiting again, with one attempt used and the cause recorded"):
            assert_that(reclaim.status_code, equal_to(status.HTTP_204_NO_CONTENT))
            [delivery] = _deliveries(context)
            assert_that(delivery.status, equal_to(CommunicationDeliveryStatus.PENDING))
            assert_that(delivery.attempt_count, equal_to(1))
            assert_that(delivery.last_error_code, equal_to("LEASE_EXPIRED"))

        with when("a healthy pod takes it and that pod dies too"):
            _clear_backoff(context, first["delivery_id"])
            second = _claim(context)
            _expire_lease(context, first["delivery_id"])
            _claim(context)

        with then("it ends after two attempts, and the reason reads as written"):
            assert_that(second.status_code, equal_to(status.HTTP_200_OK))
            assert_that(second.json()["attempt_count"], equal_to(2))
            [delivery] = _deliveries(context)
            assert_that(delivery.status, equal_to(CommunicationDeliveryStatus.DEAD_LETTERED))
            assert_that(delivery.attempt_count, equal_to(2))
            assert_that(delivery.last_error_code, equal_to("LEASE_EXPIRED"))
            assert_that(delivery.last_error_message or "", contains_string("claim lease expired"))


def test_an_agent_at_its_cap_claims_no_further_events_until_a_run_finishes() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        _fire_events(context, connection, 4)

        with when("the agent asks for work until it is told there is none"):
            claims = [_claim(context) for _ in range(4)]

        with then("it holds three runs, and the fourth event is left waiting untouched"):
            codes = [response.status_code for response in claims]
            assert_that(codes, equal_to([200, 200, 200, 204]))
            [waiting] = [row for row in _deliveries(context) if row.status == CommunicationDeliveryStatus.PENDING]
            assert_that(waiting.attempt_count, equal_to(0))
            assert_that(waiting.envelope["provider_message_id"], equal_to("evt-4"))

        with when("one run finishes"):
            _complete(context, claims[0].json()["delivery_id"], succeeded=True)
            next_claim = _claim(context)

        with then("the waiting event is handed out"):
            assert_that(next_claim.status_code, equal_to(status.HTTP_200_OK))
            assert_that(next_claim.json()["envelope"]["provider_message_id"], equal_to("evt-4"))


def test_chat_is_still_handed_out_when_events_hold_every_slot() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        chat_connection_id = _create_chat_connection(context)
        deliveries = context.injector.get(CommunicationDeliveryRepository)
        _fire_events(context, connection, 3)
        for _ in range(3):
            assert_that(_claim(context).status_code, equal_to(status.HTTP_200_OK))
        _fire_events(context, connection, 1, prefix="late")
        deliveries.accept_inbound(connection_id=chat_connection_id, envelope=_chat_envelope("chat-1"))

        with when("the agent asks for more work with every event slot taken"):
            chat = _claim(context)
            after = _claim(context)

        with then("it is handed the chat message, and the extra event keeps waiting"):
            assert_that(chat.status_code, equal_to(status.HTTP_200_OK))
            assert_that(chat.json()["kind"], equal_to("CONVERSATION"))
            assert_that(after.status_code, equal_to(status.HTTP_204_NO_CONTENT))


def test_a_chat_run_in_flight_does_not_use_up_an_event_slot() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        chat_connection_id = _create_chat_connection(context)
        deliveries = context.injector.get(CommunicationDeliveryRepository)
        _fire_events(context, connection, 2)
        for _ in range(2):
            _claim(context)
        deliveries.accept_inbound(connection_id=chat_connection_id, envelope=_chat_envelope("chat-1"))
        assert_that(_claim(context).json()["kind"], equal_to("CONVERSATION"))

        with when("a third and a fourth event arrive while the chat run is going"):
            _fire_events(context, connection, 2, prefix="more")
            third = _claim(context)
            fourth = _claim(context)

        with then("three events run beside the chat run, and only the fourth is held"):
            assert_that(third.status_code, equal_to(status.HTTP_200_OK))
            assert_that(third.json()["kind"], equal_to("EVENT"))
            assert_that(fourth.status_code, equal_to(status.HTTP_204_NO_CONTENT))


def test_a_burst_larger_than_the_cap_is_fully_processed_without_ever_exceeding_it() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        _fire_events(context, connection, 7)
        finished = 0

        with when("the agent works through the burst, claiming as much as it may each time"):
            for _ in range(10):
                in_flight: list[str] = []
                while (response := _claim(context)).status_code == status.HTTP_200_OK:
                    in_flight.append(response.json()["delivery_id"])
                processing = [
                    row for row in _deliveries(context) if row.status == CommunicationDeliveryStatus.PROCESSING
                ]
                assert_that(len(processing), less_than_or_equal_to(3))
                for delivery_id in in_flight:
                    _complete(context, delivery_id, succeeded=True)
                    finished += 1
                if finished == 7:
                    break

        with then("every event ran, just not all at once"):
            assert_that(finished, equal_to(7))
            statuses = {row.status for row in _deliveries(context)}
            assert_that(statuses, equal_to({CommunicationDeliveryStatus.SUCCEEDED}))


def _run_load_url(context, agent_id: UUID | str | None = None) -> str:
    return f"/api/v1/organizations/{context.organization.id}/agents/{agent_id or context.agent.id}/connection-runs"


def test_the_run_load_reports_event_runs_against_the_cap() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        chat_connection_id = _create_chat_connection(context)
        deliveries = context.injector.get(CommunicationDeliveryRepository)
        _fire_events(context, connection, 5)
        for _ in range(2):
            _claim(context)
        deliveries.accept_inbound(connection_id=chat_connection_id, envelope=_chat_envelope("chat-1"))

        with when("the agent's run load is read"):
            response = context.client.get(_run_load_url(context), headers=_auth(context))

        with then("it counts event runs only: two running, three waiting, against a cap of three"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            assert_that(response.json(), equal_to({"in_flight": 2, "max_in_flight": 3, "queued": 3}))


def test_the_run_load_of_an_unknown_agent_is_not_found() -> None:
    with given(_GIVEN) as context:
        response = context.client.get(_run_load_url(context, uuid4()), headers=_auth(context))

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))

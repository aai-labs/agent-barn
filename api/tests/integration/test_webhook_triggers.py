"""End to end: an external system triggers an Agent over HTTP with no human involved.

These cover what a user can actually do when this ships -- point Jira automation at a
URL, copy the secret shown once, and have the Agent run the job named in the caller's
own prompt -- plus the contract guarantees a machine caller depends on: dedupe,
ordering, and never being told a job ran when it did not.
"""

import hashlib
import hmac
import json
from typing import Any
from uuid import UUID

from fastapi import status
from hamcrest import assert_that, contains_string, equal_to, has_length, is_, not_
from sqlmodel import Session, col, select

from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.communications.models import (
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationDirection,
    DeliveryKind,
)
from api.domains.communications.plugins.webhook import SIGNATURE_HEADER, VERSION_HEADER
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


def test_the_claimed_delivery_carries_the_callers_prompt_unchanged() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        secret = connection["credential_reveal"]["signing_secret"]
        _fire(context, connection["id"], secret)

        with when("the agent claims its pending delivery"):
            response = context.communications_client.post(
                f"/communications/v1/agents/{context.agent.id}/deliveries/claim",
                headers=_runtime_auth(context),
            )

        with then("the runtime is told exactly what the caller asked for"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            delivery = response.json()
            assert_that(delivery["kind"], equal_to("EVENT"))
            assert_that(delivery["envelope"]["text"], equal_to(PROMPT))
            assert_that(delivery["progress_updates"], is_(False))
            execution = delivery["execution"]
            assert_that(execution["resume_session"], is_(False))
            assert_that(execution["approvals_enabled"], is_(False))
            assert_that(execution["busy_releases"], is_(True))
            assert_that(execution["busy_notice"], is_(None))
            # An event has no conversation to reply into.
            assert_that(execution["session_key"].startswith("connection:"), is_(False))


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


def test_the_event_is_recorded_as_a_machine_event_but_not_surfaced_as_a_conversation() -> None:
    """The agent_chat_message row is still written -- CommunicationDelivery.message_id
    is NOT NULL, and platform activity stats read this table directly -- but a webhook
    call is no longer a conversation view concept (AF-320 revision): it belongs on the
    webhook's own calls list instead. See test_conversations.py for the list-channels
    side of this."""
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

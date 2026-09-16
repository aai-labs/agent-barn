"""End to end: an external system triggers an Agent over HTTP with no human involved.

These cover what a user can actually do when this ships -- point Jira automation at a
URL and have the Agent run a named job -- plus the contract guarantees a machine caller
depends on: dedupe, ordering, and never being told a job ran when it did not.
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

SECRET = "w" * 40
PROMPT = "Write release notes for {{ payload.issue.key }}."

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


def _create_webhook_connection(context, *, auth_mode: str = "hmac", prompt_template: str = PROMPT) -> dict[str, Any]:
    response = context.client.post(
        f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections",
        json={
            "platform_key": "webhook",
            "display_name": "Jira automation",
            "settings": {"prompt_template": prompt_template},
            "credentials": {"auth_mode": auth_mode, "secret": SECRET},
        },
        headers=_auth(context),
    )
    assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
    return response.json()


def _body(event_id: str = "evt-1", **overrides) -> dict:
    return {"event_id": event_id, "payload": {"issue": {"key": "PROJ-1"}}, **overrides}


def _fire(context, connection_id: str, body: dict | None = None, *, auth_mode: str = "hmac", version: str = "1"):
    payload = _body() if body is None else body
    raw = json.dumps(payload).encode()
    headers = {VERSION_HEADER: version}
    if auth_mode == "hmac":
        headers[SIGNATURE_HEADER] = "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest()
    else:
        headers["Authorization"] = f"Bearer {SECRET}"
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


def test_a_user_gets_a_url_to_paste_into_the_calling_system() -> None:
    with given(_GIVEN) as context:
        with when("a user adds a webhook trigger to their agent"):
            connection = _create_webhook_connection(context)

        with then("the connection shows where the caller should send events"):
            assert_that(
                connection["webhook_url"],
                equal_to(f"https://api.agentbarn.test/communications/v1/webhooks/{connection['id']}"),
            )


def test_a_signed_event_makes_the_agent_run_the_job() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)

        with when("an external system posts a signed event"):
            response = _fire(context, connection["id"])

        with then("it is accepted for processing and queued as a machine event"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            [delivery] = _deliveries(context)
            assert_that(delivery.status, equal_to(CommunicationDeliveryStatus.PENDING))
            assert_that(delivery.kind, equal_to(DeliveryKind.EVENT))
            # The payload is stored with its shape intact, not flattened into prose.
            assert_that(delivery.envelope["payload"], equal_to({"issue": {"key": "PROJ-1"}}))


def test_the_claimed_delivery_carries_the_rendered_instruction_and_the_event_contract() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        _fire(context, connection["id"])

        with when("the agent claims its pending delivery"):
            response = context.communications_client.post(
                f"/communications/v1/agents/{context.agent.id}/deliveries/claim",
                headers=_runtime_auth(context),
            )

        with then("the runtime is told what to do and how to run it"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            delivery = response.json()
            assert_that(delivery["kind"], equal_to("EVENT"))
            assert_that(delivery["envelope"]["text"], contains_string("Write release notes for PROJ-1."))
            # Structure survives all the way to the runtime.
            assert_that(delivery["envelope"]["text"], contains_string('"key": "PROJ-1"'))
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
        _fire(context, connection["id"])

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

        with when("the caller sends the same event id twice"):
            first = _fire(context, connection["id"])
            second = _fire(context, connection["id"])

        with then("both are accepted but only one job exists"):
            assert_that(first.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(second.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(_deliveries(context), has_length(1))


def test_events_without_an_ordering_key_never_wait_for_each_other() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)

        with when("two unrelated events arrive"):
            _fire(context, connection["id"], _body("evt-1"))
            _fire(context, connection["id"], _body("evt-2"))

        with then("neither serialises against the other"):
            first, second = _deliveries(context)
            assert_that(first.ordering_key, not_(equal_to(second.ordering_key)))


def test_events_sharing_an_ordering_key_run_one_after_another() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)

        with when("two events declare the same ordering key on different subjects"):
            _fire(context, connection["id"], _body("evt-1", ordering_key="PROJ-1", subject="one"))
            _fire(context, connection["id"], _body("evt-2", ordering_key="PROJ-1", subject="two"))

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
        _fire(context, connection["id"])
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


def test_the_event_shows_in_the_conversation_marked_as_a_machine_event() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        _fire(context, connection["id"], _body(subject="PROJ-1"))

        with then("the transcript records it as an EVENT rather than a chat message"):
            delegate = context.injector.get(PostgresRepositoryDelegate)
            with Session(delegate.engine) as session:
                [message] = session.exec(select(AgentChatMessage)).all()
            assert_that(message.conversation_type, equal_to(ConversationType.EVENT))
            assert_that(message.channel_id, equal_to("PROJ-1"))


def test_a_wrong_secret_is_rejected() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context, auth_mode="bearer")

        with when("a caller uses the wrong token"):
            response = context.communications_client.post(
                f"/communications/v1/webhooks/{connection['id']}",
                content=json.dumps(_body()).encode(),
                headers={VERSION_HEADER: "1", "Authorization": "Bearer wrong", "Content-Type": "application/json"},
            )

        with then("it is refused and nothing is queued"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
            assert_that(_deliveries(context), has_length(0))


def test_a_body_altered_after_signing_is_rejected() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        signed = json.dumps(_body()).encode()
        signature = "sha256=" + hmac.new(SECRET.encode(), signed, hashlib.sha256).hexdigest()

        with when("the body is changed but the signature is kept"):
            response = context.communications_client.post(
                f"/communications/v1/webhooks/{connection['id']}",
                content=json.dumps(_body("evt-tampered")).encode(),
                headers={
                    VERSION_HEADER: "1",
                    SIGNATURE_HEADER: signature,
                    "Authorization": "",
                    "Content-Type": "application/json",
                },
            )

        with then("it is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
            assert_that(_deliveries(context), has_length(0))


def test_an_unsupported_contract_version_says_so() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)

        with when("a caller sends a version this server does not speak"):
            response = _fire(context, connection["id"], version="99")

        with then("it is a clear rejection, not a silent accept"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("Unsupported webhook contract version"))


def test_a_body_that_is_not_json_is_rejected() -> None:
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)

        with when("the caller sends something that is not JSON"):
            response = context.communications_client.post(
                f"/communications/v1/webhooks/{connection['id']}",
                content=b"not json at all",
                headers={VERSION_HEADER: "1", "Authorization": "", "Content-Type": "application/json"},
            )

        with then("it is a 400 naming the problem"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


def test_an_event_missing_its_id_is_told_why() -> None:
    """A machine caller cannot read a 202 and work out that nothing happened."""
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)

        with when("the caller omits event_id"):
            response = _fire(context, connection["id"], {"payload": {"a": 1}})

        with then("the reason comes back"):
            assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
            assert_that(response.json()["detail"], contains_string("event_id is required"))


def test_an_unknown_connection_is_not_a_probe_oracle() -> None:
    with given(_GIVEN) as context:
        with when("someone posts to a connection id that does not exist"):
            response = _fire(context, str(UUID(int=0)))

        with then("it looks exactly like a failed authentication"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_the_event_appears_in_the_conversations_list_as_its_own_kind() -> None:
    """The operator view is where a user checks what their trigger actually did. Events
    share the Agent's one inbox, but the UI has to be able to tell them apart."""
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        _fire(context, connection["id"], _body(subject="PROJ-1"))

        with when("the dashboard lists this agent's conversations"):
            response = context.client.get(
                f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/conversations/channels",
                headers=_auth(context),
            )

        with then("the event is listed and labelled as an event"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            [channel] = response.json()
            assert_that(channel["conversation_type"], equal_to("EVENT"))
            assert_that(channel["channel_id"], equal_to("PROJ-1"))
            assert_that(channel["platform_key"], equal_to("webhook"))


def test_a_signature_only_caller_needs_no_authorization_header() -> None:
    """A system that signs its body has nothing to put in Authorization. Requiring one
    would reject every HMAC caller with a 422 before any plugin saw the request."""
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        raw = json.dumps(_body()).encode()

        with when("the caller sends only a signature"):
            response = context.communications_client.post(
                f"/communications/v1/webhooks/{connection['id']}",
                content=raw,
                headers={
                    VERSION_HEADER: "1",
                    SIGNATURE_HEADER: "sha256=" + hmac.new(SECRET.encode(), raw, hashlib.sha256).hexdigest(),
                    "Content-Type": "application/json",
                },
            )

        with then("it is accepted"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(_deliveries(context), has_length(1))


def test_a_reply_inherits_the_contract_and_the_thread_of_what_it_answers() -> None:
    """Both halves of one exchange must agree. Nothing reads either field on an outbound
    row today, which is exactly why a wrong value here would go unnoticed until the
    reply path is built on top of it."""
    with given(_GIVEN) as context:
        connection = _create_webhook_connection(context)
        _fire(context, connection["id"], _body(subject="PROJ-1"))
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
            inbound, outbound = _deliveries(context)[0], None
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

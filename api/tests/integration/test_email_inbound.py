from typing import Any
from uuid import UUID

from fastapi import status
from hamcrest import assert_that, empty, equal_to, has_length, is_, not_
from sqlmodel import Session, col, select

from api.domains.agents.models import AgentStatus
from api.domains.communications.models import (
    CommunicationDelivery,
    CommunicationDeliveryStatus,
    CommunicationDirection,
)
from api.domains.conversations.models import AgentChatMessage
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

INBOUND_SECRET = "inbound-secret"
INBOUND_PATH = "/communications/v1/webhooks/email/inbound"
CUSTOMER = "jane@acme.test"
MESSAGE_ID = "<abc123@acme.test>"

_GIVEN = [
    set_env_variable(
        {
            "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
            "LITELLM_BASE_URL": "http://litellm:4000",
            "LITELLM_SECRET_NAME": "litellm",
            "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
            "AGENT_LITELLM_BASE_URL": "http://litellm:4000",
            "AGENT_EMAIL_DOMAIN": "agents.agentbarn.test",
            "EMAIL_INBOUND_SECRET": INBOUND_SECRET,
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


def _create_email_connection(context, allowed_senders: list[str] | None = None) -> str:
    response = context.client.post(
        f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections",
        json={
            "platform_key": "email",
            "display_name": "Email",
            "settings": {
                "sender_policy": "allowlist",
                "allowed_senders": allowed_senders if allowed_senders is not None else [CUSTOMER],
            },
            "credentials": {},
        },
        headers=_auth(context),
    )
    assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
    return response.json()["managed_address"]


def _payload(to: str, **overrides) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "to": to,
        "from": CUSTOMER,
        "from_name": "Jane Customer",
        "subject": "Question about pricing",
        "text": "What does the team plan cost?",
        "message_id": MESSAGE_ID,
        "in_reply_to": "",
        "references": [],
        "auto_submitted": "",
        "precedence": "",
        "list_id": "",
        "received_at": "2026-08-31T10:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def _post(context, payload: dict[str, Any], secret: str = INBOUND_SECRET):
    return context.communications_client.post(
        INBOUND_PATH,
        json=payload,
        headers={"Authorization": f"Bearer {secret}"},
    )


def _deliveries(context) -> list[CommunicationDelivery]:
    delegate = context.injector.get(PostgresRepositoryDelegate)
    with Session(delegate.engine) as session:
        return list(
            session.exec(
                select(CommunicationDelivery).where(
                    col(CommunicationDelivery.direction) == CommunicationDirection.INBOUND
                )
            ).all()
        )


def test_mail_to_an_agent_address_becomes_a_pending_delivery() -> None:
    with given(_GIVEN) as context:
        address = _create_email_connection(context)

        with when("the inbound worker posts a parsed message"):
            response = _post(context, _payload(address))

        with then("it is accepted and queued for the running agent"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            [delivery] = _deliveries(context)
            assert_that(delivery.status, equal_to(CommunicationDeliveryStatus.PENDING))
            assert_that(delivery.idempotency_key, equal_to(MESSAGE_ID))


def test_the_stored_message_is_located_on_the_sender_and_carries_the_subject() -> None:
    with given(_GIVEN) as context:
        address = _create_email_connection(context)

        with when("the inbound worker posts a parsed message"):
            _post(context, _payload(address))

        with then("the conversation is the correspondent, and the agent can see who wrote and why"):
            delegate = context.injector.get(PostgresRepositoryDelegate)
            with Session(delegate.engine) as session:
                [message] = session.exec(select(AgentChatMessage)).all()
            assert_that(message.channel_id, equal_to(CUSTOMER))
            assert_that(message.sender_id, equal_to(CUSTOMER))
            assert_that("Question about pricing" in message.content, is_(True))
            assert_that("Jane Customer" in message.content, is_(True))


def test_a_wrong_shared_secret_is_rejected() -> None:
    with given(_GIVEN) as context:
        address = _create_email_connection(context)

        with when("the request presents the wrong secret"):
            response = _post(context, _payload(address), secret="not-the-secret")

        with then("it is unauthorized and nothing is stored"):
            assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
            assert_that(_deliveries(context), is_(empty()))


def test_a_missing_authorization_header_is_rejected() -> None:
    with given(_GIVEN) as context:
        _create_email_connection(context)

        with when("the request carries no credential at all"):
            response = context.communications_client.post(INBOUND_PATH, json=_payload("whatever@x.test"))

        with then("the route refuses it"):
            assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_mail_to_an_unknown_address_is_accepted_without_revealing_that_it_is_unknown() -> None:
    with given(_GIVEN) as context:
        _create_email_connection(context)

        with when("mail arrives for an address that was never allocated"):
            response = _post(context, _payload("agent+nobody-0000@agents.agentbarn.test"))

        with then("the worker sees the same 202 as a delivered message, and nothing is stored"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(response.json()["accepted"], is_(empty()))
            assert_that(_deliveries(context), is_(empty()))


def test_mail_to_a_released_address_no_longer_reaches_the_agent() -> None:
    with given(_GIVEN) as context:
        address = _create_email_connection(context)
        connections = context.client.get(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections",
            headers=_auth(context),
        ).json()
        connection = next(item for item in connections if item["platform_key"] == "email")
        context.client.delete(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}"
            f"/connections/{connection['id']}?revision={connection['revision']}",
            headers=_auth(context),
        )

        with when("mail arrives for the retired connection's address"):
            response = _post(context, _payload(address))

        with then("it is silently dropped"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(_deliveries(context), is_(empty()))


def test_a_retried_message_creates_one_delivery() -> None:
    with given(_GIVEN) as context:
        address = _create_email_connection(context)

        with when("the worker delivers the same message twice"):
            first = _post(context, _payload(address))
            second = _post(context, _payload(address))

        with then("the second is recognised as a duplicate of the first"):
            assert_that(_deliveries(context), has_length(1))
            first_accepted = first.json()["accepted"][0]
            second_accepted = second.json()["accepted"][0]
            assert_that(second_accepted["delivery_id"], equal_to(first_accepted["delivery_id"]))
            assert_that(second_accepted["duplicate"], is_(True))


def test_a_sender_outside_the_allowlist_is_dropped_before_persistence() -> None:
    with given(_GIVEN) as context:
        address = _create_email_connection(context, allowed_senders=["@trusted.test"])

        with when("an unlisted sender writes in"):
            response = _post(context, _payload(address))

        with then("nothing is stored"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(_deliveries(context), is_(empty()))


def test_automated_mail_is_dropped_before_persistence() -> None:
    with given(_GIVEN) as context:
        address = _create_email_connection(context)

        with when("an out-of-office autoresponder replies"):
            response = _post(context, _payload(address, auto_submitted="auto-replied"))

        with then("the loop is refused"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(_deliveries(context), is_(empty()))


def test_the_address_resolves_regardless_of_the_case_the_sender_typed() -> None:
    with given(_GIVEN) as context:
        address = _create_email_connection(context)

        with when("the recipient address arrives upper-cased"):
            response = _post(context, _payload(address.upper()))

        with then("it still reaches the agent"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(_deliveries(context), has_length(1))


def test_mail_for_another_agents_address_never_reaches_this_one() -> None:
    with given(_GIVEN) as context:
        address = _create_email_connection(context)
        other_local_part = address.split("+")[1].split("@")[0]

        with when("a near-miss local part arrives"):
            response = _post(context, _payload(f"agent+{other_local_part}x@agents.agentbarn.test"))

        with then("no delivery is created for the real address"):
            assert_that(response.status_code, equal_to(status.HTTP_202_ACCEPTED))
            assert_that(_deliveries(context), is_(empty()))


def test_a_delivery_is_bound_to_the_connection_that_owns_the_address() -> None:
    with given(_GIVEN) as context:
        address = _create_email_connection(context)
        connections = context.client.get(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections",
            headers=_auth(context),
        ).json()
        connection_id = UUID(next(item for item in connections if item["platform_key"] == "email")["id"])

        with when("mail arrives"):
            _post(context, _payload(address))

        with then("the delivery is attributed to that connection and agent"):
            [delivery] = _deliveries(context)
            assert_that(delivery.connection_id, equal_to(connection_id))
            assert_that(delivery.agent_id, equal_to(context.agent.id))
            assert_that(delivery.organization_id, equal_to(context.organization.id))
            assert_that(delivery.envelope, is_(not_(equal_to({}))))

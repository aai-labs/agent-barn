from datetime import UTC, datetime
from uuid import UUID

from hamcrest import assert_that, equal_to, is_, none, not_
from starlette.testclient import TestClient

from api.domains.agents.models import AgentStatus
from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.models import (
    CommunicationDeliveryStatus,
    CommunicationSender,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
)
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


def _create_connection(context, bot_token: str = "gateway-token") -> UUID:
    client: TestClient = context.client
    response = client.post(
        f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections",
        json={
            "platform_key": "discord",
            "display_name": "Gateway Discord",
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

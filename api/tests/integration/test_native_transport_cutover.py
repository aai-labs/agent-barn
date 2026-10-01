from datetime import UTC, datetime, timedelta

import pytest
from hamcrest import assert_that, equal_to, has_length
from sqlmodel import Session

from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.models import CommunicationDelivery, CommunicationDeliveryStatus
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.agent_messages import STEPS, change_connection, messaging_ready, rows
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, there_is_an_agent, there_is_an_agent_in_another_org
from api.tests.steps.communication import there_is_an_inbound_delivery, there_is_an_outbound_delivery


@pytest.mark.parametrize("platform_key", ["slack", "discord", "telegram", "teams"])
def test_retired_driver_ingress_is_absent(platform_key: str) -> None:
    with given([*STEPS, messaging_ready]) as context:
        change_connection(
            context,
            platform_key=platform_key,
        )
        url = f"/communications/v1/connections/{context.connection.id}/events"
        with when("a legacy driver submits an event with invalid and valid credentials"):
            invalid = context.communications_client.post(
                url, json={}, headers={"Authorization": "Bearer wrong", "X-AgentBarn-Driver-Version": "1"}
            )
            valid = context.communications_client.post(
                url, json={}, headers={"Authorization": "Bearer legacy-driver", "X-AgentBarn-Driver-Version": "1"}
            )
        with then("the route is absent and the event cannot create gateway work"):
            assert_that(invalid.status_code, equal_to(404))
            assert_that(valid.status_code, equal_to(404))
            for records in rows(context):
                assert_that(records, has_length(0))


def test_native_historical_execution_cannot_reply_complete_renew_or_be_reclaimed() -> None:
    with given([*STEPS, messaging_ready]) as context:
        repository = context.injector.get(CommunicationDeliveryRepository)
        there_is_an_inbound_delivery()(context)
        delegate = context.injector.get(PostgresRepositoryDelegate)
        expired_at = datetime.now(UTC) - timedelta(minutes=1)
        with Session(delegate.engine) as session:
            delivery = session.get(CommunicationDelivery, context.delivery_id)
            if delivery is None:
                raise AssertionError("Historical delivery was not persisted")
            delivery.status = CommunicationDeliveryStatus.PROCESSING
            delivery.attempt_count = 1
            delivery.lease_expires_at = expired_at
            session.add(delivery)
            session.commit()

        url = f"/communications/v1/agents/{context.agent.id}/deliveries/{context.delivery_id}"
        with when("a stale runtime sends callbacks and the gateway tries to reclaim its expired lease"):
            reply = context.communications_client.post(
                f"{url}/replies",
                json={"idempotency_key": "late-reply", "text": "late output"},
                headers=context.runtime_headers,
            )
            complete = context.communications_client.post(
                f"{url}/complete",
                json={"succeeded": True},
                headers=context.runtime_headers,
            )
            renew = context.communications_client.post(f"{url}/renew", headers=context.runtime_headers)
            reclaimed = repository.reclaim_expired_inbound(agent_id=context.agent.id)
            claimed = repository.claim_next_inbound(agent_id=context.agent.id)

        with then("the historical execution remains unchanged and creates no reply"):
            assert_that(reply.status_code, equal_to(409))
            assert_that(complete.status_code, equal_to(404))
            assert_that(renew.status_code, equal_to(404))
            assert_that(reclaimed, equal_to([]))
            assert_that(claimed, equal_to(None))
            deliveries, messages, journal = rows(context)
            assert_that(deliveries, has_length(1))
            assert_that(messages, has_length(1))
            assert_that(journal, has_length(1))
            assert_that(deliveries[0].status, equal_to(CommunicationDeliveryStatus.PROCESSING))
            assert_that(deliveries[0].lease_expires_at, equal_to(expired_at))


@pytest.mark.parametrize("platform_key", ["slack", "discord", "telegram", "teams"])
def test_native_expired_outbound_lease_is_never_reclaimed(platform_key: str) -> None:
    with given([*STEPS, messaging_ready]) as context:
        change_connection(context, platform_key=platform_key)
        there_is_an_outbound_delivery(status=CommunicationDeliveryStatus.PROCESSING)(context)
        expired_at = datetime.now(UTC) - timedelta(minutes=1)
        delegate = context.injector.get(PostgresRepositoryDelegate)
        with Session(delegate.engine) as session:
            delivery = session.get(CommunicationDelivery, context.outbound_delivery_id)
            if delivery is None:
                raise AssertionError("Historical outbound delivery was not persisted")
            delivery.lease_expires_at = expired_at
            session.add(delivery)
            session.commit()

        with when("the gateway looks for outbound work without a native exclusion argument"):
            repository = context.injector.get(CommunicationDeliveryRepository)
            claimed = repository.claim_next_outbound()
            completed = repository.complete_outbound(context.outbound_delivery_id, provider_message_id="stale-send")
        with then("the historical lease and status stay unchanged"):
            assert_that(claimed, equal_to(None))
            assert_that(completed, equal_to(False))
            deliveries, messages, journal = rows(context)
            assert_that(journal, has_length(0))
            assert_that(messages, has_length(1))
            assert_that(deliveries[0].status, equal_to(CommunicationDeliveryStatus.PROCESSING))
            assert_that(deliveries[0].lease_expires_at, equal_to(expired_at))


@pytest.mark.parametrize("cross_organization", [False, True])
def test_native_reply_does_not_reveal_a_different_agents_historical_execution(cross_organization: bool) -> None:
    with given([*STEPS, messaging_ready]) as context:
        there_is_an_inbound_delivery()(context)
        source_id = context.delivery_id
        (there_is_an_agent_in_another_org() if cross_organization else there_is_an_agent())(context)
        context.agent.communication_key_encrypted = encrypt_token("other-runtime", TEST_ENCRYPTION_KEY)
        context.injector.get(PostgresRepositoryDelegate).save(context.agent)
        url = f"/communications/v1/agents/{context.agent.id}/deliveries/{source_id}/replies"

        with when("another authenticated Agent sends a callback for the historical source"):
            response = context.communications_client.post(
                url,
                json={"idempotency_key": "foreign-reply", "text": "output"},
                headers={"Authorization": "Bearer other-runtime", "X-AgentBarn-Communications-Version": "2"},
            )
        with then("the source is concealed before its transport ownership is disclosed"):
            assert_that(response.status_code, equal_to(404))

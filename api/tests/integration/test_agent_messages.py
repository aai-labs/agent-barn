from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest
from hamcrest import assert_that, contains_string, empty, equal_to, has_length, is_, not_
from pydantic import ValidationError
from sqlalchemy.exc import IntegrityError

from api.domains.communications.delivery_repository import CommunicationDeliveryRepository
from api.domains.communications.gateway_service import CommunicationsGatewayService
from api.domains.communications.models import (
    AgentMessageCreate,
    CommunicationConnection,
    CommunicationDirection,
    CommunicationJournalStage,
    CommunicationSender,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.tests.core.givenpy import given, then, when
from api.tests.helpers.agent_messages import (
    STEPS,
    agent_was_in_conversation,
    change_connection,
    messaging_ready,
    origin_request,
    receipt_id,
    rows,
    scheduled_request,
    second_slack_connection,
    submit,
)


def _conversation(channel):
    return {"id": channel, "name": "updates", "is_im": False}


@pytest.fixture(autouse=True)
def slack_lookup():
    with patch("api.domains.communications.plugins.slack.SlackClient.get_conversation", side_effect=_conversation):
        with patch("api.domains.communications.plugins.slack.SlackPlatformPlugin.processing_feedback"):
            yield


def test_scheduled_submission_atomically_records_history_delivery_and_content_free_journal():
    with given([*STEPS, messaging_ready]) as context:
        with when("a fresh scheduled execution submits without any inbound session"):
            receipt = submit(context, scheduled_request())
        with then("one durable delivery and canonical message exist"):
            delivery_id = receipt_id(receipt)
            deliveries, messages, journal = rows(context)
            assert_that(deliveries, has_length(1))
            assert_that(messages, has_length(1))
            assert_that(journal, has_length(1))
            assert_that(deliveries[0].id, equal_to(delivery_id))
            assert_that(deliveries[0].envelope["source_delivery_id"], is_(None))
            assert_that(str(journal[0].model_dump()), not_(contains_string("Scheduled result")))
        with then("diagnostics separate it from inbound work waiting on the Agent"):
            assert_that(journal[0].stage, equal_to(CommunicationJournalStage.INITIATED_QUEUED))
            assert_that(deliveries[0].direction, equal_to(CommunicationDirection.OUTBOUND))


def test_lost_acknowledgement_does_not_resolve_changed_or_disabled_default():
    with given([*STEPS, messaging_ready]) as context:
        first = receipt_id(submit(context, scheduled_request()))
        change_connection(context, enabled=False, settings={"channel_ids": ["C456"], "default_delivery_target": None})
        with when("the bridge retries after losing the acknowledgement"):
            retried = receipt_id(submit(context, scheduled_request()))
        with then("the accepted destination and identity remain fixed"):
            assert_that(retried, equal_to(first))
            assert_that(rows(context)[0][0].envelope["location"]["id"], equal_to("C123"))


def test_concurrent_submission_creates_one_canonical_message_and_delivery():
    with given([*STEPS, messaging_ready]) as context:
        with when("four clients concurrently retry one scheduled completion"):
            with ThreadPoolExecutor(max_workers=4) as pool:
                receipts = list(pool.map(lambda _: receipt_id(submit(context, scheduled_request())), range(4)))
        with then("every caller receives the same durable identity"):
            assert_that(len(set(receipts)), equal_to(1))
            assert_that(rows(context)[0], has_length(1))
            assert_that(rows(context)[1], has_length(1))


def test_same_key_with_changed_content_conflicts():
    with given([*STEPS, messaging_ready]) as context:
        receipt_id(submit(context, scheduled_request()))
        assert_that(submit(context, scheduled_request(text="Different result")).status_code, equal_to(409))
        assert_that(rows(context)[1], has_length(1))


@pytest.mark.parametrize(
    "settings,enabled",
    [
        ({}, True),
        ({"default_delivery_target": None}, True),
        ({"default_delivery_target": {"recipient": "C123"}, "channel_ids": ["C123"]}, False),
    ],
)
def test_missing_or_disabled_default_is_unavailable(settings, enabled):
    with given([*STEPS, messaging_ready]) as context:
        change_connection(context, settings=settings, enabled=enabled)
        assert_that(submit(context, scheduled_request()).status_code, equal_to(409))
        assert_that(rows(context)[0], has_length(0))


def test_disallowed_default_cannot_submit():
    with given([*STEPS, messaging_ready]) as context:
        change_connection(context, settings={"default_delivery_target": {"recipient": "C123"}, "channel_ids": []})
        assert_that(submit(context, scheduled_request()).status_code, equal_to(403))


def _interactive(context):
    gateway = context.injector.get(CommunicationsGatewayService)
    gateway.accept_inbound(
        context.connection.id,
        NormalizedCommunicationEnvelope(
            provider_message_id="incoming",
            occurred_at=datetime.now(UTC),
            location=ConversationLocation(id="C123", type="CHANNEL"),
            sender=CommunicationSender(id="U123"),
            text="Send an update",
        ),
    )
    delivery = gateway.claim_runtime_delivery(context.agent)
    return delivery, {
        "text": "Requested update",
        "idempotency_key": "tool-invocation-one",
        "destination": {"kind": "explicit", "target": {"recipient": "C456"}},
        "context": {"kind": "interactive", "execution_token": delivery.execution_token},
    }


def test_explicit_message_requires_active_uncancelled_claim():
    with given([*STEPS, messaging_ready]) as context:
        delivery, payload = _interactive(context)
        receipt_id(submit(context, payload))
        context.injector.get(CommunicationDeliveryRepository).request_cancel(
            delivery.delivery_id, agent_id=context.agent.id
        )
        payload["idempotency_key"] = "another-call"
        assert_that(submit(context, payload).status_code, equal_to(403))


@pytest.mark.parametrize("mutation,expected", [("token", 403), ("connection", 422), ("scheduled", 422)])
def test_explicit_send_rejects_untrusted_context_and_named_connections(mutation, expected):
    with given([*STEPS, messaging_ready]) as context:
        _, payload = _interactive(context)
        if mutation == "token":
            payload["context"]["execution_token"] = "user_directed"
        elif mutation == "connection":
            # Connection identity is not part of the contract, so naming one is malformed.
            payload["destination"]["connection_id"] = str(uuid4())
        else:
            payload["context"] = {"kind": "scheduled", "run_id": "invented"}
        assert_that(submit(context, payload).status_code, equal_to(expected))


def test_explicit_send_stays_on_the_conversation_connection():
    """An Agent can hold several Slack Connections; a send must not cross workspaces."""
    with given([*STEPS, messaging_ready]) as context:
        other = second_slack_connection(context)
        _, payload = _interactive(context)
        receipt = submit(context, payload)
        deliveries, _, _ = rows(context)
        outbound = [item for item in deliveries if item.id == receipt_id(receipt)]
        assert_that(outbound, has_length(1))
        assert_that(outbound[0].connection_id, equal_to(context.connection.id))
        assert_that(outbound[0].connection_id, not_(equal_to(other.id)))


def test_runtime_identity_requires_matching_credential():
    with given([*STEPS, messaging_ready]) as context:
        context.runtime_headers["Authorization"] = "Bearer wrong-key"
        assert_that(submit(context, scheduled_request()).status_code, equal_to(401))


def test_database_enforces_one_default_including_disabled_connections():
    with given([*STEPS, messaging_ready]) as context:
        other = CommunicationConnection(
            organization_id=context.connection.organization_id,
            agent_id=context.connection.agent_id,
            platform_key=context.connection.platform_key,
            display_name="Another",
            enabled=False,
            settings=dict(context.connection.settings),
            credentials_encrypted=context.connection.credentials_encrypted,
            driver_key_encrypted=context.connection.driver_key_encrypted,
        )
        with pytest.raises(IntegrityError):
            context.injector.get(PostgresRepositoryDelegate).save(other)


@pytest.mark.parametrize("disabled", [False, True])
def test_pending_send_obeys_current_policy_and_connection_availability(disabled):
    from api.domains.communications.processor import OutboundCommunicationProcessor

    with given([*STEPS, messaging_ready]) as context:
        receipt_id(submit(context, scheduled_request()))
        if disabled:
            change_connection(context, enabled=False)
        else:
            change_connection(context, settings={"channel_ids": [], "default_delivery_target": {"recipient": "C123"}})
        with patch("api.domains.communications.plugins.slack.SlackPlatformPlugin.send") as send:
            context.injector.get(OutboundCommunicationProcessor).process_one()
            assert_that(send.call_count, equal_to(0))
        assert_that(rows(context)[0][0].status, not_(equal_to("SUCCEEDED")))


def test_initiated_delivery_uses_existing_worker_without_inbound_feedback():
    from api.domains.communications.processor import OutboundCommunicationProcessor

    with given([*STEPS, messaging_ready]) as context:
        receipt_id(submit(context, scheduled_request()))
        with patch(
            "api.domains.communications.plugins.slack.SlackPlatformPlugin.send", return_value="provider-one"
        ) as send:
            with patch.object(CommunicationsGatewayService, "notify_processing_feedback") as feedback:
                assert_that(context.injector.get(OutboundCommunicationProcessor).process_one(), is_(True))
                assert_that(send.call_count, equal_to(1))
                assert_that(feedback.call_count, equal_to(0))
        assert_that(rows(context)[0][0].status, equal_to("SUCCEEDED"))


def test_foreign_agent_cannot_use_an_execution_token():
    from api.domains.communications.execution_context import issue_execution_token
    from api.tests.steps.agent import TEST_ENCRYPTION_KEY

    with given([*STEPS, messaging_ready]) as context:
        delivery, payload = _interactive(context)
        payload["context"]["execution_token"] = issue_execution_token(
            TEST_ENCRYPTION_KEY, uuid4(), delivery.delivery_id, delivery.attempt_count
        )
        assert_that(submit(context, payload).status_code, equal_to(403))


def test_setting_a_conflicting_default_returns_conflict_through_connection_editor_api():
    with given([*STEPS, messaging_ready]) as context:
        response = context.client.post(
            f"/api/v1/organizations/{context.organization.id}/agents/{context.agent.id}/connections",
            headers={"Authorization": f"Bearer {context.access_token}"},
            json={
                "platform_key": "slack",
                "display_name": "Second default",
                "enabled": False,
                "settings": {"channel_ids": ["C456"], "default_delivery_target": {"recipient": "C456"}},
                "credentials": {"bot_token": "another-bot", "app_token": "another-app"},
            },
        )
        assert_that(response.status_code, equal_to(409), response.text)


def test_scheduled_job_delivers_to_the_conversation_it_was_created_from():
    """The default points at C123; a job created in C456 must not follow the default."""
    with given([*STEPS, messaging_ready]) as context:
        agent_was_in_conversation(context, channel="C456")
        receipt = submit(context, origin_request(context, channel="C456"))
        deliveries, _, _ = rows(context)
        outbound = [item for item in deliveries if item.id == receipt_id(receipt)]
        assert_that(outbound, has_length(1))
        assert_that(outbound[0].envelope["location"]["id"], equal_to("C456"))
        assert_that(outbound[0].connection_id, equal_to(context.connection.id))


def test_scheduled_job_without_an_origin_still_uses_the_configured_default():
    with given([*STEPS, messaging_ready]) as context:
        receipt = submit(context, scheduled_request())
        deliveries, _, _ = rows(context)
        outbound = [item for item in deliveries if item.id == receipt_id(receipt)]
        assert_that(outbound[0].envelope["location"]["id"], equal_to("C123"))


def test_origin_on_a_second_workspace_is_not_pulled_to_the_default_workspace():
    with given([*STEPS, messaging_ready]) as context:
        other = second_slack_connection(context)
        agent_was_in_conversation(context, connection=other, channel="C456")
        receipt = submit(context, origin_request(context, connection=other, channel="C456"))
        deliveries, _, _ = rows(context)
        outbound = [item for item in deliveries if item.id == receipt_id(receipt)]
        assert_that(outbound[0].connection_id, equal_to(other.id))


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("foreign_connection", 409),
        ("unknown_conversation", 409),
        ("disallowed_channel", 403),
        ("retired_connection", 409),
    ],
)
def test_unverifiable_origin_is_rejected_and_never_diverted_to_the_default(mutation, expected):
    with given([*STEPS, messaging_ready]) as context:
        agent_was_in_conversation(context, channel="C456")
        payload = origin_request(context, channel="C456")
        if mutation == "foreign_connection":
            payload["destination"]["connection_id"] = str(uuid4())
        elif mutation == "unknown_conversation":
            payload["destination"]["channel_id"] = "C999"
        elif mutation == "disallowed_channel":
            change_connection(context, settings={"channel_ids": ["C123"], "default_delivery_target": None})
        else:
            change_connection(context, retired_at=datetime.now(UTC))
        assert_that(submit(context, payload).status_code, equal_to(expected))
        deliveries, _, _ = rows(context)
        assert_that(deliveries, empty())


@pytest.mark.parametrize(
    "context_kind,destination_kind,allowed",
    [
        # A scheduled run may reach its configured default or the conversation that
        # created it. It may never name a destination itself -- that is the whole
        # authorization boundary for work with no user in the loop.
        ("scheduled", "default", True),
        ("scheduled", "origin", True),
        ("scheduled", "explicit", False),
        # An interactive run has a live execution to authorize an explicit send, but
        # no job origin to inherit.
        ("interactive", "default", True),
        ("interactive", "explicit", True),
        ("interactive", "origin", False),
    ],
)
def test_only_the_allowed_destination_kinds_are_accepted_per_context(context_kind, destination_kind, allowed):
    destinations = {
        "default": {"kind": "default"},
        "explicit": {"kind": "explicit", "target": {"recipient": "C456"}},
        "origin": {
            "kind": "origin",
            "connection_id": str(uuid4()),
            "channel_id": "C456",
            "thread_id": None,
        },
    }
    contexts = {
        "scheduled": {"kind": "scheduled", "run_id": "hermes:run"},
        "interactive": {"kind": "interactive", "execution_token": "token"},
    }
    payload = {
        "text": "Scheduled result",
        "idempotency_key": "matrix",
        "destination": destinations[destination_kind],
        "context": contexts[context_kind],
    }
    if allowed:
        AgentMessageCreate.model_validate(payload)
    else:
        with pytest.raises(ValidationError):
            AgentMessageCreate.model_validate(payload)


def test_a_connection_id_is_not_part_of_the_explicit_contract():
    """Connection identity changes when an operator recreates a Connection, so it
    must never be something a prompt carries or a model can name."""
    with pytest.raises(ValidationError):
        AgentMessageCreate.model_validate(
            {
                "text": "hello",
                "idempotency_key": "k",
                "destination": {
                    "kind": "explicit",
                    "connection_id": str(uuid4()),
                    "target": {"recipient": "C456"},
                },
                "context": {"kind": "interactive", "execution_token": "token"},
            }
        )

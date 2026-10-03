from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest

from api.core.config import Config
from api.domains.communications.models import ConversationLocation, OutboundCommunicationEnvelope
from api.domains.communications.plugins.base import GatewayDeliveryPlugin
from api.domains.communications.plugins.email import EmailCredentials, EmailSettings
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.processor import OutboundCommunicationProcessor


def processor(platform_key="email", origin="reply", error=None):
    outbound = OutboundCommunicationEnvelope(
        origin=origin,
        execution_id="historical-run" if origin != "reply" else None,
        source_delivery_id=uuid4() if origin != "cron" else None,
        location=ConversationLocation(id="sender@example.test", type="DM"),
        text="reply",
        provider_metadata={"subject": "Subject"},
    )
    delivery = SimpleNamespace(
        id=uuid4(), connection_id=uuid4(), idempotency_key="reply-1", envelope=outbound.model_dump(mode="json")
    )
    deliveries = Mock()
    deliveries.claim_next_outbound.return_value = delivery
    connections = Mock()
    connections.get_active.return_value = SimpleNamespace(
        enabled=True,
        platform_key=platform_key,
        settings={},
        credentials_encrypted="ciphertext",
        agent_id=uuid4(),
    )
    agents = Mock()
    agents.get_by_id.return_value = SimpleNamespace(name="Tommy")
    plugin = Mock(spec=GatewayDeliveryPlugin)
    plugin.key = "email"
    plugin.schema_version = 1
    plugin.settings_model = EmailSettings
    plugin.credentials_model = EmailCredentials
    plugin.send.return_value = "provider-reply"
    plugin.send.side_effect = error
    worker = OutboundCommunicationProcessor(
        config=Config(agent_token_encryption_key="key"),
        deliveries=deliveries,
        connections=connections,
        agents=agents,
        plugins=PlatformPluginRegistry([plugin]),
    )
    return worker, deliveries, plugin, delivery


def test_provider_success_completes_with_stable_idempotency_and_current_agent_identity():
    worker, deliveries, plugin, delivery = processor()
    with patch("api.domains.communications.processor.decrypt_token", return_value="{}"):
        assert worker.process_one() is True
    deliveries.complete_outbound.assert_called_once_with(delivery.id, provider_message_id="provider-reply")
    sent = plugin.send.call_args.args[2]
    assert sent.provider_metadata == {"subject": "Subject", "agent_name": "Tommy"}
    assert plugin.send.call_args.kwargs == {"idempotency_key": "reply-1"}
    deliveries.claim_next_outbound.assert_called_once_with()


def test_provider_failure_is_normalized_for_durable_retry():
    worker, deliveries, _, delivery = processor(error=TimeoutError("provider timed out"))
    with patch("api.domains.communications.processor.decrypt_token", return_value="{}"):
        assert worker.process_one() is True
    assert deliveries.complete_outbound.call_args.args == (delivery.id,)
    assert deliveries.complete_outbound.call_args.kwargs["error_details"].operation == "send_message"


@pytest.mark.parametrize("platform_key", ["slack", "discord", "telegram", "teams"])
def test_native_claim_already_in_flight_cannot_reach_a_provider(platform_key):
    worker, deliveries, plugin, delivery = processor(platform_key=platform_key)
    with patch("api.domains.communications.processor.decrypt_token") as decrypt:
        assert worker.process_one() is True
    decrypt.assert_not_called()
    plugin.send.assert_not_called()
    assert deliveries.complete_outbound.call_args.args == (delivery.id,)


@pytest.mark.parametrize("origin", ["cron", "user_directed"])
def test_historical_initiated_gateway_work_is_rejected_before_provider_send(origin):
    worker, deliveries, plugin, delivery = processor(origin=origin)
    with patch("api.domains.communications.processor.decrypt_token", return_value="{}"):
        assert worker.process_one() is True
    plugin.send.assert_not_called()
    assert deliveries.complete_outbound.call_args.args == (delivery.id,)
    assert deliveries.complete_outbound.call_args.kwargs["error_details"].retryable is False


@pytest.mark.parametrize("origin", ["cron", "user_directed"])
def test_retired_initiated_work_does_not_consult_unavailable_dependencies(origin):
    worker, deliveries, plugin, delivery = processor(origin=origin)
    worker.connections.get_active.side_effect = TimeoutError("database unavailable")
    worker.agents.get_by_id.side_effect = TimeoutError("database unavailable")
    with patch(
        "api.domains.communications.processor.decrypt_token", side_effect=TimeoutError("decryption unavailable")
    ) as decrypt:
        assert worker.process_one() is True
    worker.connections.get_active.assert_not_called()
    worker.agents.get_by_id.assert_not_called()
    decrypt.assert_not_called()
    plugin.send.assert_not_called()
    assert deliveries.complete_outbound.call_args.args == (delivery.id,)
    assert deliveries.complete_outbound.call_args.kwargs["error_details"].retryable is False

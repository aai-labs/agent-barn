import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch
from uuid import uuid4

from api.core.config import Config
from api.domains.communications.models import (
    CommunicationDeliveryStatus,
    ConversationLocation,
    OutboundCommunicationEnvelope,
    ProcessingFeedbackStage,
)
from api.domains.communications.plugins.slack import SlackCredentials, SlackSettings
from api.domains.communications.processor import OutboundCommunicationProcessor


def _delivery() -> tuple[SimpleNamespace, OutboundCommunicationEnvelope]:
    connection_id = uuid4()
    source_delivery_id = uuid4()
    outbound = OutboundCommunicationEnvelope(
        source_delivery_id=source_delivery_id,
        location=ConversationLocation(id="C123", type="CHANNEL", thread_id="1724264405.531769"),
        text="reply",
        reply_to_provider_message_id="1724264405.531769",
    )
    return (
        SimpleNamespace(
            id=uuid4(),
            connection_id=connection_id,
            envelope=outbound.model_dump(mode="json"),
        ),
        outbound,
    )


def _processor(
    delivery: SimpleNamespace,
    plugin: Mock,
    *,
    status: CommunicationDeliveryStatus,
) -> tuple[OutboundCommunicationProcessor, Mock, Mock]:
    deliveries = Mock()
    deliveries.claim_next_outbound.return_value = delivery
    deliveries.complete_outbound.return_value = True
    deliveries.delivery_status.return_value = status
    connections = Mock()
    connections.get_active.return_value = SimpleNamespace(
        enabled=True,
        platform_key="slack",
        settings={},
        credentials_encrypted="ciphertext",
    )
    plugins = Mock()
    plugins.require.return_value = plugin
    gateway = Mock()
    processor = OutboundCommunicationProcessor(
        config=cast(Config, SimpleNamespace(agent_token_encryption_key="key")),
        deliveries=deliveries,
        connections=connections,
        plugins=plugins,
        gateway=gateway,
    )
    return processor, gateway, deliveries


def _plugin(send_result: str | None = "provider-reply", *, error: Exception | None = None) -> Mock:
    plugin = Mock()
    plugin.settings_model = SlackSettings
    plugin.credentials_model = SlackCredentials
    plugin.send.side_effect = error or None
    if error is None:
        plugin.send.return_value = send_result
    return plugin


def test_outbound_success_feedback_runs_after_durable_provider_success() -> None:
    delivery, outbound = _delivery()
    processor, gateway, deliveries = _processor(
        delivery,
        _plugin(),
        status=CommunicationDeliveryStatus.SUCCEEDED,
    )

    with patch(
        "api.domains.communications.processor.decrypt_token",
        return_value=json.dumps({"bot_token": "xoxb-token", "app_token": "xapp-token"}),
    ):
        assert processor.process_one() is True

    deliveries.complete_outbound.assert_called_once_with(delivery.id, provider_message_id="provider-reply")
    context = gateway.notify_processing_feedback.call_args.args[0]
    assert context.stage == ProcessingFeedbackStage.SUCCEEDED
    assert context.connection_id == delivery.connection_id
    assert context.location == outbound.location
    assert context.provider_message_id == outbound.reply_to_provider_message_id
    assert context.source_delivery_id == outbound.source_delivery_id


def test_outbound_terminal_failure_feedback_marks_failed_after_dead_letter() -> None:
    delivery, _ = _delivery()
    processor, gateway, _ = _processor(
        delivery,
        _plugin(error=RuntimeError("provider unavailable")),
        status=CommunicationDeliveryStatus.DEAD_LETTERED,
    )

    with patch(
        "api.domains.communications.processor.decrypt_token",
        return_value=json.dumps({"bot_token": "xoxb-token", "app_token": "xapp-token"}),
    ):
        assert processor.process_one() is True

    context = gateway.notify_processing_feedback.call_args.args[0]
    assert context.stage == ProcessingFeedbackStage.FAILED


def test_outbound_retry_does_not_mark_processing_failed() -> None:
    delivery, _ = _delivery()
    processor, gateway, _ = _processor(
        delivery,
        _plugin(error=RuntimeError("temporary provider failure")),
        status=CommunicationDeliveryStatus.PENDING,
    )

    with patch(
        "api.domains.communications.processor.decrypt_token",
        return_value=json.dumps({"bot_token": "xoxb-token", "app_token": "xapp-token"}),
    ):
        assert processor.process_one() is True

    gateway.notify_processing_feedback.assert_not_called()

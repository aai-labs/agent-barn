import json
from types import SimpleNamespace
from typing import cast
from unittest.mock import Mock, patch
from uuid import uuid4

from api.core.config import Config
from api.domains.agents.models import Agent, AgentStatus
from api.domains.communications.gateway_service import CommunicationsGatewayService
from api.domains.communications.models import (
    AcceptedCommunicationRead,
    CommunicationConnection,
    CommunicationDeliveryStatus,
    CommunicationPolicyDisposition,
    ConversationLocation,
    NormalizedCommunicationEnvelope,
    PlatformCapability,
    ProcessingFeedbackStage,
    RuntimeDeliveryRead,
    RuntimeDeliveryResult,
)
from api.domains.communications.plugins.base import InboundAdmissionResult, PlatformPlugin
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.plugins.slack import SlackCredentials, SlackSettings


def _connection() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        enabled=True,
        platform_key="slack",
        settings={},
        credentials_encrypted="ciphertext",
    )


def _envelope() -> NormalizedCommunicationEnvelope:
    return NormalizedCommunicationEnvelope(
        provider_message_id="1724264405.531769",
        occurred_at="2026-08-24T10:00:00Z",
        location=ConversationLocation(id="C123", type="CHANNEL", thread_id="1724264405.531769"),
        text="hello",
    )


def _service(connection: CommunicationConnection, plugin: Mock) -> tuple[CommunicationsGatewayService, Mock]:
    deliveries = Mock()
    connections = Mock()
    connections.get_active.return_value = connection
    plugins = PlatformPluginRegistry([cast(PlatformPlugin, plugin)])
    service = CommunicationsGatewayService(
        config=cast(Config, SimpleNamespace(agent_token_encryption_key="key")),
        agent_repository=Mock(),
        delivery_repository=deliveries,
        connection_repository=connections,
        plugins=plugins,
    )
    return service, deliveries


def _feedback_plugin() -> Mock:
    plugin = Mock()
    plugin.key = "slack"
    plugin.display_name = "Slack"
    plugin.schema_version = 1
    plugin.capabilities = frozenset({PlatformCapability.PROCESSING_FEEDBACK})
    plugin.settings_model = SlackSettings
    plugin.credentials_model = SlackCredentials
    plugin.admit_inbound.return_value = [_envelope()]
    plugin.enrich_inbound.side_effect = lambda settings, credentials, envelopes: envelopes
    return plugin


def test_gateway_feedback_is_best_effort_after_inbound_acceptance() -> None:
    connection = cast(CommunicationConnection, _connection())
    plugin = _feedback_plugin()
    service, deliveries = _service(connection, plugin)
    deliveries.accept_inbound.return_value = AcceptedCommunicationRead(
        message_id=uuid4(),
        delivery_id=uuid4(),
        status=CommunicationDeliveryStatus.PENDING,
    )
    plugin.processing_feedback.side_effect = RuntimeError("Slack unavailable")

    with patch(
        "api.domains.communications.gateway_service.decrypt_token",
        return_value=json.dumps({"bot_token": "xoxb-token", "app_token": "xapp-token"}),
    ):
        accepted = service._accept_admitted_payload(connection, plugin, SlackSettings(), {})

    assert len(accepted) == 1
    deliveries.accept_inbound.assert_called_once()
    plugin.processing_feedback.assert_called_once()
    assert plugin.processing_feedback.call_args.args[2].stage == ProcessingFeedbackStage.ACCEPTED


def test_gateway_enriches_inbound_envelopes_with_decrypted_credentials_before_acceptance() -> None:
    connection = cast(CommunicationConnection, _connection())
    plugin = _feedback_plugin()
    enriched = _envelope().model_copy(update={"text": "enriched"})
    plugin.enrich_inbound.side_effect = None
    plugin.enrich_inbound.return_value = [enriched]
    service, deliveries = _service(connection, plugin)
    deliveries.accept_inbound.return_value = AcceptedCommunicationRead(
        message_id=uuid4(),
        delivery_id=uuid4(),
        status=CommunicationDeliveryStatus.PENDING,
    )

    with patch(
        "api.domains.communications.gateway_service.decrypt_token",
        return_value=json.dumps({"bot_token": "xoxb-token", "app_token": "xapp-token"}),
    ):
        service._accept_admitted_payload(connection, plugin, SlackSettings(), {})

    plugin.enrich_inbound.assert_called_once()
    call_settings, call_credentials, call_envelopes = plugin.enrich_inbound.call_args.args
    assert isinstance(call_settings, SlackSettings)
    assert call_credentials == SlackCredentials(bot_token="xoxb-token", app_token="xapp-token")
    assert call_envelopes == [_envelope()]
    deliveries.accept_inbound.assert_called_once_with(connection_id=connection.id, envelope=enriched)


def test_gateway_enrichment_failure_falls_back_to_unenriched_envelope() -> None:
    connection = cast(CommunicationConnection, _connection())
    plugin = _feedback_plugin()
    plugin.enrich_inbound.side_effect = RuntimeError("Slack directory unavailable")
    service, deliveries = _service(connection, plugin)
    deliveries.accept_inbound.return_value = AcceptedCommunicationRead(
        message_id=uuid4(),
        delivery_id=uuid4(),
        status=CommunicationDeliveryStatus.PENDING,
    )

    with patch(
        "api.domains.communications.gateway_service.decrypt_token",
        return_value=json.dumps({"bot_token": "xoxb-token", "app_token": "xapp-token"}),
    ):
        accepted = service._accept_admitted_payload(connection, plugin, SlackSettings(), {})

    assert len(accepted) == 1
    deliveries.accept_inbound.assert_called_once_with(connection_id=connection.id, envelope=_envelope())


def test_gateway_enrichment_validation_warning_does_not_log_credential_values(caplog) -> None:
    connection = cast(CommunicationConnection, _connection())
    plugin = _feedback_plugin()
    service, deliveries = _service(connection, plugin)
    deliveries.accept_inbound.return_value = AcceptedCommunicationRead(
        message_id=uuid4(),
        delivery_id=uuid4(),
        status=CommunicationDeliveryStatus.PENDING,
    )

    with patch(
        "api.domains.communications.gateway_service.decrypt_token",
        return_value=json.dumps({"bot_token": ["super-secret-token"], "app_token": "xapp-token"}),
    ):
        with caplog.at_level("WARNING"):
            accepted = service._accept_admitted_payload(connection, plugin, SlackSettings(), {})

    assert len(accepted) == 1
    assert "super-secret-token" not in caplog.text
    deliveries.accept_inbound.assert_called_once_with(connection_id=connection.id, envelope=_envelope())


def test_gateway_does_not_create_a_delivery_for_a_denied_admission() -> None:
    connection = cast(CommunicationConnection, _connection())
    plugin = _feedback_plugin()
    plugin.admit_inbound.return_value = InboundAdmissionResult(CommunicationPolicyDisposition.USER_DENIED)
    service, deliveries = _service(connection, plugin)

    with patch("api.domains.communications.metrics.record_policy_disposition") as record_disposition:
        accepted = service._accept_admitted_payload(connection, plugin, SlackSettings(), {})

    assert accepted == []
    deliveries.accept_inbound.assert_not_called()
    record_disposition.assert_called_once_with(CommunicationPolicyDisposition.USER_DENIED)


def test_gateway_marks_claim_and_terminal_runtime_failure_at_lifecycle_seam() -> None:
    connection = cast(CommunicationConnection, _connection())
    plugin = _feedback_plugin()
    service, deliveries = _service(connection, plugin)
    envelope = _envelope()
    delivery = RuntimeDeliveryRead(
        delivery_id=uuid4(),
        message_id=uuid4(),
        connection_id=connection.id,
        attempt_count=5,
        envelope=envelope,
    )
    deliveries.claim_next_inbound.return_value = delivery
    deliveries.get_inbound_runtime_delivery.return_value = delivery
    deliveries.complete_runtime_delivery.return_value = True
    deliveries.delivery_status.return_value = CommunicationDeliveryStatus.DEAD_LETTERED
    agent = cast(Agent, SimpleNamespace(id=uuid4(), status=AgentStatus.RUNNING))

    with patch(
        "api.domains.communications.gateway_service.decrypt_token",
        return_value=json.dumps({"bot_token": "xoxb-token", "app_token": "xapp-token"}),
    ):
        claimed = service.claim_runtime_delivery(agent)
        completed = service.complete_runtime_delivery(
            agent,
            delivery.delivery_id,
            RuntimeDeliveryResult(succeeded=False, error_code="RuntimeError", error_message="failed"),
        )

    assert claimed == delivery
    assert completed is True
    stages = [call.args[2].stage for call in plugin.processing_feedback.call_args_list]
    assert stages == [ProcessingFeedbackStage.CLAIMED, ProcessingFeedbackStage.FAILED]


def test_runtime_completion_is_not_blocked_by_feedback_context_lookup() -> None:
    connection = cast(CommunicationConnection, _connection())
    plugin = _feedback_plugin()
    service, deliveries = _service(connection, plugin)
    deliveries.complete_runtime_delivery.return_value = True
    deliveries.delivery_status.return_value = CommunicationDeliveryStatus.DEAD_LETTERED
    deliveries.get_inbound_runtime_delivery.side_effect = RuntimeError("database unavailable")
    agent = cast(Agent, SimpleNamespace(id=uuid4(), status=AgentStatus.RUNNING))

    completed = service.complete_runtime_delivery(
        agent,
        uuid4(),
        RuntimeDeliveryResult(succeeded=False, error_code="RuntimeError", error_message="failed"),
    )

    assert completed is True
    deliveries.complete_runtime_delivery.assert_called_once()
    plugin.processing_feedback.assert_not_called()

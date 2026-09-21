import asyncio
import json
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import httpx
import pytest
from hamcrest import assert_that, empty, equal_to, is_

from api.core.config import Config
from api.domains.agents.models import Agent, AgentStatus, AgentType
from api.domains.communications.gateway_service import (
    CommunicationsGatewayService,
)
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
    RuntimeReplyCreate,
)
from api.domains.communications.plugins.base import InboundAdmissionResult, PlatformPlugin
from api.domains.communications.plugins.registry import PlatformPluginRegistry
from api.domains.communications.plugins.slack import SlackCredentials, SlackSettings
from api.domains.communications.plugins.teams import TeamsPlatformPlugin
from api.domains.communications.teams_runtime_webhook import (
    RuntimeWebhookRelayResponse,
    RuntimeWebhookUnavailable,
    TeamsRuntimeWebhookRelay,
)
from api.infrastructure.communication_signals import CommunicationSignalType


def _connection() -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        agent_id=uuid4(),
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
        provider_metadata={"route": "stored-provider-route"},
    )


def _service(
    connection: CommunicationConnection,
    plugin: Mock,
    *,
    operations: Mock | None = None,
) -> tuple[CommunicationsGatewayService, Mock]:
    deliveries = Mock()
    connections = Mock()
    connections.get_active.return_value = connection
    plugins = PlatformPluginRegistry([cast(PlatformPlugin, plugin)])
    service = CommunicationsGatewayService(
        config=cast(Config, SimpleNamespace(agent_token_encryption_key="key", native_platform_keys=frozenset())),
        agent_repository=Mock(),
        delivery_repository=deliveries,
        connection_repository=connections,
        email_addresses=Mock(),
        plugins=plugins,
        signals=Mock(),
        operations=operations,
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
    plugin.supports_progress_updates = True
    plugin.runtime_prompt.side_effect = lambda envelope: envelope.text
    plugin.admit_inbound.return_value = InboundAdmissionResult(
        CommunicationPolicyDisposition.ACCEPTED,
        (_envelope(),),
    )
    plugin.enrich_inbound.side_effect = lambda settings, credentials, envelopes: envelopes
    return plugin


def _teams_runtime_service(
    *, settings: dict | None = None
) -> tuple[TeamsRuntimeWebhookRelay, TeamsPlatformPlugin, CommunicationConnection]:
    connection = cast(
        CommunicationConnection,
        SimpleNamespace(
            id=uuid4(),
            organization_id=uuid4(),
            agent_id=uuid4(),
            enabled=True,
            platform_key="teams",
            settings=settings or {"dm_policy": "open"},
            credentials_encrypted="ciphertext",
        ),
    )
    validation_config = SimpleNamespace(
        skip_teams_token_validation=True,
        teams_publisher_name="Agent Barn",
        teams_publisher_website_url="https://example.test",
        teams_privacy_url="https://example.test/privacy",
        teams_terms_url="https://example.test/terms",
    )
    plugin = TeamsPlatformPlugin(cast(Any, validation_config))
    connections = Mock()
    connections.get_active.return_value = connection
    agents = Mock()
    agents.get_by_id.return_value = SimpleNamespace(
        id=connection.agent_id,
        deleted_at=None,
        status=AgentStatus.RUNNING,
    )
    service = TeamsRuntimeWebhookRelay(
        config=cast(
            Config,
            SimpleNamespace(
                agent_token_encryption_key="key",
                native_platform_keys=frozenset({"teams"}),
                k8s_namespace="agent-farm",
            ),
        ),
        agent_repository=agents,
        connection_repository=connections,
        plugins=PlatformPluginRegistry([plugin]),
        operations=Mock(),
    )
    return service, plugin, connection


def _teams_activity() -> dict:
    return {
        "type": "message",
        "id": "activity-1",
        "timestamp": "2026-09-17T12:00:00Z",
        "serviceUrl": "https://smba.trafficmanager.net/amer/",
        "from": {"id": "teams-user", "aadObjectId": "aad-user"},
        "recipient": {"id": "bot-id"},
        "conversation": {"conversationType": "personal", "id": "conversation-1"},
        "text": "hello",
    }


def test_runtime_teams_webhook_is_verified_and_relayed_to_the_private_agent_service() -> None:
    service, plugin, connection = _teams_runtime_service()
    upstream = SimpleNamespace(status_code=200, content=b'{"ok":true}', headers={"Content-Type": "application/json"})

    with (
        patch(
            "api.domains.communications.teams_runtime_webhook.decrypt_token",
            return_value=json.dumps({"app_id": "app", "app_password": "secret", "tenant_id": "tenant"}),
        ),
        patch.object(plugin, "verify_webhook") as verify,
        patch("api.domains.communications.teams_runtime_webhook.resilient_request", return_value=upstream) as request,
    ):
        result = service.relay(connection.id, _teams_activity(), "Bearer signed-token")

    assert result == RuntimeWebhookRelayResponse(200, b'{"ok":true}', "application/json")
    verify.assert_called_once()
    assert request.call_args.args == (
        "POST",
        f"http://agent-{connection.agent_id}.agent-farm.svc.cluster.local:3978/api/messages",
    )
    assert request.call_args.kwargs["headers"]["Authorization"] == "Bearer signed-token"
    assert json.loads(request.call_args.kwargs["content"]) == _teams_activity()
    assert request.call_args.kwargs["max_retries"] == 0


def test_runtime_teams_webhook_policy_denial_is_acknowledged_without_relay() -> None:
    service, plugin, connection = _teams_runtime_service(settings={"dm_policy": "off"})

    with (
        patch(
            "api.domains.communications.teams_runtime_webhook.decrypt_token",
            return_value=json.dumps({"app_id": "app", "app_password": "secret", "tenant_id": "tenant"}),
        ),
        patch.object(plugin, "verify_webhook"),
        patch("api.domains.communications.teams_runtime_webhook.resilient_request") as request,
    ):
        result = service.relay(connection.id, _teams_activity(), "Bearer signed-token")

    assert result == RuntimeWebhookRelayResponse(200, b"")
    request.assert_not_called()


def test_runtime_teams_webhook_requires_a_running_agent() -> None:
    service, plugin, connection = _teams_runtime_service()
    cast(Mock, service.agent_repository).get_by_id.return_value.status = AgentStatus.STOPPED

    with (
        patch(
            "api.domains.communications.teams_runtime_webhook.decrypt_token",
            return_value=json.dumps({"app_id": "app", "app_password": "secret", "tenant_id": "tenant"}),
        ),
        patch.object(plugin, "verify_webhook"),
        pytest.raises(RuntimeWebhookUnavailable, match="not running"),
    ):
        service.relay(connection.id, _teams_activity(), "Bearer signed-token")


def test_runtime_teams_webhook_maps_transport_failure_to_unavailable() -> None:
    service, plugin, connection = _teams_runtime_service()

    with (
        patch(
            "api.domains.communications.teams_runtime_webhook.decrypt_token",
            return_value=json.dumps({"app_id": "app", "app_password": "secret", "tenant_id": "tenant"}),
        ),
        patch.object(plugin, "verify_webhook"),
        patch(
            "api.domains.communications.teams_runtime_webhook.resilient_request",
            side_effect=httpx.ConnectError("refused"),
        ),
        pytest.raises(RuntimeWebhookUnavailable, match="unavailable"),
    ):
        service.relay(connection.id, _teams_activity(), "Bearer signed-token")


def test_gateway_owned_teams_webhook_is_not_handled_by_the_runtime_relay() -> None:
    service, plugin, connection = _teams_runtime_service()
    cast(Any, service.config).native_platform_keys = frozenset()

    with (
        patch(
            "api.domains.communications.teams_runtime_webhook.decrypt_token",
            return_value=json.dumps({"app_id": "app", "app_password": "secret", "tenant_id": "tenant"}),
        ),
        patch.object(plugin, "verify_webhook") as verify,
    ):
        result = service.relay(connection.id, _teams_activity(), "Bearer signed-token")

    assert result is None
    verify.assert_not_called()


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
    signals = cast(Mock, service.signals)
    published_agent_id, published_signal = signals.publish.call_args.args
    assert published_agent_id == connection.agent_id
    assert published_signal.type == CommunicationSignalType.DELIVERY_AVAILABLE


def test_gateway_renews_only_the_authenticated_agents_live_delivery() -> None:
    connection = cast(CommunicationConnection, _connection())
    service, deliveries = _service(connection, _feedback_plugin())
    agent = cast(Agent, SimpleNamespace(id=uuid4(), status=AgentStatus.RUNNING))
    deliveries.renew_runtime_delivery_lease.return_value = True

    renewed = service.renew_runtime_delivery_lease(agent, uuid4())

    assert_that(renewed, is_(True))
    deliveries.renew_runtime_delivery_lease.assert_called_once()
    assert deliveries.renew_runtime_delivery_lease.call_args.kwargs["agent_id"] == agent.id


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

    assert_that(accepted, empty())
    deliveries.accept_inbound.assert_not_called()
    record_disposition.assert_called_once_with(CommunicationPolicyDisposition.USER_DENIED)


def test_gateway_journal_failure_does_not_drop_an_event() -> None:
    connection = cast(CommunicationConnection, _connection())
    connection.organization_id = uuid4()
    connection.agent_id = uuid4()
    plugin = _feedback_plugin()
    operations = Mock()
    operations.record_journal.side_effect = RuntimeError("database unavailable")
    service, deliveries = _service(connection, plugin, operations=operations)

    accepted = service._accept_admitted_payload(connection, plugin, SlackSettings(), {})

    assert len(accepted) == 1
    deliveries.accept_inbound.assert_called_once_with(connection_id=connection.id, envelope=_envelope())
    plugin.admit_inbound.assert_called_once()


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
    deliveries.reclaim_expired_inbound.return_value = []
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

    # The claim now carries a server-issued execution token; the rest must be unchanged.
    assert claimed is not None and claimed.execution_token
    assert claimed.model_copy(update={"execution_token": None}) == delivery
    assert completed is True
    stages = [call.args[2].stage for call in plugin.processing_feedback.call_args_list]
    assert stages == [ProcessingFeedbackStage.CLAIMED, ProcessingFeedbackStage.FAILED]
    assert_that(
        plugin.processing_feedback.call_args_list[1].args[2].provider_metadata,
        equal_to(envelope.provider_metadata),
    )
    published_agent_id, published_signal = cast(Mock, service.signals).publish.call_args.args
    assert published_agent_id == agent.id
    assert published_signal.type == CommunicationSignalType.MESSAGE_CHANGED
    assert published_signal.delivery_id == delivery.delivery_id


def test_native_platform_deliveries_are_not_reclaimed_or_claimed_by_the_gateway() -> None:
    connection = cast(CommunicationConnection, _connection())
    service, deliveries = _service(connection, _feedback_plugin())
    service.config = Config(
        agent_token_encryption_key="key",
        communications_native_platforms="slack,discord",
    )
    deliveries.reclaim_expired_inbound.return_value = []
    deliveries.claim_next_inbound.return_value = None
    agent = cast(
        Agent,
        SimpleNamespace(id=uuid4(), status=AgentStatus.RUNNING, agent_type=AgentType.OPENCLAW),
    )

    assert service.claim_runtime_delivery(agent) is None

    excluded = frozenset({"slack", "discord"})
    deliveries.reclaim_expired_inbound.assert_called_once_with(
        agent_id=agent.id,
        excluded_platform_keys=excluded,
    )
    deliveries.claim_next_inbound.assert_called_once_with(
        agent_id=agent.id,
        reclaim_expired=False,
        excluded_platform_keys=excluded,
    )


def test_cancel_persists_before_publishing_to_the_runtime_control_stream() -> None:
    connection = cast(CommunicationConnection, _connection())
    plugin = _feedback_plugin()
    service, deliveries = _service(connection, plugin)
    delivery_id = uuid4()
    agent_id = uuid4()
    deliveries.request_cancel.return_value = CommunicationDeliveryStatus.PROCESSING

    assert service.request_cancel_delivery(agent_id, delivery_id) is True

    deliveries.request_cancel.assert_called_once_with(delivery_id, agent_id=agent_id)
    signals = cast(Mock, service.signals)
    published_agent_id, published_signal = signals.publish.call_args.args
    assert published_agent_id == agent_id
    assert published_signal.type == CommunicationSignalType.DELIVERY_CANCELLED
    assert published_signal.delivery_id == delivery_id


def test_runtime_reply_publishes_message_changed_for_the_new_outbound_delivery() -> None:
    connection = cast(CommunicationConnection, _connection())
    plugin = _feedback_plugin()
    service, deliveries = _service(connection, plugin)
    agent = cast(Agent, SimpleNamespace(id=uuid4()))
    source_delivery_id = uuid4()
    outbound_delivery_id = uuid4()
    deliveries.enqueue_runtime_reply.return_value = outbound_delivery_id
    reply = RuntimeReplyCreate(idempotency_key="reply-1", text="agent reply")

    returned_delivery_id = service.enqueue_runtime_reply(agent, source_delivery_id, reply)

    assert returned_delivery_id == outbound_delivery_id
    deliveries.enqueue_runtime_reply.assert_called_once_with(
        agent_id=agent.id,
        source_delivery_id=source_delivery_id,
        reply=reply,
    )
    published_agent_id, published_signal = cast(Mock, service.signals).publish.call_args.args
    assert published_agent_id == agent.id
    assert published_signal.type == CommunicationSignalType.MESSAGE_CHANGED
    assert published_signal.delivery_id == outbound_delivery_id


def test_runtime_control_stream_replays_then_heartbeats_without_claim_polling() -> None:
    connection = cast(CommunicationConnection, _connection())
    plugin = _feedback_plugin()
    service, _ = _service(connection, plugin)
    agent = cast(Agent, SimpleNamespace(id=uuid4()))
    signals = cast(Mock, service.signals)
    signals.latest_cursor_async = AsyncMock(return_value="10-0")
    signals.wait_async = AsyncMock(return_value=("10-0", []))

    stream = service.stream_runtime_control(agent)

    async def read_frames() -> tuple[str, str]:
        return await stream.__anext__(), await stream.__anext__()

    first, second = asyncio.run(read_frames())

    assert json.loads(first.removeprefix("data: ")) == {"type": "delivery_available"}
    assert second == ": keep-alive\n\n"
    signals.latest_cursor_async.assert_awaited_once_with(agent.id)
    signals.wait_async.assert_awaited_once_with(agent.id, "10-0")
    signals.latest_cursor.assert_not_called()
    signals.wait.assert_not_called()


def test_a_claimed_delivery_carries_whether_its_platform_accepts_progress_updates() -> None:
    for accepts_progress in (True, False):
        connection = cast(CommunicationConnection, _connection())
        plugin = _feedback_plugin()
        plugin.supports_progress_updates = accepts_progress
        service, deliveries = _service(connection, plugin)
        delivery = RuntimeDeliveryRead(
            delivery_id=uuid4(),
            message_id=uuid4(),
            connection_id=connection.id,
            attempt_count=1,
            envelope=_envelope(),
        )
        deliveries.claim_next_inbound.return_value = delivery
        deliveries.reclaim_expired_inbound.return_value = []
        agent = cast(Agent, SimpleNamespace(id=uuid4(), status=AgentStatus.RUNNING))

        with patch(
            "api.domains.communications.gateway_service.decrypt_token",
            return_value=json.dumps({"bot_token": "xoxb-token", "app_token": "xapp-token"}),
        ):
            claimed = service.claim_runtime_delivery(agent)

        assert claimed is not None
        assert claimed.progress_updates is accepts_progress


def test_a_claimed_delivery_carries_the_prompt_its_platform_builds_for_the_runtime() -> None:
    connection = cast(CommunicationConnection, _connection())
    plugin = _feedback_plugin()
    plugin.runtime_prompt.side_effect = lambda envelope: f"FRAMING\n\n{envelope.text}"
    service, deliveries = _service(connection, plugin)
    delivery = RuntimeDeliveryRead(
        delivery_id=uuid4(),
        message_id=uuid4(),
        connection_id=connection.id,
        attempt_count=1,
        envelope=_envelope(),
    )
    deliveries.claim_next_inbound.return_value = delivery
    deliveries.reclaim_expired_inbound.return_value = []
    agent = cast(Agent, SimpleNamespace(id=uuid4(), status=AgentStatus.RUNNING))

    with patch(
        "api.domains.communications.gateway_service.decrypt_token",
        return_value=json.dumps({"bot_token": "xoxb-token", "app_token": "xapp-token"}),
    ):
        claimed = service.claim_runtime_delivery(agent)

    assert claimed is not None
    assert claimed.envelope.text == "FRAMING\n\nhello"
    assert delivery.envelope.text == "hello"


def test_a_claim_retries_when_its_platform_plugin_is_gone() -> None:
    retired_platform = _connection()
    retired_platform.platform_key = "platform-that-no-longer-ships"
    connection = cast(CommunicationConnection, retired_platform)
    service, deliveries = _service(connection, _feedback_plugin())
    delivery = RuntimeDeliveryRead(
        delivery_id=uuid4(),
        message_id=uuid4(),
        connection_id=connection.id,
        attempt_count=1,
        envelope=_envelope(),
    )
    deliveries.claim_next_inbound.return_value = delivery
    deliveries.reclaim_expired_inbound.return_value = []
    agent = cast(Agent, SimpleNamespace(id=uuid4(), status=AgentStatus.RUNNING))

    with pytest.raises(RuntimeError, match="Could not prepare runtime delivery"):
        service.claim_runtime_delivery(agent)


def test_a_claim_retries_when_its_connection_is_no_longer_active() -> None:
    connection = cast(CommunicationConnection, _connection())
    service, deliveries = _service(connection, _feedback_plugin())
    cast(Mock, service.connection_repository).get_active.return_value = None
    delivery = RuntimeDeliveryRead(
        delivery_id=uuid4(),
        message_id=uuid4(),
        connection_id=connection.id,
        attempt_count=1,
        envelope=_envelope(),
    )
    deliveries.claim_next_inbound.return_value = delivery
    deliveries.reclaim_expired_inbound.return_value = []
    agent = cast(Agent, SimpleNamespace(id=uuid4(), status=AgentStatus.RUNNING))

    with pytest.raises(RuntimeError, match="is no longer active"):
        service.claim_runtime_delivery(agent)


def test_gateway_reports_a_dead_letter_created_by_lease_reclaim() -> None:
    connection = cast(CommunicationConnection, _connection())
    plugin = _feedback_plugin()
    service, deliveries = _service(connection, plugin)
    stale = RuntimeDeliveryRead(
        delivery_id=uuid4(),
        message_id=uuid4(),
        connection_id=connection.id,
        attempt_count=5,
        envelope=_envelope(),
    )
    deliveries.reclaim_expired_inbound.return_value = [stale]
    deliveries.claim_next_inbound.return_value = None
    agent = cast(Agent, SimpleNamespace(id=uuid4(), status=AgentStatus.RUNNING))

    with patch(
        "api.domains.communications.gateway_service.decrypt_token",
        return_value=json.dumps({"bot_token": "xoxb-token", "app_token": "xapp-token"}),
    ):
        assert service.claim_runtime_delivery(agent) is None

    assert plugin.processing_feedback.call_args.args[2].stage == ProcessingFeedbackStage.FAILED


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

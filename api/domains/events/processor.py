import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from api.domains.events.handlers import (
    EventDeliveryContext,
    EventHandlerRegistry,
    RetryableEventHandlerError,
    TerminalEventHandlerError,
    UnknownEventHandlerError,
    UnsupportedHandlerEventError,
)
from api.domains.events.models import (
    ActorIdentity,
    DomainEventEnvelope,
    EventDelivery,
    EventDeliveryDeadLetterReason,
    EventDeliveryStatus,
    OutboxMessage,
    SubjectIdentity,
)
from api.domains.events.repository import OutboxMessageRepository

logger = logging.getLogger(__name__)


@dataclass
class EventDeliveryProcessor:
    repository: OutboxMessageRepository
    handlers: EventHandlerRegistry
    processing_stale_seconds: int = 900

    def process(self, delivery_id: UUID) -> bool:
        delivery = self.repository.get_delivery(delivery_id)
        if delivery is None:
            return False
        if delivery.status in {EventDeliveryStatus.SUCCEEDED, EventDeliveryStatus.DEAD_LETTERED}:
            return False

        message = self.repository.get_by_event_id(delivery.event_id)
        if message is None:
            logger.warning(
                "Event Delivery dead-lettered: delivery_id=%s handler_name=%s reason=%s",
                delivery.id,
                delivery.handler_name,
                EventDeliveryDeadLetterReason.INVALID_DELIVERY.value,
            )
            self.repository.mark_delivery_dead_lettered(
                delivery.id,
                reason=EventDeliveryDeadLetterReason.INVALID_DELIVERY,
                error=f"Event Delivery {delivery.id} references missing Outbox Message {delivery.event_id}",
            )
            return False

        if not self._validate_handler(delivery, message):
            return False

        now = datetime.now(UTC)
        claimed = self.repository.claim_delivery(
            delivery.id,
            claimed_at=now,
            processing_stale_before=now - timedelta(seconds=self.processing_stale_seconds),
        )
        if claimed is None:
            return False

        event = self._envelope_from_message(message)
        context = EventDeliveryContext(
            delivery_id=claimed.id,
            event_id=claimed.event_id,
            handler_name=claimed.handler_name,
            attempt_count=claimed.attempt_count,
            correlation_id=message.correlation_id,
            organization_id=claimed.organization_id,
        )
        handler = self.handlers.get(claimed.handler_name)

        started = time.monotonic()
        try:
            handler.handle(event, context)
        except TerminalEventHandlerError as exc:
            self._log_handler_outcome(claimed, event, started, outcome="terminal_error")
            self.repository.mark_delivery_dead_lettered(
                claimed.id,
                reason=EventDeliveryDeadLetterReason.TERMINAL_HANDLER_ERROR,
                error=exc,
            )
            return False
        except RetryableEventHandlerError as exc:
            self._log_handler_outcome(claimed, event, started, outcome="retryable_error")
            self.repository.mark_delivery_retryable_failure(claimed.id, exc)
            raise
        except Exception as exc:
            self._log_handler_outcome(claimed, event, started, outcome="unexpected_error")
            self.repository.mark_delivery_retryable_failure(claimed.id, exc)
            raise

        self._log_handler_outcome(claimed, event, started, outcome="succeeded")
        self.repository.mark_delivery_succeeded(claimed.id)
        return True

    @staticmethod
    def _log_handler_outcome(
        delivery: EventDelivery,
        event: DomainEventEnvelope,
        started: float,
        *,
        outcome: str,
    ) -> None:
        duration_ms = (time.monotonic() - started) * 1000
        logger.info(
            "Event Delivery handler %s: delivery_id=%s handler_name=%s event_name=%s attempt_count=%s duration_ms=%.1f",
            outcome,
            delivery.id,
            delivery.handler_name,
            event.event_name,
            delivery.attempt_count,
            duration_ms,
        )

    def _validate_handler(self, delivery: EventDelivery, message: OutboxMessage) -> bool:
        try:
            self.handlers.require_support(delivery.handler_name, message.event_name, message.schema_version)
        except UnknownEventHandlerError as exc:
            self._log_dead_letter(delivery, message, reason=EventDeliveryDeadLetterReason.UNKNOWN_HANDLER)
            self.repository.mark_delivery_dead_lettered(
                delivery.id,
                reason=EventDeliveryDeadLetterReason.UNKNOWN_HANDLER,
                error=exc,
            )
            return False
        except UnsupportedHandlerEventError as exc:
            self._log_dead_letter(delivery, message, reason=EventDeliveryDeadLetterReason.UNSUPPORTED_EVENT)
            self.repository.mark_delivery_dead_lettered(
                delivery.id,
                reason=EventDeliveryDeadLetterReason.UNSUPPORTED_EVENT,
                error=exc,
            )
            return False
        return True

    @staticmethod
    def _log_dead_letter(
        delivery: EventDelivery,
        message: OutboxMessage,
        *,
        reason: EventDeliveryDeadLetterReason,
    ) -> None:
        logger.warning(
            "Event Delivery dead-lettered: delivery_id=%s handler_name=%s event_name=%s reason=%s",
            delivery.id,
            delivery.handler_name,
            message.event_name,
            reason.value,
        )

    @staticmethod
    def _envelope_from_message(message: OutboxMessage) -> DomainEventEnvelope:
        return DomainEventEnvelope(
            event_id=message.event_id,
            event_name=message.event_name,
            schema_version=message.schema_version,
            occurred_at=message.occurred_at,
            event_scope=message.event_scope,
            organization_id=message.organization_id,
            actor=ActorIdentity.model_validate(message.actor),
            subject=SubjectIdentity.model_validate(message.subject),
            correlation_id=message.correlation_id,
            causation_id=message.causation_id,
            payload=message.payload,
        )

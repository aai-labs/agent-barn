from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlmodel import Session, select

from api.domains.events.models import DomainEventEnvelope, EventDelivery, OutboxMessage
from api.domains.events.registry import DomainEventRegistry
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class OutboxMessageRepository:
    delegate: PostgresRepositoryDelegate

    def create(self, event: DomainEventEnvelope, registry: DomainEventRegistry) -> OutboxMessage:
        with Session(self.delegate.engine) as session:
            message = self.stage(session=session, event=event, registry=registry)
            session.commit()
            session.refresh(message)
            return message

    def stage(
        self,
        *,
        session: Session,
        event: DomainEventEnvelope,
        registry: DomainEventRegistry,
    ) -> OutboxMessage:
        message = self.build_message(event)
        session.add(message)
        session.flush()
        deliveries = self.build_deliveries(message, registry.handler_names_for(event.event_name, event.schema_version))
        session.add_all(deliveries)
        session.flush()
        return message

    def build_message(self, event: DomainEventEnvelope) -> OutboxMessage:
        return OutboxMessage(
            event_id=event.event_id,
            event_name=event.event_name,
            schema_version=event.schema_version,
            occurred_at=event.occurred_at,
            organization_id=event.organization_id,
            actor=event.actor.model_dump(mode="json"),
            subject=event.subject.model_dump(mode="json"),
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            payload=event.payload,
        )

    def build_deliveries(self, message: OutboxMessage, handler_names: tuple[str, ...]) -> list[EventDelivery]:
        return [
            EventDelivery(
                outbox_message_id=message.id,
                event_id=message.event_id,
                organization_id=message.organization_id,
                handler_name=handler_name,
            )
            for handler_name in handler_names
        ]

    def get_by_event_id(self, event_id: UUID) -> OutboxMessage | None:
        with Session(self.delegate.engine) as session:
            return session.exec(select(OutboxMessage).where(OutboxMessage.event_id == event_id)).one_or_none()

    def list_deliveries_for_event(self, event_id: UUID) -> list[EventDelivery]:
        with Session(self.delegate.engine) as session:
            return list(session.exec(select(EventDelivery).where(EventDelivery.event_id == event_id)))

    def count(self) -> int:
        return self.delegate.count(OutboxMessage)

    def delivery_count(self) -> int:
        return self.delegate.count(EventDelivery)

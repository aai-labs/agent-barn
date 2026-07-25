from dataclasses import dataclass
from uuid import UUID

from sqlmodel import Session, select

from api.domains.events.models import DomainEventEnvelope, OutboxMessage
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@dataclass
class OutboxMessageRepository:
    delegate: PostgresRepositoryDelegate

    def create(self, event: DomainEventEnvelope) -> OutboxMessage:
        with Session(self.delegate.engine) as session:
            message = self.build_message(event)
            session.add(message)
            session.commit()
            session.refresh(message)
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

    def get_by_event_id(self, event_id: UUID) -> OutboxMessage | None:
        with Session(self.delegate.engine) as session:
            return session.exec(select(OutboxMessage).where(OutboxMessage.event_id == event_id)).one_or_none()

    def count(self) -> int:
        return self.delegate.count(OutboxMessage)

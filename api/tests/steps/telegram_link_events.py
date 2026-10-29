"""Reads the Telegram link Domain Events staged in the outbox."""

from sqlmodel import Session, col, select

from api.domains.events.catalog import TELEGRAM_ACCOUNT_UNLINKED, TELEGRAM_FIRST_MESSAGE_RECEIVED
from api.domains.events.models import OutboxMessage
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


def _events(context, event_name: str) -> list[OutboxMessage]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(
            session.exec(
                select(OutboxMessage)
                .where(col(OutboxMessage.event_name) == event_name)
                .order_by(col(OutboxMessage.occurred_at))
            )
        )


def unlinked_events(context) -> list[OutboxMessage]:
    return _events(context, TELEGRAM_ACCOUNT_UNLINKED)


def first_message_events(context) -> list[OutboxMessage]:
    return _events(context, TELEGRAM_FIRST_MESSAGE_RECEIVED)


def unlink_reasons(context) -> list[str]:
    return [event.payload["reason"] for event in unlinked_events(context)]

"""Reads the Telegram link Domain Events staged in the outbox."""

from sqlmodel import Session, col, select

from api.domains.events.catalog import TELEGRAM_ACCOUNT_UNLINKED
from api.domains.events.models import OutboxMessage
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


def unlinked_events(context) -> list[OutboxMessage]:
    with Session(context.injector.get(PostgresRepositoryDelegate).engine) as session:
        return list(
            session.exec(
                select(OutboxMessage)
                .where(col(OutboxMessage.event_name) == TELEGRAM_ACCOUNT_UNLINKED)
                .order_by(col(OutboxMessage.occurred_at))
            )
        )


def unlink_reasons(context) -> list[str]:
    return [event.payload["reason"] for event in unlinked_events(context)]

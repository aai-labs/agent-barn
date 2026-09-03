from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, col, func, select

from api.domains.communications.models import AgentEmailAddress
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


def release_agent_email_addresses(now: datetime):
    """Build the release statement for Connection retirement and Agent deletion.

    Both callers run bulk statements inside their own transaction, so this returns
    the statement rather than executing it, and lives here rather than in the
    Connection repository because that module already imports the Agent repository.
    The row is kept rather than deleted so a retired Agent's correspondents can
    never be routed to whoever is allocated next.
    """
    return (
        sa.update(AgentEmailAddress)
        .where(col(AgentEmailAddress.released_at).is_(None))
        .values(released_at=now, updated_at=now)
    )


@inject
@singleton
@dataclass
class AgentEmailAddressRepository:
    delegate: PostgresRepositoryDelegate

    def resolve(self, local_part: str) -> UUID | None:
        normalized = local_part.strip().lower()
        if not normalized:
            return None
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(AgentEmailAddress.connection_id).where(
                    func.lower(col(AgentEmailAddress.local_part)) == normalized,
                    col(AgentEmailAddress.released_at).is_(None),
                )
            ).one_or_none()

    def addresses_for(self, connection_ids: Iterable[UUID]) -> dict[UUID, str]:
        wanted = list(connection_ids)
        if not wanted:
            return {}
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(AgentEmailAddress.connection_id, AgentEmailAddress.address).where(
                    col(AgentEmailAddress.connection_id).in_(wanted),
                    col(AgentEmailAddress.released_at).is_(None),
                )
            ).all()
            return {connection_id: address for connection_id, address in rows}

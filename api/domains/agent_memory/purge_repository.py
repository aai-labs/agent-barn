from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.agent_memory.models import AgentMemoryPurge
from api.domains.agents.models import Agent
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class MemoryPurgeRepository:
    delegate: PostgresRepositoryDelegate

    def claim(self) -> AgentMemoryPurge | None:
        """Lease one due deletion tombstone; crashed workers are reclaimed after ten minutes."""
        now = datetime.now(UTC)
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            row = session.exec(
                select(AgentMemoryPurge)
                .where(
                    col(AgentMemoryPurge.next_attempt_at) <= now,
                    (col(AgentMemoryPurge.lease_until).is_(None)) | (col(AgentMemoryPurge.lease_until) <= now),
                )
                .order_by(col(AgentMemoryPurge.next_attempt_at), col(AgentMemoryPurge.id))
                .limit(1)
                .with_for_update(skip_locked=True)
            ).first()
            if row is None:
                return None
            row.lease_id = uuid4()
            row.lease_until = now + timedelta(minutes=10)
            row.updated_at = now
            session.add(row)
            session.commit()
            return row

    def can_purge(self, row: AgentMemoryPurge) -> bool:
        """Fail closed if a target is live or belongs to a different Organization."""
        with Session(self.delegate.engine) as session:
            agent = session.get(Agent, row.agent_id)
            return agent is None or (agent.organization_id == row.organization_id and agent.deleted_at is not None)

    def finish(self, claimed: AgentMemoryPurge, error: str | None) -> None:
        """Persist a retry, or schedule a later sweep for late Hindsight jobs. Never lose the tombstone."""
        now = datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            row = session.get(AgentMemoryPurge, claimed.id, with_for_update=True)
            if row is None or row.lease_id != claimed.lease_id:
                return
            row.attempts = row.attempts + 1 if error else 0
            row.last_error = error
            if not error:
                row.last_cleaned_at = now
            # Sweep recent deletions hourly for late jobs, then daily indefinitely.
            # Retaining tombstones avoids assuming a maximum Hindsight queue lifetime.
            clean_delay = 3600 if now - row.created_at.astimezone(UTC) < timedelta(days=2) else 86400
            delay = min(3600, 30 * 2 ** min(row.attempts - 1, 7)) if error else clean_delay
            row.next_attempt_at = now + timedelta(seconds=delay)
            row.lease_id = None
            row.lease_until = None
            row.updated_at = now
            session.add(row)
            session.commit()

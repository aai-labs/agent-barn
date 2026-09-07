import datetime
from dataclasses import dataclass

from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, func, select

from api.domains.costs.models import HonchoUsageEvent
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@dataclass(frozen=True)
class WorkspaceTokenTotals:
    workspace_name: str
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@inject
@singleton
@dataclass
class HonchoUsageRepository:
    delegate: PostgresRepositoryDelegate

    def record(self, events: list[HonchoUsageEvent]) -> int:
        """Persist usage rows, discarding any CloudEvent id already stored.

        Honcho retries failed batches, so the same event can arrive more than
        once; counting it twice would skew every workspace's share.
        """
        if not events:
            return 0
        rows = [event.model_dump() for event in events]
        statement = insert(HonchoUsageEvent).values(rows).on_conflict_do_nothing(index_elements=["event_id"])
        with Session(self.delegate.engine) as session:
            # Straight to the connection: this is an INSERT with ON CONFLICT, which
            # `Session.exec` does not type, and the count of rows actually stored
            # (duplicates are discarded) comes from the cursor.
            result = session.connection().execute(statement)
            session.commit()
            return result.rowcount

    def token_totals_by_workspace(self, start: datetime.datetime, end: datetime.datetime) -> list[WorkspaceTokenTotals]:
        statement = (
            select(
                HonchoUsageEvent.workspace_name,
                func.sum(HonchoUsageEvent.input_tokens),
                func.sum(HonchoUsageEvent.output_tokens),
            )
            .where(HonchoUsageEvent.occurred_at >= start, HonchoUsageEvent.occurred_at <= end)
            .group_by(HonchoUsageEvent.workspace_name)
        )
        with Session(self.delegate.engine) as session:
            return [
                WorkspaceTokenTotals(workspace_name=name, input_tokens=int(inp or 0), output_tokens=int(out or 0))
                for name, inp, out in session.exec(statement).all()
            ]

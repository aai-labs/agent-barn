import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlmodel import Session, SQLModel, col, select

from api.domains.costs.models import (
    COST_RECORD_STATUS_SUCCESS,
    CostRecord,
    CostRecordSource,
)
from api.domains.organizations.models import Organization
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

logger = logging.getLogger(__name__)

# The Core table behind the model. Both writes below are Core statements: the upsert
# needs Postgres' ON CONFLICT, and the heal update needs to match on a column rather
# than load the row first.
COST_RECORD_TABLE = SQLModel.metadata.tables["cost_record"]

# Successful calls that passed through OpenRouter carry its generation id. Anything
# else — a UUID from a failed request, a call to a non-OpenRouter provider — has no
# generation to look up, and guessing would invent spend that never happened.
OPENROUTER_GENERATION_ID_PREFIX = "gen-"

# Columns a re-sync is allowed to refresh on a row we already hold. `request_id`,
# `id` and `created_at` identify the row; the name columns are merged rather than
# replaced (see `upsert_many`).
_REFRESHABLE_COLUMNS = (
    "litellm_key_hash",
    "occurred_at",
    "ended_at",
    "spend",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "model",
    "status",
    "call_type",
    "request_duration_ms",
    "agent_id",
    "organization_id",
)


@inject
@singleton
@dataclass
class CostRepository:
    delegate: PostgresRepositoryDelegate

    def upsert_many(self, records: list[CostRecord]) -> int:
        """Insert or refresh cost rows, keyed on request_id. Returns rows written.

        The guard on this statement is the difference between a healing job that
        converges and one that runs forever. Each sync re-reads the last hour, and
        LiteLLM still reports `spend = 0` for a row we have already corrected from
        OpenRouter. An unguarded upsert would overwrite the recovered figure back to
        zero, the row would re-enter the heal queue, and the whole cycle would repeat
        every 15 minutes without ever finishing. So a row only accepts an update
        while it is still `litellm_live`; once healed, the sync leaves it alone.

        Display names are merged with COALESCE rather than replaced. A later sync can
        legitimately fail to resolve an agent that has since been hard-deleted, and
        overwriting the name we captured at the time would erase the only record of
        who spent the money.
        """
        if not records:
            return 0

        now = datetime.now(UTC)
        rows = []
        for record in records:
            row = record.model_dump()
            row["updated_at"] = now
            rows.append(row)

        table = COST_RECORD_TABLE
        statement = pg_insert(table).values(rows)
        assignments: dict[str, Any] = {name: statement.excluded[name] for name in _REFRESHABLE_COLUMNS}
        assignments["updated_at"] = statement.excluded["updated_at"]
        assignments["agent_name"] = sa.func.coalesce(statement.excluded["agent_name"], table.c.agent_name)
        assignments["organization_name"] = sa.func.coalesce(
            statement.excluded["organization_name"], table.c.organization_name
        )
        statement = statement.on_conflict_do_update(
            constraint="uq_cost_record_request_id",
            set_=assignments,
            where=table.c.source == CostRecordSource.LITELLM_LIVE.value,
        )

        with Session(self.delegate.engine) as session:
            result = session.exec(statement)  # type: ignore[call-overload]
            session.commit()
            return result.rowcount

    def latest_occurred_at(self) -> datetime | None:
        """The newest call we have stored, or None when the table is empty.

        The sync watermark is derived from this rather than stored anywhere. There is
        one less thing to keep consistent, and an empty table naturally means "sync
        from the beginning" — which *is* the backfill, so it needs no special case.
        """
        with Session(self.delegate.engine) as session:
            return session.exec(select(sa.func.max(col(CostRecord.occurred_at)))).one()

    def find_heal_candidates(self, limit: int) -> list[CostRecord]:
        """Rows that recorded no money for a call that plainly consumed tokens.

        The predicate mirrors `ix_cost_record_heal_candidates` exactly so the scan
        stays on the index. Newest first: recent spend is the figure someone is most
        likely to be looking at.
        """
        with Session(self.delegate.engine) as session:
            query = (
                select(CostRecord)
                .where(col(CostRecord.spend) == 0)
                .where(col(CostRecord.status) == COST_RECORD_STATUS_SUCCESS)
                .where(col(CostRecord.total_tokens) > 0)
                .where(col(CostRecord.source) == CostRecordSource.LITELLM_LIVE)
                .where(col(CostRecord.request_id).startswith(OPENROUTER_GENERATION_ID_PREFIX))
                .order_by(col(CostRecord.occurred_at).desc())
                .limit(limit)
            )
            return list(session.exec(query).all())

    def mark_healed(
        self,
        request_id: str,
        *,
        spend: Decimal,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> bool:
        """Record the true cost for one row and take it out of the heal queue.

        Called on any successful OpenRouter lookup, including one that reports zero —
        a genuinely free generation is still an answer, and leaving it untagged would
        have the job fetch it again on every run for as long as the row exists.

        Token counts are optional because OpenRouter's native counts are the
        provider's own tally and can differ slightly from LiteLLM's. Overwrite them
        only when the caller has them.
        """
        values: dict = {
            "spend": spend,
            "source": CostRecordSource.OPENROUTER_BACKFILL.value,
            "healed_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }
        if prompt_tokens is not None and completion_tokens is not None:
            values["prompt_tokens"] = prompt_tokens
            values["completion_tokens"] = completion_tokens
            values["total_tokens"] = prompt_tokens + completion_tokens

        table = COST_RECORD_TABLE
        statement = (
            sa.update(table)
            .where(table.c.request_id == request_id)
            # Never re-heal: whichever pass got there first wins, so a retry after a
            # partial failure cannot double-apply.
            .where(table.c.source == CostRecordSource.LITELLM_LIVE.value)
            .values(**values)
        )
        with Session(self.delegate.engine) as session:
            result = session.exec(statement)  # type: ignore[call-overload]
            session.commit()
            return result.rowcount > 0

    def find_organization_names(self) -> dict[UUID, str]:
        """id -> name for every organization, for denormalising attribution at write.

        Read straight from here rather than through OrganizationRepository: that one
        pulls in the outbox and its whole dependency chain, which a CronJob that only
        needs names has no business constructing.
        """
        with Session(self.delegate.engine) as session:
            rows = session.exec(select(Organization.id, Organization.name)).all()
            return {row[0]: row[1] for row in rows}

    def count_heal_candidates(self) -> int:
        """Size of the heal queue — logged each run so the backlog's progress is visible."""
        with Session(self.delegate.engine) as session:
            query = (
                select(sa.func.count())
                .select_from(CostRecord)
                .where(col(CostRecord.spend) == 0)
                .where(col(CostRecord.status) == COST_RECORD_STATUS_SUCCESS)
                .where(col(CostRecord.total_tokens) > 0)
                .where(col(CostRecord.source) == CostRecordSource.LITELLM_LIVE)
                .where(col(CostRecord.request_id).startswith(OPENROUTER_GENERATION_ID_PREFIX))
            )
            return session.exec(query).one()

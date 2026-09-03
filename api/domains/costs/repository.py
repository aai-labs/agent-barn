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

from api.domains.costs.constants import COST_HISTOGRAM_BOUNDS, TOP_AGENTS_IN_SERIES
from api.domains.costs.models import (
    COST_RECORD_STATUS_SUCCESS,
    CostFilter,
    CostRecord,
    CostRecordSource,
    CostSortDirection,
)
from api.domains.organizations.models import Organization
from api.domains.platform_admin.models import StatsWindow
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CostTotals:
    spend: Decimal
    calls: int
    agents: int
    avg_prompt_tokens: float
    prompt_tokens: int = 0
    completion_tokens: int = 0


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

    # --- Reads for the cost pages ------------------------------------------
    #
    # Every read below is filtered through `_predicates`, so a stat card and the
    # table beneath it can never disagree about what is being counted.

    def _predicates(self, window: StatsWindow, filters: CostFilter) -> list:
        predicates = [
            col(CostRecord.occurred_at) >= window.start,
            col(CostRecord.occurred_at) < window.end,
        ]
        if filters.organization_id is not None:
            predicates.append(col(CostRecord.organization_id) == filters.organization_id)
        if filters.agent_id is not None:
            predicates.append(col(CostRecord.agent_id) == filters.agent_id)
        if filters.model is not None:
            predicates.append(col(CostRecord.model) == filters.model)
        if filters.search:
            term = f"%{filters.search.strip()}%"
            predicates.append(
                sa.or_(
                    col(CostRecord.model).ilike(term),
                    col(CostRecord.agent_name).ilike(term),
                    col(CostRecord.request_id).ilike(term),
                )
            )
        return predicates

    def _order_by(self, filters: CostFilter):
        if filters.sort == CostSortDirection.OLDEST_FIRST:
            return [col(CostRecord.occurred_at).asc(), col(CostRecord.request_id).asc()]
        if filters.sort == CostSortDirection.MOST_EXPENSIVE:
            return [col(CostRecord.spend).desc(), col(CostRecord.request_id).asc()]
        # request_id breaks ties on identical timestamps. Without it, two rows sharing
        # a millisecond can swap places between pages and the client sees a duplicate
        # while another row is skipped entirely.
        return [col(CostRecord.occurred_at).desc(), col(CostRecord.request_id).asc()]

    def find_paginated(
        self,
        window: StatsWindow,
        filters: CostFilter,
        pagination: Pagination,
    ) -> PaginatedItems[CostRecord]:
        predicates = self._predicates(window, filters)
        with Session(self.delegate.engine) as session:
            total = session.exec(select(sa.func.count()).select_from(CostRecord).where(*predicates)).one()
            rows = session.exec(
                select(CostRecord)
                .where(*predicates)
                .order_by(*self._order_by(filters))
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            ).all()
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=list(rows),
        )

    def totals(self, window: StatsWindow, filters: CostFilter) -> CostTotals:
        predicates = self._predicates(window, filters)
        # sa.select rather than sqlmodel's: the latter's typed overloads stop short of
        # six columns, and every one of these has to come from the same scan.
        query = sa.select(
            sa.func.coalesce(sa.func.sum(col(CostRecord.spend)), 0),
            sa.func.count(),
            sa.func.count(sa.distinct(col(CostRecord.agent_id))),
            sa.func.coalesce(sa.func.avg(col(CostRecord.prompt_tokens)), 0),
            sa.func.coalesce(sa.func.sum(col(CostRecord.prompt_tokens)), 0),
            sa.func.coalesce(sa.func.sum(col(CostRecord.completion_tokens)), 0),
        ).where(*predicates)
        # A plain connection, not a Session: this is a pure aggregate read with no ORM
        # objects involved, and SQLModel deprecates Session.execute.
        with self.delegate.engine.connect() as connection:
            row = connection.execute(query).one()
        return CostTotals(
            spend=Decimal(str(row[0])),
            calls=int(row[1]),
            agents=int(row[2]),
            avg_prompt_tokens=float(row[3]),
            prompt_tokens=int(row[4]),
            completion_tokens=int(row[5]),
        )

    def model_breakdown(
        self,
        window: StatsWindow,
        filters: CostFilter,
    ) -> list[tuple[str, Decimal, int, int]]:
        """Per-model spend and tokens, biggest spender first."""
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(
                    col(CostRecord.model),
                    sa.func.coalesce(sa.func.sum(col(CostRecord.spend)), 0).label("spend"),
                    sa.func.coalesce(sa.func.sum(col(CostRecord.prompt_tokens)), 0),
                    sa.func.coalesce(sa.func.sum(col(CostRecord.completion_tokens)), 0),
                )
                .where(*self._predicates(window, filters))
                .group_by(col(CostRecord.model))
                .order_by(sa.desc("spend"))
            ).all()
        return [(row[0], Decimal(str(row[1])), int(row[2]), int(row[3])) for row in rows]

    def top_model(self, window: StatsWindow, filters: CostFilter) -> tuple[str, Decimal] | None:
        predicates = self._predicates(window, filters)
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(
                    col(CostRecord.model),
                    sa.func.coalesce(sa.func.sum(col(CostRecord.spend)), 0).label("spend"),
                )
                .where(*predicates)
                .group_by(col(CostRecord.model))
                .order_by(sa.desc("spend"))
                .limit(1)
            ).first()
        return (row[0], Decimal(str(row[1]))) if row else None

    def spend_series(self, window: StatsWindow, filters: CostFilter) -> list[tuple[datetime, Decimal, int]]:
        """Spend and call count per bucket, with empty buckets filled in as zero.

        Left-joined onto generate_series rather than grouped alone: a quiet day has
        to render as a gap at zero, not vanish and pull the line across it.
        """
        unit = window.granularity.value
        buckets = self._bucket_series(window).subquery()
        totals = (
            select(
                sa.func.date_trunc(unit, sa.func.timezone("UTC", col(CostRecord.occurred_at))).label("bucket"),
                sa.func.sum(col(CostRecord.spend)).label("spend"),
                sa.func.count().label("calls"),
            )
            .where(*self._predicates(window, filters))
            .group_by(sa.text("1"))
            .subquery()
        )
        query = (
            select(
                buckets.c.bucket,
                sa.func.coalesce(totals.c.spend, 0),
                sa.func.coalesce(totals.c.calls, 0),
            )
            .select_from(buckets.outerjoin(totals, buckets.c.bucket == totals.c.bucket))
            .order_by(buckets.c.bucket)
        )
        with Session(self.delegate.engine) as session:
            return [(row[0], Decimal(str(row[1])), int(row[2])) for row in session.exec(query).all()]

    def avg_prompt_tokens_series(self, window: StatsWindow, filters: CostFilter) -> list[tuple[datetime, float]]:
        unit = window.granularity.value
        buckets = self._bucket_series(window).subquery()
        totals = (
            select(
                sa.func.date_trunc(unit, sa.func.timezone("UTC", col(CostRecord.occurred_at))).label("bucket"),
                sa.func.avg(col(CostRecord.prompt_tokens)).label("avg_prompt_tokens"),
            )
            .where(*self._predicates(window, filters))
            .group_by(sa.text("1"))
            .subquery()
        )
        query = (
            select(buckets.c.bucket, sa.func.coalesce(totals.c.avg_prompt_tokens, 0))
            .select_from(buckets.outerjoin(totals, buckets.c.bucket == totals.c.bucket))
            .order_by(buckets.c.bucket)
        )
        with Session(self.delegate.engine) as session:
            return [(row[0], float(row[1])) for row in session.exec(query).all()]

    def spend_by_agent_series(
        self,
        window: StatsWindow,
        filters: CostFilter,
        limit: int = TOP_AGENTS_IN_SERIES,
    ) -> list[tuple[datetime, UUID | None, str | None, Decimal]]:
        """Per-agent spend over time, restricted to the biggest spenders.

        A chart with one line per agent stops being readable well before an
        organization stops having agents, so only the top few by total spend get a
        line. Empty buckets are not filled here: the caller knows the bucket list from
        `spend_series` and a missing point for one agent means zero.
        """
        unit = window.granularity.value
        predicates = self._predicates(window, filters)
        with Session(self.delegate.engine) as session:
            top_agents = session.exec(
                select(col(CostRecord.agent_id))
                .where(*predicates)
                .group_by(col(CostRecord.agent_id))
                .order_by(sa.desc(sa.func.sum(col(CostRecord.spend))))
                .limit(limit)
            ).all()
            if not top_agents:
                return []
            rows = session.exec(
                select(
                    sa.func.date_trunc(unit, sa.func.timezone("UTC", col(CostRecord.occurred_at))).label("bucket"),
                    col(CostRecord.agent_id),
                    sa.func.max(col(CostRecord.agent_name)),
                    sa.func.sum(col(CostRecord.spend)),
                )
                .where(*predicates, col(CostRecord.agent_id).in_(top_agents))
                .group_by(sa.text("1"), col(CostRecord.agent_id))
                .order_by(sa.text("1"))
            ).all()
        return [(row[0], row[1], row[2], Decimal(str(row[3]))) for row in rows]

    def cost_per_call_histogram(
        self,
        window: StatsWindow,
        filters: CostFilter,
    ) -> list[tuple[Decimal, Decimal | None, int]]:
        """Distribution of per-call cost over fixed dollar bands.

        Fixed bands rather than bands derived from the data, so the shape is
        comparable between two filters and between two organizations. The last band is
        open-ended: a few very expensive calls are the thing worth seeing.
        """
        bounds = list(COST_HISTOGRAM_BOUNDS)
        bucket = sa.func.width_bucket(
            sa.cast(col(CostRecord.spend), sa.Numeric(20, 12)),
            sa.cast(sa.literal(bounds, sa.ARRAY(sa.Numeric(20, 12))), sa.ARRAY(sa.Numeric(20, 12))),
        ).label("band")
        query = (
            select(bucket, sa.func.count())
            .where(*self._predicates(window, filters))
            .group_by(sa.text("1"))
            .order_by(sa.text("1"))
        )
        with Session(self.delegate.engine) as session:
            counts = {int(row[0]): int(row[1]) for row in session.exec(query).all()}

        # width_bucket returns 0 below the first bound and len(bounds) above the last.
        # Band 0 is spend < the first bound, which includes the free calls.
        histogram: list[tuple[Decimal, Decimal | None, int]] = [(Decimal(0), bounds[0], counts.get(0, 0))]
        for index, lower in enumerate(bounds, start=1):
            upper = bounds[index] if index < len(bounds) else None
            histogram.append((lower, upper, counts.get(index, 0)))
        return histogram

    def distinct_models(self, window: StatsWindow, filters: CostFilter) -> list[str]:
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(col(CostRecord.model))
                .where(*self._predicates(window, filters))
                .group_by(col(CostRecord.model))
                .order_by(sa.desc(sa.func.sum(col(CostRecord.spend))))
            ).all()
        return [row for row in rows]

    def distinct_agents(
        self,
        window: StatsWindow,
        filters: CostFilter,
    ) -> list[tuple[UUID, str | None, str | None]]:
        """Agents that actually spent something, ordered by how much.

        Read from the cost table rather than the agent table on purpose: an agent
        deleted last month still has spend in the window, and its name still needs to
        appear in the filter that would surface it.
        """
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(
                    col(CostRecord.agent_id),
                    sa.func.max(col(CostRecord.agent_name)),
                    sa.func.max(col(CostRecord.organization_name)),
                )
                .where(*self._predicates(window, filters), col(CostRecord.agent_id).is_not(None))
                .group_by(col(CostRecord.agent_id))
                .order_by(sa.desc(sa.func.sum(col(CostRecord.spend))))
            ).all()
        # The SQL already excludes NULL agent_id; repeating it here is what makes the
        # narrowed return type true rather than merely intended.
        return [(row[0], row[1], row[2]) for row in rows if row[0] is not None]

    def _bucket_series(self, window: StatsWindow):
        unit = window.granularity.value
        return select(
            sa.func.generate_series(
                sa.func.date_trunc(unit, sa.func.timezone("UTC", sa.literal(window.start))),
                sa.func.date_trunc(unit, sa.func.timezone("UTC", sa.literal(window.end))),
                sa.text(f"interval '{window.granularity.interval}'"),
            ).label("bucket")
        )

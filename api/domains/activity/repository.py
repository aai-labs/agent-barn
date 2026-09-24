from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.activity.models import (
    USER_LEAD_SECONDS,
    WAKE_GAP_SECONDS,
    ActivityFilter,
    ActivityTrigger,
)
from api.domains.conversations.models import AgentChatMessage, MessageDirection
from api.domains.costs.models import CostRecord
from api.domains.platform_admin.models import StatsWindow
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination

_WAKE_GAP = sa.text(f"interval '{WAKE_GAP_SECONDS} seconds'")
_USER_LEAD = sa.text(f"interval '{USER_LEAD_SECONDS} seconds'")


@dataclass(frozen=True)
class CallTotals:
    calls: int = 0
    spend: Decimal = Decimal(0)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    avg_prompt_tokens: float = 0.0
    median_prompt_tokens: int = 0
    p95_prompt_tokens: int = 0
    max_prompt_tokens: int = 0
    last_call_at: datetime | None = None


@dataclass(frozen=True)
class WakeRow:
    started_at: datetime
    ended_at: datetime
    trigger: ActivityTrigger
    calls: int
    spend: Decimal
    prompt_tokens: int
    completion_tokens: int
    min_prompt_tokens: int
    max_prompt_tokens: int
    models: list[str]


@dataclass(frozen=True)
class TriggerTotals:
    trigger: ActivityTrigger
    wakes: int
    calls: int
    spend: Decimal
    prompt_tokens: int


@inject
@singleton
@dataclass
class ActivityRepository:
    """Reads one Agent's billed calls as work rather than as money.

    Everything here runs off `cost_record`, which holds one row per model call.
    Consecutive calls are grouped into *wakes* — bursts separated by more than
    `WAKE_GAP_SECONDS` — because a burst, not a call, is the unit a person
    recognises as a piece of work.

    A wake is labelled `USER` when an inbound message landed just before it, and
    `BACKGROUND` otherwise. Only the timing and direction of messages is read;
    never their content.
    """

    delegate: PostgresRepositoryDelegate

    # --- Shared shape ------------------------------------------------------

    def _predicates(self, agent_id: UUID, organization_id: UUID, window: StatsWindow) -> list:
        return [
            col(CostRecord.agent_id) == agent_id,
            col(CostRecord.organization_id) == organization_id,
            col(CostRecord.occurred_at) >= window.start,
            col(CostRecord.occurred_at) < window.end,
        ]

    def _wakes(self, agent_id: UUID, organization_id: UUID, window: StatsWindow):
        """Subquery of one row per wake, carrying its totals and its trigger."""
        previous = sa.func.lag(col(CostRecord.occurred_at)).over(order_by=col(CostRecord.occurred_at))
        marked = (
            sa.select(
                col(CostRecord.occurred_at).label("occurred_at"),
                col(CostRecord.spend).label("spend"),
                col(CostRecord.prompt_tokens).label("prompt_tokens"),
                col(CostRecord.completion_tokens).label("completion_tokens"),
                col(CostRecord.model).label("model"),
                sa.case(
                    (previous.is_(None), 1),
                    (col(CostRecord.occurred_at) - previous > _WAKE_GAP, 1),
                    else_=0,
                ).label("starts_wake"),
            )
            .where(*self._predicates(agent_id, organization_id, window))
            .subquery()
        )
        # A running sum over the gap markers numbers the wakes: every marker
        # increments it, so all the calls in one burst share an index.
        indexed = sa.select(
            marked.c.occurred_at,
            marked.c.spend,
            marked.c.prompt_tokens,
            marked.c.completion_tokens,
            marked.c.model,
            sa.func.sum(marked.c.starts_wake).over(order_by=marked.c.occurred_at).label("wake_index"),
        ).subquery()
        grouped = (
            sa.select(
                sa.func.min(indexed.c.occurred_at).label("started_at"),
                sa.func.max(indexed.c.occurred_at).label("ended_at"),
                sa.func.count().label("calls"),
                sa.func.sum(indexed.c.spend).label("spend"),
                sa.func.sum(indexed.c.prompt_tokens).label("prompt_tokens"),
                sa.func.sum(indexed.c.completion_tokens).label("completion_tokens"),
                sa.func.min(indexed.c.prompt_tokens).label("min_prompt_tokens"),
                sa.func.max(indexed.c.prompt_tokens).label("max_prompt_tokens"),
                sa.func.array_agg(sa.distinct(indexed.c.model)).label("models"),
            )
            .group_by(indexed.c.wake_index)
            .subquery()
        )
        user_triggered = (
            sa.select(sa.literal(1))
            .where(
                col(AgentChatMessage.agent_id) == agent_id,
                col(AgentChatMessage.direction) == MessageDirection.INBOUND,
                col(AgentChatMessage.occurred_at) >= grouped.c.started_at - _USER_LEAD,
                col(AgentChatMessage.occurred_at) <= grouped.c.ended_at,
            )
            .exists()
            .label("user_triggered")
        )
        return sa.select(*grouped.c, user_triggered).subquery()

    @staticmethod
    def _trigger_predicate(wakes, filters: ActivityFilter):
        if filters.trigger is None:
            return []
        return [wakes.c.user_triggered.is_(filters.trigger == ActivityTrigger.USER)]

    # --- Reads -------------------------------------------------------------

    def call_totals(self, agent_id: UUID, organization_id: UUID, window: StatsWindow) -> CallTotals:
        prompt_tokens = col(CostRecord.prompt_tokens)
        query = sa.select(
            sa.func.count(),
            sa.func.coalesce(sa.func.sum(col(CostRecord.spend)), 0),
            sa.func.coalesce(sa.func.sum(prompt_tokens), 0),
            sa.func.coalesce(sa.func.sum(col(CostRecord.completion_tokens)), 0),
            sa.func.coalesce(sa.func.avg(prompt_tokens), 0),
            # percentile_cont over an empty set is NULL, not zero.
            sa.func.coalesce(sa.func.percentile_cont(0.5).within_group(sa.asc(prompt_tokens)), 0),
            sa.func.coalesce(sa.func.percentile_cont(0.95).within_group(sa.asc(prompt_tokens)), 0),
            sa.func.coalesce(sa.func.max(prompt_tokens), 0),
            sa.func.max(col(CostRecord.occurred_at)),
        ).where(*self._predicates(agent_id, organization_id, window))
        with self.delegate.engine.connect() as connection:
            row = connection.execute(query).one()
        return CallTotals(
            calls=int(row[0]),
            spend=Decimal(str(row[1])),
            prompt_tokens=int(row[2]),
            completion_tokens=int(row[3]),
            avg_prompt_tokens=float(row[4]),
            median_prompt_tokens=int(row[5]),
            p95_prompt_tokens=int(row[6]),
            max_prompt_tokens=int(row[7]),
            last_call_at=row[8].astimezone(UTC) if row[8] else None,
        )

    def bucket_series(
        self,
        agent_id: UUID,
        organization_id: UUID,
        window: StatsWindow,
    ) -> list[tuple[datetime, int, int, int, Decimal]]:
        """Calls, tokens and spend per bucket, with quiet buckets filled in as zero."""
        unit = window.granularity.value
        buckets = sa.select(
            sa.func.generate_series(
                sa.func.date_trunc(unit, sa.func.timezone("UTC", sa.literal(window.start))),
                sa.func.date_trunc(unit, sa.func.timezone("UTC", sa.literal(window.end))),
                sa.text(f"interval '{window.granularity.interval}'"),
            ).label("bucket")
        ).subquery()
        totals = (
            sa.select(
                sa.func.date_trunc(unit, sa.func.timezone("UTC", col(CostRecord.occurred_at))).label("bucket"),
                sa.func.count().label("calls"),
                sa.func.sum(col(CostRecord.prompt_tokens)).label("prompt_tokens"),
                sa.func.sum(col(CostRecord.completion_tokens)).label("completion_tokens"),
                sa.func.sum(col(CostRecord.spend)).label("spend"),
            )
            .where(*self._predicates(agent_id, organization_id, window))
            .group_by(sa.text("1"))
            .subquery()
        )
        query = (
            sa.select(
                # date_trunc over a naive timestamp yields a naive one, which
                # serializes without a zone and would be read as local time by
                # anything formatting it. The buckets are UTC, so say so.
                sa.func.timezone("UTC", buckets.c.bucket),
                sa.func.coalesce(totals.c.calls, 0),
                sa.func.coalesce(totals.c.prompt_tokens, 0),
                sa.func.coalesce(totals.c.completion_tokens, 0),
                sa.func.coalesce(totals.c.spend, 0),
            )
            .select_from(buckets.outerjoin(totals, buckets.c.bucket == totals.c.bucket))
            .order_by(buckets.c.bucket)
        )
        with self.delegate.engine.connect() as connection:
            return [
                (row[0], int(row[1]), int(row[2]), int(row[3]), Decimal(str(row[4])))
                for row in connection.execute(query).all()
            ]

    def trigger_breakdown(
        self,
        agent_id: UUID,
        organization_id: UUID,
        window: StatsWindow,
    ) -> list[TriggerTotals]:
        wakes = self._wakes(agent_id, organization_id, window)
        query = sa.select(
            wakes.c.user_triggered,
            sa.func.count(),
            sa.func.sum(wakes.c.calls),
            sa.func.sum(wakes.c.spend),
            sa.func.sum(wakes.c.prompt_tokens),
        ).group_by(wakes.c.user_triggered)
        with self.delegate.engine.connect() as connection:
            rows = connection.execute(query).all()
        return [
            TriggerTotals(
                trigger=ActivityTrigger.USER if row[0] else ActivityTrigger.BACKGROUND,
                wakes=int(row[1]),
                calls=int(row[2]),
                spend=Decimal(str(row[3])),
                prompt_tokens=int(row[4]),
            )
            for row in rows
        ]

    def wake_cadence_seconds(self, agent_id: UUID, organization_id: UUID, window: StatsWindow) -> int | None:
        """Median gap between the starts of consecutive wakes.

        A schedule shows up as a steady number here; ad-hoc work does not.
        """
        wakes = self._wakes(agent_id, organization_id, window)
        gaps = sa.select(
            sa.func.extract(
                "epoch",
                wakes.c.started_at - sa.func.lag(wakes.c.started_at).over(order_by=wakes.c.started_at),
            ).label("gap")
        ).subquery()
        query = sa.select(sa.func.percentile_cont(0.5).within_group(sa.asc(gaps.c.gap))).where(gaps.c.gap.is_not(None))
        with self.delegate.engine.connect() as connection:
            value = connection.execute(query).scalar()
        return int(value) if value is not None else None

    def find_wakes(
        self,
        agent_id: UUID,
        organization_id: UUID,
        window: StatsWindow,
        filters: ActivityFilter,
        pagination: Pagination,
    ) -> PaginatedItems[WakeRow]:
        wakes = self._wakes(agent_id, organization_id, window)
        predicates = self._trigger_predicate(wakes, filters)
        count_query = sa.select(sa.func.count()).select_from(wakes).where(*predicates)
        page_query = (
            sa.select(wakes)
            .where(*predicates)
            .order_by(wakes.c.started_at.desc())
            .offset((pagination.page - 1) * pagination.size)
            .limit(pagination.size)
        )
        with self.delegate.engine.connect() as connection:
            total = connection.execute(count_query).scalar() or 0
            rows = connection.execute(page_query).mappings().all()
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=int(total),
            items=[
                WakeRow(
                    started_at=row["started_at"],
                    ended_at=row["ended_at"],
                    trigger=ActivityTrigger.USER if row["user_triggered"] else ActivityTrigger.BACKGROUND,
                    calls=int(row["calls"]),
                    spend=Decimal(str(row["spend"])),
                    prompt_tokens=int(row["prompt_tokens"]),
                    completion_tokens=int(row["completion_tokens"]),
                    min_prompt_tokens=int(row["min_prompt_tokens"]),
                    max_prompt_tokens=int(row["max_prompt_tokens"]),
                    models=sorted(row["models"] or []),
                )
                for row in rows
            ],
        )

    def find_calls(
        self,
        agent_id: UUID,
        organization_id: UUID,
        window: StatsWindow,
        filters: ActivityFilter,
        pagination: Pagination,
    ) -> PaginatedItems[CostRecord]:
        predicates = self._predicates(agent_id, organization_id, window)
        if filters.trigger is not None:
            # A call's trigger is its wake's trigger, so the two views cannot
            # disagree about which calls ran without a person.
            wakes = self._wakes(agent_id, organization_id, window)
            predicates.append(
                sa.select(sa.literal(1))
                .select_from(wakes)
                .where(
                    col(CostRecord.occurred_at) >= wakes.c.started_at,
                    col(CostRecord.occurred_at) <= wakes.c.ended_at,
                    *self._trigger_predicate(wakes, filters),
                )
                .exists()
            )
        with Session(self.delegate.engine) as session:
            total = session.exec(select(sa.func.count()).select_from(CostRecord).where(*predicates)).one()
            rows = session.exec(
                select(CostRecord)
                .where(*predicates)
                # request_id breaks ties: two rows sharing a millisecond would
                # otherwise swap places between pages.
                .order_by(col(CostRecord.occurred_at).desc(), col(CostRecord.request_id).asc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            ).all()
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=int(total),
            items=list(rows),
        )

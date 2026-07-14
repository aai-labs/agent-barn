import datetime
from collections.abc import Iterator
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import func, tuple_
from sqlmodel import Session, col, or_, select

from api.domains.audit_logs.models import (
    AuditLog,
    AuditLogFilter,
    AuditLogRead,
)
from api.domains.organizations.models import Organization
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination


@dataclass
class _OrgScope:
    """Resolved visibility for a list/export query. ``organization_id`` set = restrict to
    that org; ``all_orgs`` = no org restriction (superuser scope=all, includes NULL-org
    global events)."""

    organization_id: UUID | None = None
    all_orgs: bool = False


def _parse_date(value: str | None) -> datetime.date | None:
    if not value:
        return None
    try:
        return datetime.date.fromisoformat(value[:10])
    except ValueError:
        return None


@inject
@singleton
@dataclass
class AuditLogRepository:
    delegate: PostgresRepositoryDelegate

    def save(self, audit_log: AuditLog) -> None:
        self.delegate.save(audit_log)

    @staticmethod
    def _base_query():
        # Left join so rows survive deletion of their org (org_name comes back NULL and
        # the read falls back to the raw UUID) and so NULL-org global rows are kept.
        return select(AuditLog, col(Organization.name).label("organization_name")).join(
            Organization,
            col(Organization.id) == col(AuditLog.organization_id),
            isouter=True,
        )

    @staticmethod
    def _apply_scope(query, scope: _OrgScope):
        if scope.all_orgs:
            return query
        return query.where(col(AuditLog.organization_id) == scope.organization_id)

    @staticmethod
    def _apply_filters(query, filters: AuditLogFilter):
        if filters.actor_user_id:
            query = query.where(col(AuditLog.actor_user_id) == filters.actor_user_id)
        if filters.action:
            query = query.where(col(AuditLog.action) == filters.action)
        if filters.target_type:
            query = query.where(col(AuditLog.target_type) == filters.target_type)
        if filters.target_id:
            query = query.where(col(AuditLog.target_id) == filters.target_id)
        if filters.search:
            term = f"%{filters.search}%"
            query = query.where(
                or_(
                    col(AuditLog.actor_email).ilike(term),
                    col(AuditLog.target_label).ilike(term),
                )
            )
        start = _parse_date(filters.start_date)
        if start:
            query = query.where(col(AuditLog.created_at) >= start)
        end = _parse_date(filters.end_date)
        if end:
            # inclusive of the end date — compare against the following midnight
            query = query.where(
                col(AuditLog.created_at) < end + datetime.timedelta(days=1)
            )
        return query

    @staticmethod
    def _to_read(row) -> AuditLogRead:
        audit_log, organization_name = row
        return AuditLogRead(
            **audit_log.model_dump(), organization_name=organization_name
        )

    def find_paginated(
        self,
        scope: _OrgScope,
        filters: AuditLogFilter,
        pagination: Pagination,
    ) -> PaginatedItems[AuditLogRead]:
        with Session(self.delegate.engine) as session:
            query = self._base_query()
            query = self._apply_scope(query, scope)
            query = self._apply_filters(query, filters)

            count_query = select(func.count()).select_from(AuditLog)
            count_query = self._apply_scope(count_query, scope)
            count_query = self._apply_filters(count_query, filters)
            total = session.scalar(count_query) or 0

            query = query.order_by(
                col(AuditLog.created_at).desc(), col(AuditLog.id).desc()
            )
            query = query.offset((pagination.page - 1) * pagination.size).limit(
                pagination.size
            )
            items = [self._to_read(row) for row in session.exec(query).all()]

            return PaginatedItems(
                page=pagination.page,
                page_size=pagination.size,
                total=total,
                items=items,
            )

    def iter_for_export(
        self,
        scope: _OrgScope,
        filters: AuditLogFilter,
        batch_size: int = 1000,
        max_rows: int = 100_000,
    ) -> Iterator[AuditLogRead]:
        """Yield rows newest-first via keyset pagination. Each batch runs in its own
        short-lived session so a slow client never pins a pooled connection for the whole
        stream. Stops after ``max_rows``; the route appends a truncation notice."""
        emitted = 0
        cursor: tuple[datetime.datetime, UUID] | None = None

        while emitted < max_rows:
            with Session(self.delegate.engine) as session:
                query = self._base_query()
                query = self._apply_scope(query, scope)
                query = self._apply_filters(query, filters)
                if cursor is not None:
                    last_created, last_id = cursor
                    # Row-value comparison: (created_at, id) < (last_created, last_id).
                    # Keeps keyset paging correct when rows share a timestamp.
                    query = query.where(
                        tuple_(col(AuditLog.created_at), col(AuditLog.id))
                        < tuple_(last_created, last_id)
                    )
                query = query.order_by(
                    col(AuditLog.created_at).desc(), col(AuditLog.id).desc()
                ).limit(batch_size)

                rows = session.exec(query).all()

            if not rows:
                return

            for row in rows:
                audit_log = row[0]
                yield self._to_read(row)
                cursor = (audit_log.created_at, audit_log.id)
                emitted += 1
                if emitted >= max_rows:
                    return

            if len(rows) < batch_size:
                return

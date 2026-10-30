from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from injector import inject, singleton
from sqlalchemy import and_, func, or_, update
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentRestorePoint, AgentStatus, RestorePointOrigin, RestorePointStatus
from api.domains.agents.repository import agent_scope_predicates
from api.domains.events.catalog import EVENT_REGISTRY
from api.domains.events.models import ActorIdentity, EventDelivery, SubjectIdentity, SubjectIdentityType
from api.domains.events.repository import OutboxMessageRepository
from api.domains.rbac.policy import AuthorizationScope
from api.domains.restore_points.models import (
    ACTIVE_CAPTURE_STATUSES,
    AGENT_VOLUME_BUSY_STATUSES,
    AUTOMATIC_BACKUP_ORIGINS,
    MANUAL_GROUP_ORIGINS,
    NON_TERMINAL_STATUSES,
    AgentRestorePointRead,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import PaginatedItems, Pagination


@dataclass
class RestorePointEventResult:
    restore_point: AgentRestorePoint
    delivery_ids: list[UUID]


@inject
@singleton
@dataclass
class RestorePointRepository:
    delegate: PostgresRepositoryDelegate
    outbox_repository: OutboxMessageRepository

    def find_by_agent(
        self,
        agent_id: UUID,
        pagination: Pagination,
        authorization_scope: AuthorizationScope,
    ) -> PaginatedItems[AgentRestorePointRead]:
        with Session(self.delegate.engine) as session:
            visibility = agent_scope_predicates(authorization_scope)
            predicates = (col(AgentRestorePoint.agent_id) == agent_id, *visibility)

            count_query = (
                select(func.count())
                .select_from(AgentRestorePoint)
                .join(Agent, col(Agent.id) == col(AgentRestorePoint.agent_id))
                .where(*predicates)
            )
            total = session.scalar(count_query) or 0

            query = (
                select(AgentRestorePoint)
                .join(Agent, col(Agent.id) == col(AgentRestorePoint.agent_id))
                .where(*predicates)
                .order_by(col(AgentRestorePoint.created_at).desc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            )
            rows = list(session.exec(query).all())

        return PaginatedItems[AgentRestorePointRead](
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=[AgentRestorePointRead.model_validate(row) for row in rows],
        )

    def get_by_id(self, restore_point_id: UUID) -> AgentRestorePoint | None:
        """The row itself, with no authorization scope.

        Callers that already hold the Agent — the orchestrator waiting on a row
        it just requested — need the row, not a scoped read.
        """
        with Session(self.delegate.engine) as session:
            return session.get(AgentRestorePoint, restore_point_id)

    def get_in_scope(
        self,
        restore_point_id: UUID,
        agent_id: UUID,
        authorization_scope: AuthorizationScope,
    ) -> AgentRestorePoint | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentRestorePoint)
                .join(Agent, col(Agent.id) == col(AgentRestorePoint.agent_id))
                .where(
                    col(AgentRestorePoint.id) == restore_point_id,
                    col(AgentRestorePoint.agent_id) == agent_id,
                    *agent_scope_predicates(authorization_scope),
                )
            )
            return session.exec(query).first()

    def count_manual_for_agent(self, agent_id: UUID) -> int:
        """Restore points a user took that still hold a volume."""
        return self.count_holding_a_volume(agent_id, (RestorePointOrigin.MANUAL,))

    def count_holding_a_volume(self, agent_id: UUID, origins: tuple[RestorePointOrigin, ...]) -> int:
        """Restore points of these origins that still hold a volume.

        FAILED ones released theirs when they failed, so counting them would let a run
        of failures block an Agent from ever taking another.
        """
        with Session(self.delegate.engine) as session:
            query = (
                select(func.count())
                .select_from(AgentRestorePoint)
                .where(
                    col(AgentRestorePoint.agent_id) == agent_id,
                    col(AgentRestorePoint.origin).in_(origins),
                    col(AgentRestorePoint.status) != RestorePointStatus.FAILED,
                )
            )
            return session.scalar(query) or 0

    def find_for_agent_by_origin(
        self,
        agent_id: UUID,
        origins: tuple[RestorePointOrigin, ...],
        statuses: tuple[RestorePointStatus, ...],
    ) -> list[AgentRestorePoint]:
        """Oldest first."""
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentRestorePoint)
                .where(
                    col(AgentRestorePoint.agent_id) == agent_id,
                    col(AgentRestorePoint.origin).in_(origins),
                    col(AgentRestorePoint.status).in_(statuses),
                )
                .order_by(col(AgentRestorePoint.created_at))
            )
            return list(session.exec(query).all())

    def find_in_flight_scheduled(self) -> list[AgentRestorePoint]:
        with Session(self.delegate.engine) as session:
            query = select(AgentRestorePoint).where(
                col(AgentRestorePoint.origin) == RestorePointOrigin.SCHEDULED,
                col(AgentRestorePoint.status).in_(NON_TERMINAL_STATUSES),
            )
            return list(session.exec(query).all())

    def find_agent_ids_due_a_snapshot(self, *, last_taken_before: datetime) -> list[UUID]:
        """Running Agents whose newest scheduled snapshot, in any status, is older than the cutoff.

        Any status, so a failed attempt waits a full interval before the next one. The
        Agents that never had one come first, then the longest waiting.
        """
        newest = (
            select(
                col(AgentRestorePoint.agent_id).label("agent_id"),
                func.max(AgentRestorePoint.created_at).label("taken_at"),
            )
            .where(col(AgentRestorePoint.origin) == RestorePointOrigin.SCHEDULED)
            .group_by(col(AgentRestorePoint.agent_id))
            .subquery()
        )
        with Session(self.delegate.engine) as session:
            query = (
                select(col(Agent.id))
                .outerjoin(newest, newest.c.agent_id == col(Agent.id))
                .where(
                    col(Agent.status) == AgentStatus.RUNNING,
                    col(Agent.deleted_at).is_(None),
                    or_(newest.c.taken_at.is_(None), newest.c.taken_at < last_taken_before),
                )
                .order_by(newest.c.taken_at.asc().nulls_first())
            )
            return list(session.exec(query).all())

    def find_agent_ids_over_retention(self, *, scheduled_cap: int, manual_cap: int) -> list[UUID]:
        """Agents retention would remove a restore point from, by the rules of `enforce_retention`.

        Over a limit is not enough: a user's captures, the newest automatic backup and a
        restore point owing a replay are never removed, so an Agent over only because of
        those is left out rather than returned on every run.
        """
        ready = col(AgentRestorePoint.status) == RestorePointStatus.READY
        failed = col(AgentRestorePoint.status) == RestorePointStatus.FAILED
        removable = and_(ready, col(AgentRestorePoint.reapply_configuration).is_(False))
        scheduled = col(AgentRestorePoint.origin) == RestorePointOrigin.SCHEDULED
        manual_group = col(AgentRestorePoint.origin).in_(MANUAL_GROUP_ORIGINS)
        automatic = col(AgentRestorePoint.origin).in_(AUTOMATIC_BACKUP_ORIGINS)
        with Session(self.delegate.engine) as session:
            query = (
                select(col(AgentRestorePoint.agent_id))
                .group_by(col(AgentRestorePoint.agent_id))
                .having(
                    or_(
                        and_(
                            func.count().filter(and_(scheduled, ready)) > scheduled_cap,
                            func.count().filter(and_(scheduled, removable)) > 0,
                        ),
                        and_(
                            func.count().filter(and_(manual_group, ready)) > manual_cap,
                            func.count().filter(and_(automatic, removable)) > 1,
                        ),
                        func.count().filter(and_(scheduled, failed)) > 1,
                    )
                )
            )
            return list(session.exec(query).all())

    def mark_deleting(self, restore_point_id: UUID, *, from_statuses: tuple[RestorePointStatus, ...]) -> bool:
        return self._conditional_update(
            restore_point_id,
            from_statuses,
            {"status": RestorePointStatus.DELETING},
        )

    def has_active_capture(self, agent_id: UUID) -> bool:
        return self._exists_with_status(agent_id, ACTIVE_CAPTURE_STATUSES)

    def has_agent_volume_operation(self, agent_id: UUID, *, ignoring: tuple[RestorePointOrigin, ...] = ()) -> bool:
        return self._exists_with_status(agent_id, AGENT_VOLUME_BUSY_STATUSES, ignoring=ignoring)

    def find_owing_replay_for_agent(self, agent_id: UUID) -> list[AgentRestorePoint]:
        """Rows whose volume is back but whose recorded configuration is not written.

        READY only, never FAILED: a restore that did not succeed must not have its
        configuration applied. The flag outlives the status, so a process that stops
        between marking the restore done and writing the configuration leaves work
        the next read finds.
        """
        with Session(self.delegate.engine) as session:
            query = select(AgentRestorePoint).where(
                col(AgentRestorePoint.agent_id) == agent_id,
                col(AgentRestorePoint.reapply_configuration).is_(True),
                col(AgentRestorePoint.status) == RestorePointStatus.READY,
            )
            return list(session.exec(query).all())

    def claim_reconciliation_candidates(
        self,
        *,
        stale_before: datetime,
        limit: int,
        skip_locked: bool = True,
        claimed_at: datetime | None = None,
    ) -> list[AgentRestorePoint]:
        claimed_at = claimed_at or datetime.now(UTC)
        statement = (
            select(AgentRestorePoint)
            .where(
                col(AgentRestorePoint.updated_at) <= stale_before,
                or_(
                    col(AgentRestorePoint.status).in_(NON_TERMINAL_STATUSES),
                    and_(
                        col(AgentRestorePoint.status) == RestorePointStatus.READY,
                        col(AgentRestorePoint.reapply_configuration).is_(True),
                    ),
                ),
            )
            .order_by(col(AgentRestorePoint.updated_at))
            .limit(limit)
            .with_for_update(skip_locked=skip_locked)
        )
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            rows = list(session.exec(statement))
            for row in rows:
                row.updated_at = claimed_at
                session.add(row)
            session.commit()
            return rows

    def find_ready_rows_missing_volumes(self, live_pvc_names: set[str], limit: int) -> list[AgentRestorePoint]:
        with Session(self.delegate.engine) as session:
            query = (
                select(AgentRestorePoint)
                .where(
                    col(AgentRestorePoint.status) == RestorePointStatus.READY,
                    col(AgentRestorePoint.pvc_name).not_in(live_pvc_names),
                )
                .order_by(col(AgentRestorePoint.created_at))
                .limit(limit)
            )
            return list(session.exec(query).all())

    def find_existing_ids(self, restore_point_ids: set[UUID]) -> set[UUID]:
        if not restore_point_ids:
            return set()
        with Session(self.delegate.engine) as session:
            query = select(col(AgentRestorePoint.id)).where(col(AgentRestorePoint.id).in_(restore_point_ids))
            return set(session.exec(query).all())

    def mark_ready_row_failed(self, restore_point_id: UUID, reason: str) -> bool:
        return self._conditional_update(
            restore_point_id,
            (RestorePointStatus.READY,),
            {
                "status": RestorePointStatus.FAILED,
                "failure_reason": reason,
                "job_name": None,
                "reapply_configuration": False,
            },
        )

    def find_non_terminal_for_agent(self, agent_id: UUID) -> list[AgentRestorePoint]:
        with Session(self.delegate.engine) as session:
            query = select(AgentRestorePoint).where(
                col(AgentRestorePoint.agent_id) == agent_id,
                col(AgentRestorePoint.status).in_(NON_TERMINAL_STATUSES),
            )
            return list(session.exec(query).all())

    def update_status(
        self,
        restore_point_id: UUID,
        new_status: RestorePointStatus,
        *,
        from_statuses: tuple[RestorePointStatus, ...],
    ) -> bool:
        return self._conditional_update(restore_point_id, from_statuses, {"status": new_status})

    def mark_ready(
        self,
        restore_point_id: UUID,
        *,
        archive_bytes: int | None,
        file_count: int | None,
    ) -> bool:
        return self._conditional_update(
            restore_point_id,
            NON_TERMINAL_STATUSES,
            {
                "status": RestorePointStatus.READY,
                "archive_bytes": archive_bytes,
                "file_count": file_count,
                "captured_at": datetime.now(UTC),
                "failure_reason": None,
                "job_name": None,
            },
        )

    def mark_restored(self, restore_point_id: UUID, *, cancel_replay: bool = False) -> bool:
        return self._conditional_update(
            restore_point_id,
            (RestorePointStatus.RESTORING,),
            {
                "status": RestorePointStatus.READY,
                "failure_reason": None,
                "job_name": None,
                **({"reapply_configuration": False, "configuration_error": None} if cancel_replay else {}),
            },
        )

    def mark_restore_retryable(self, restore_point_id: UUID, reason: str) -> bool:
        return self._conditional_update(
            restore_point_id,
            (RestorePointStatus.RESTORING,),
            {"status": RestorePointStatus.READY, "failure_reason": reason, "job_name": None},
        )

    def mark_failed_restore_target_ready(self, restore_point_id: UUID) -> bool:
        return self._conditional_update(
            restore_point_id,
            (RestorePointStatus.FAILED,),
            {"status": RestorePointStatus.READY, "failure_reason": None},
        )

    def mark_configuration_failed(self, restore_point_id: UUID, reason: str) -> None:
        """Record why replay could not complete and clear its pending intent."""
        with Session(self.delegate.engine) as session:
            session.exec(
                update(AgentRestorePoint)
                .where(col(AgentRestorePoint.id) == restore_point_id)
                .values(reapply_configuration=False, configuration_error=reason)
            )
            session.commit()

    def mark_failed(self, restore_point_id: UUID, reason: str) -> bool:
        return self._conditional_update(
            restore_point_id,
            NON_TERMINAL_STATUSES,
            {
                "status": RestorePointStatus.FAILED,
                "failure_reason": reason,
                "job_name": None,
                "reapply_configuration": False,
            },
        )

    def _conditional_update(
        self,
        restore_point_id: UUID,
        from_statuses: tuple[RestorePointStatus, ...],
        values: dict,
    ) -> bool:
        with Session(self.delegate.engine) as session:
            result = session.exec(
                update(AgentRestorePoint)
                .where(
                    col(AgentRestorePoint.id) == restore_point_id,
                    col(AgentRestorePoint.status).in_(from_statuses),
                )
                .values(**values, updated_at=datetime.now(UTC))
            )
            session.commit()
            return bool(result.rowcount)

    def delete(self, restore_point_id: UUID) -> bool:
        return self.delegate.delete_one(AgentRestorePoint, restore_point_id)

    def delete_for_agent(self, agent_id: UUID) -> None:
        with Session(self.delegate.engine) as session:
            query = select(AgentRestorePoint).where(col(AgentRestorePoint.agent_id) == agent_id)
            rows = list(session.exec(query).all())
        if rows:
            self.delegate.delete_many(rows)

    def save(self, restore_point: AgentRestorePoint) -> AgentRestorePoint:
        self.delegate.save(restore_point)
        return restore_point

    def save_with_event(
        self,
        restore_point: AgentRestorePoint,
        *,
        event_name: str,
        actor: ActorIdentity,
        payload: dict,
    ) -> RestorePointEventResult:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            session.add(restore_point)
            session.flush()
            delivery_ids = self._stage(session, restore_point, event_name, actor, payload)
            session.commit()
            return RestorePointEventResult(restore_point=restore_point, delivery_ids=delivery_ids)

    def update_status_with_event(
        self,
        restore_point_id: UUID,
        new_status: RestorePointStatus,
        *,
        from_statuses: tuple[RestorePointStatus, ...],
        job_name: str | None,
        event_name: str,
        actor: ActorIdentity,
        payload: dict,
        reapply_configuration: bool = False,
        backup_skipped_by_user: bool = False,
        restored_by_user_id: UUID | None = None,
        restored_by_display: str | None = None,
    ) -> RestorePointEventResult | None:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            row = session.exec(
                select(AgentRestorePoint)
                .where(
                    col(AgentRestorePoint.id) == restore_point_id,
                    col(AgentRestorePoint.status).in_(from_statuses),
                )
                .with_for_update()
            ).first()
            if row is None:
                return None
            row.status = new_status
            row.job_name = job_name
            # Stored with the transition so the intent and the operation it belongs to
            # are written together, and reconciliation can find it later.
            row.reapply_configuration = reapply_configuration
            row.configuration_error = None
            row.backup_skipped_by_user = backup_skipped_by_user
            row.restored_by_user_id = restored_by_user_id
            row.restored_by_display = restored_by_display
            row.updated_at = datetime.now(UTC)
            session.add(row)
            session.flush()
            delivery_ids = self._stage(session, row, event_name, actor, payload)
            session.commit()
            return RestorePointEventResult(restore_point=row, delivery_ids=delivery_ids)

    def delete_with_event(
        self,
        restore_point: AgentRestorePoint,
        *,
        event_name: str,
        actor: ActorIdentity,
        payload: dict,
    ) -> list[UUID]:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            delivery_ids = self._stage(session, restore_point, event_name, actor, payload)
            row = session.get(AgentRestorePoint, restore_point.id)
            if row is not None:
                session.delete(row)
            session.commit()
            return delivery_ids

    def _stage(
        self,
        session: Session,
        restore_point: AgentRestorePoint,
        event_name: str,
        actor: ActorIdentity,
        payload: dict,
    ) -> list[UUID]:
        organization_id = payload["organization_id"]
        event = EVENT_REGISTRY.build_event(
            event_name=event_name,
            schema_version=1,
            occurred_at=datetime.now(UTC),
            organization_id=organization_id,
            actor=actor,
            subject=SubjectIdentity(
                type=SubjectIdentityType.AGENT,
                id=restore_point.agent_id,
                organization_id=organization_id,
            ),
            correlation_id=uuid4(),
            payload=payload,
        )
        self.outbox_repository.stage(session=session, registry=EVENT_REGISTRY, event=event)
        return list(session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id)))

    def _exists_with_status(
        self,
        agent_id: UUID,
        statuses: tuple[RestorePointStatus, ...],
        *,
        ignoring: tuple[RestorePointOrigin, ...] = (),
    ) -> bool:
        with Session(self.delegate.engine) as session:
            query = (
                select(col(AgentRestorePoint.id))
                .where(
                    col(AgentRestorePoint.agent_id) == agent_id,
                    col(AgentRestorePoint.status).in_(statuses),
                    col(AgentRestorePoint.origin).not_in(ignoring),
                )
                .limit(1)
            )
            return session.exec(query).first() is not None

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlalchemy import and_, func
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent
from api.domains.agents.repository import agent_scope_predicates
from api.domains.rbac.policy import AuthorizationScope
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationUser
from api.domains.workflows.models import (
    Workflow,
    WorkflowDraft,
    WorkflowVersion,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class Unchanged:
    """Distinguishes "leave the default Agent as it is" from "clear it"."""


UNCHANGED = Unchanged()


class WorkflowConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkflowCreator:
    membership_id: UUID
    user_id: UUID | None
    name: str | None


@dataclass(frozen=True)
class WorkflowSummaryRow:
    id: UUID
    created_by_membership_id: UUID | None
    default_agent_id: UUID | None
    revision: int
    archived_at: datetime | None
    version_id: UUID
    number: int
    created_at: datetime
    created_by_user_id: UUID | None
    name: str
    description: str
    step_count: int
    input_count: int


@inject
@singleton
@dataclass
class WorkflowRepository:
    """Definitions are scoped by Organization; callers authorize the Member before reading."""

    delegate: PostgresRepositoryDelegate

    def version(self, version_id: UUID, workflow_id: UUID, organization_id: UUID) -> WorkflowVersion | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(WorkflowVersion)
                .join(Workflow, col(Workflow.id) == col(WorkflowVersion.workflow_id))
                .where(
                    col(WorkflowVersion.id) == version_id,
                    col(Workflow.id) == workflow_id,
                    col(Workflow.organization_id) == organization_id,
                )
            ).one_or_none()

    def list_workflows(
        self,
        organization_id: UUID,
        page: int,
        size: int,
        *,
        created_by_membership_id: UUID | None = None,
        archived: bool | None = None,
    ) -> tuple[list[WorkflowSummaryRow], int]:
        """Latest version of each definition, projected in SQL so lists never load full snapshots."""
        predicates = [col(Workflow.organization_id) == organization_id]
        if created_by_membership_id is not None:
            predicates.append(col(Workflow.created_by_membership_id) == created_by_membership_id)
        if archived is not None:
            archived_at = col(Workflow.archived_at)
            predicates.append(archived_at.is_not(None) if archived else archived_at.is_(None))
        latest = (
            select(WorkflowVersion.workflow_id, func.max(WorkflowVersion.number).label("number"))
            .join(Workflow, col(Workflow.id) == col(WorkflowVersion.workflow_id))
            .where(col(Workflow.organization_id) == organization_id)
            .group_by(col(WorkflowVersion.workflow_id))
            .subquery()
        )
        snapshot = col(WorkflowVersion.snapshot)
        with Session(self.delegate.engine) as session:
            query = (
                sa.select(
                    col(Workflow.id),
                    col(Workflow.created_by_membership_id),
                    col(Workflow.default_agent_id),
                    col(Workflow.revision),
                    col(Workflow.archived_at),
                    col(WorkflowVersion.id),
                    col(WorkflowVersion.number),
                    col(WorkflowVersion.created_at),
                    col(WorkflowVersion.created_by_user_id),
                    snapshot["name"].astext,
                    snapshot["description"].astext,
                    func.jsonb_array_length(snapshot["steps"]),
                    func.coalesce(func.jsonb_array_length(snapshot["inputs"]), 0),
                )
                .select_from(Workflow)
                .join(latest, latest.c.workflow_id == col(Workflow.id))
                .join(
                    WorkflowVersion,
                    and_(
                        col(WorkflowVersion.workflow_id) == col(Workflow.id),
                        col(WorkflowVersion.number) == latest.c.number,
                    ),
                )
                .where(*predicates)
            )
            total = session.exec(select(func.count()).select_from(Workflow).where(*predicates)).one()
            rows = session.connection().execute(
                query.order_by(col(Workflow.created_at).desc(), col(Workflow.id)).offset((page - 1) * size).limit(size)
            )
            return [WorkflowSummaryRow(*row) for row in rows], total

    def get(self, workflow_id: UUID, organization_id: UUID) -> Workflow | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(Workflow).where(
                    col(Workflow.id) == workflow_id, col(Workflow.organization_id) == organization_id
                )
            ).one_or_none()

    def versions(
        self,
        workflow_id: UUID,
        organization_id: UUID,
        page: int = 1,
        size: int = 20,
        max_number: int | None = None,
    ) -> tuple[list[WorkflowVersion], int]:
        with Session(self.delegate.engine) as session:
            query = (
                select(WorkflowVersion)
                .join(Workflow, col(Workflow.id) == col(WorkflowVersion.workflow_id))
                .where(col(Workflow.id) == workflow_id, col(Workflow.organization_id) == organization_id)
            )
            if max_number is not None:
                query = query.where(col(WorkflowVersion.number) <= max_number)
            total = session.exec(select(func.count()).select_from(query.subquery())).one()
            rows = session.exec(
                query.order_by(col(WorkflowVersion.number).desc()).offset((page - 1) * size).limit(size)
            ).all()
            return list(rows), total

    def creators(self, membership_ids: Iterable[UUID | None]) -> dict[UUID, WorkflowCreator]:
        membership_ids = {item for item in membership_ids if item is not None}
        if not membership_ids:
            return {}
        with Session(self.delegate.engine) as session:
            rows = session.exec(
                select(OrganizationUser.id, OrganizationUser.user_id, User.full_name)
                .outerjoin(User, col(User.id) == col(OrganizationUser.user_id))
                .where(col(OrganizationUser.id).in_(membership_ids))
            ).all()
            return {row[0]: WorkflowCreator(*row) for row in rows}

    def readable_agent_ids(self, agent_ids: Iterable[UUID | None], scope: AuthorizationScope) -> set[UUID]:
        """The active Agents among these that the scope may read."""
        agent_ids = {item for item in agent_ids if item is not None}
        if not agent_ids:
            return set()
        with Session(self.delegate.engine) as session:
            return set(
                session.exec(select(Agent.id).where(col(Agent.id).in_(agent_ids), *agent_scope_predicates(scope)))
            )

    def create(
        self,
        organization_id: UUID,
        membership_id: UUID,
        draft: WorkflowDraft,
        user_id: UUID,
        default_agent_id: UUID | None,
    ) -> Workflow:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            workflow = Workflow(
                organization_id=organization_id,
                created_by_membership_id=membership_id,
                default_agent_id=default_agent_id,
            )
            session.add(workflow)
            session.flush()
            session.add(
                WorkflowVersion(
                    workflow_id=workflow.id,
                    number=1,
                    snapshot=draft.model_dump(mode="json"),
                    created_by_user_id=user_id,
                )
            )
            session.commit()
            return workflow

    def change(
        self,
        workflow_id: UUID,
        organization_id: UUID,
        expected_revision: int,
        user_id: UUID,
        *,
        draft: WorkflowDraft | None = None,
        archive: bool = False,
        default_agent_id: UUID | None | Unchanged = UNCHANGED,
    ) -> Workflow:
        """Save a version, archive, or change the default Agent, under the workflow's revision."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            workflow = session.exec(
                select(Workflow)
                .where(col(Workflow.id) == workflow_id, col(Workflow.organization_id) == organization_id)
                .with_for_update(of=Workflow)
            ).one_or_none()
            if workflow is None or workflow.revision != expected_revision or workflow.archived_at is not None:
                raise WorkflowConflict(
                    "Workflow changed or was archived; reload its current revision before saving. Your draft can be kept."
                )
            if archive:
                workflow.archived_at = datetime.now(UTC)
            if not isinstance(default_agent_id, Unchanged):
                workflow.default_agent_id = default_agent_id
            if draft is not None:
                number = (
                    session.exec(
                        select(func.max(WorkflowVersion.number)).where(col(WorkflowVersion.workflow_id) == workflow_id)
                    ).one()
                    or 0
                )
                session.add(
                    WorkflowVersion(
                        workflow_id=workflow_id,
                        number=number + 1,
                        snapshot=draft.model_dump(mode="json"),
                        created_by_user_id=user_id,
                    )
                )
            workflow.revision += 1
            workflow.updated_at = datetime.now(UTC)
            session.add(workflow)
            session.commit()
            return workflow

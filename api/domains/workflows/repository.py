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
from api.domains.workflows.models import (
    Workflow,
    WorkflowDraft,
    WorkflowVersion,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


class WorkflowConflict(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkflowSummaryRow:
    id: UUID
    agent_id: UUID
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
    delegate: PostgresRepositoryDelegate

    def version_in_scope(
        self, version_id: UUID, workflow_id: UUID, agent_id: UUID, scope: AuthorizationScope
    ) -> WorkflowVersion | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(WorkflowVersion)
                .join(Workflow, col(Workflow.id) == col(WorkflowVersion.workflow_id))
                .join(Agent, col(Agent.id) == col(Workflow.agent_id))
                .where(
                    col(WorkflowVersion.id) == version_id,
                    col(Workflow.id) == workflow_id,
                    col(Workflow.agent_id) == agent_id,
                    *agent_scope_predicates(scope),
                )
            ).one_or_none()

    def list_in_scope(
        self, agent_id: UUID, scope: AuthorizationScope, page: int, size: int
    ) -> tuple[list[WorkflowSummaryRow], int]:
        """Latest version of each visible definition, projected in SQL so lists never load full snapshots."""
        predicates = (col(Workflow.agent_id) == agent_id, *agent_scope_predicates(scope))
        latest = (
            select(WorkflowVersion.workflow_id, func.max(WorkflowVersion.number).label("number"))
            .join(Workflow, col(Workflow.id) == col(WorkflowVersion.workflow_id))
            .where(col(Workflow.agent_id) == agent_id)
            .group_by(col(WorkflowVersion.workflow_id))
            .subquery()
        )
        snapshot = col(WorkflowVersion.snapshot)
        with Session(self.delegate.engine) as session:
            query = (
                sa.select(
                    col(Workflow.id),
                    col(Workflow.agent_id),
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
                .join(Agent, col(Agent.id) == col(Workflow.agent_id))
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
            total = session.exec(
                select(func.count())
                .select_from(Workflow)
                .join(Agent, col(Agent.id) == col(Workflow.agent_id))
                .where(*predicates)
            ).one()
            rows = session.connection().execute(
                query.order_by(col(Workflow.created_at).desc(), col(Workflow.id)).offset((page - 1) * size).limit(size)
            )
            return [WorkflowSummaryRow(*row) for row in rows], total

    def get_in_scope(self, workflow_id: UUID, agent_id: UUID, scope: AuthorizationScope) -> Workflow | None:
        with Session(self.delegate.engine) as session:
            return session.exec(
                select(Workflow)
                .join(Agent, col(Agent.id) == col(Workflow.agent_id))
                .where(
                    col(Workflow.id) == workflow_id, col(Workflow.agent_id) == agent_id, *agent_scope_predicates(scope)
                )
            ).one_or_none()

    def versions_in_scope(
        self,
        workflow_id: UUID,
        agent_id: UUID,
        scope: AuthorizationScope,
        page: int = 1,
        size: int = 20,
        max_number: int | None = None,
    ) -> tuple[list[WorkflowVersion], int]:
        with Session(self.delegate.engine) as session:
            query = (
                select(WorkflowVersion)
                .join(Workflow, col(Workflow.id) == col(WorkflowVersion.workflow_id))
                .join(Agent, col(Agent.id) == col(Workflow.agent_id))
                .where(
                    col(Workflow.id) == workflow_id, col(Workflow.agent_id) == agent_id, *agent_scope_predicates(scope)
                )
            )
            if max_number is not None:
                query = query.where(col(WorkflowVersion.number) <= max_number)
            total = session.exec(select(func.count()).select_from(query.subquery())).one()
            rows = session.exec(
                query.order_by(col(WorkflowVersion.number).desc()).offset((page - 1) * size).limit(size)
            ).all()
            return list(rows), total

    def create(self, agent_id: UUID, draft: WorkflowDraft, user_id: UUID, scope: AuthorizationScope) -> Workflow:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            if (
                session.exec(
                    select(Agent).where(col(Agent.id) == agent_id, *agent_scope_predicates(scope))
                ).one_or_none()
                is None
            ):
                raise WorkflowConflict("Agent access changed; refresh before saving")
            workflow = Workflow(agent_id=agent_id)
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

    def save_version(
        self,
        workflow_id: UUID,
        agent_id: UUID,
        scope: AuthorizationScope,
        expected_revision: int,
        draft: WorkflowDraft | None,
        user_id: UUID,
    ) -> Workflow:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            workflow = session.exec(
                select(Workflow)
                .join(Agent, col(Agent.id) == col(Workflow.agent_id))
                .where(
                    col(Workflow.id) == workflow_id, col(Workflow.agent_id) == agent_id, *agent_scope_predicates(scope)
                )
                .with_for_update(of=Workflow)
            ).one_or_none()
            if workflow is None or workflow.revision != expected_revision or workflow.archived_at is not None:
                raise WorkflowConflict(
                    "Workflow changed or was archived; reload its current revision before saving. Your draft can be kept."
                )
            if draft is None:
                workflow.archived_at = datetime.now(UTC)
            else:
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

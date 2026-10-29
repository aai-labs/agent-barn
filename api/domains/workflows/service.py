from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.workflows.models import (
    Workflow,
    WorkflowCapabilitiesRead,
    WorkflowDraft,
    WorkflowRead,
    WorkflowSummaryRead,
    WorkflowVersion,
    WorkflowVersionCreate,
    WorkflowVersionRead,
    WorkflowVersionSummaryRead,
)
from api.domains.workflows.platform_repository import PlatformWorkflowRepository
from api.domains.workflows.repository import WorkflowConflict, WorkflowRepository, WorkflowSummaryRow
from api.infrastructure.shared.models import PaginatedItems


@inject
@singleton
@dataclass
class WorkflowService:
    repository: WorkflowRepository
    authorization: AgentAuthorization
    settings: PlatformWorkflowRepository

    def _authoring_enabled(self) -> bool:
        return self.settings.read().authoring_enabled

    def capabilities(self, agent_id: UUID, context: CurrentUserContext) -> WorkflowCapabilitiesRead:
        self.authorization.require_visible(context, agent_id)
        return WorkflowCapabilitiesRead(
            authoring=self._authoring_enabled(),
            execution=True,
        )

    def _require_authoring(self, agent_id: UUID, context: CurrentUserContext) -> None:
        self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        if not self._authoring_enabled():
            raise HTTPException(409, "Workflow authoring is disabled for this installation")

    def _read(self, workflow: Workflow, context: CurrentUserContext) -> WorkflowRead:
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
        versions, _ = self.repository.versions_in_scope(
            workflow.id, workflow.agent_id, scope, size=1, max_number=workflow.revision
        )
        if not versions:
            raise HTTPException(404, "Workflow is unavailable")
        agent = self.authorization.require_visible(context, workflow.agent_id)
        permitted = self.authorization.allowed_actions(context, [agent])[agent.id]
        return self._snapshot_read(
            workflow, versions[0], PermissionKey.AGENT_UPDATE in permitted and self._authoring_enabled()
        )

    def _actions(self, archived_at: datetime | None, can_author: bool) -> list[Literal["save_version", "archive"]]:
        if can_author and archived_at is None:
            return ["save_version", "archive"]
        return []

    def _snapshot_read(self, workflow: Workflow, version: WorkflowVersion, can_author: bool) -> WorkflowRead:
        return WorkflowRead(
            id=workflow.id,
            agent_id=workflow.agent_id,
            revision=workflow.revision,
            archived_at=workflow.archived_at,
            version=self._version_read(version),
            allowed_actions=self._actions(workflow.archived_at, can_author),
            execution_available=True and workflow.archived_at is None,
        )

    def _summary_read(self, row: WorkflowSummaryRow, can_author: bool) -> WorkflowSummaryRead:
        return WorkflowSummaryRead(
            id=row.id,
            agent_id=row.agent_id,
            revision=row.revision,
            archived_at=row.archived_at,
            version=WorkflowVersionSummaryRead(
                id=row.version_id,
                number=row.number,
                created_at=row.created_at,
                created_by_user_id=row.created_by_user_id,
                name=row.name,
                description=row.description,
                step_count=row.step_count,
                input_count=row.input_count,
            ),
            allowed_actions=self._actions(row.archived_at, can_author),
            execution_available=True and row.archived_at is None,
        )

    @staticmethod
    def _version_read(version: WorkflowVersion) -> WorkflowVersionRead:
        return WorkflowVersionRead(
            id=version.id,
            number=version.number,
            created_at=version.created_at,
            created_by_user_id=version.created_by_user_id,
            draft=WorkflowDraft.model_validate(version.snapshot),
        )

    def list_workflows(
        self, agent_id: UUID, context: CurrentUserContext, page: int, size: int
    ) -> PaginatedItems[WorkflowSummaryRead]:
        agent = self.authorization.require_visible(context, agent_id)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
        rows, total = self.repository.list_in_scope(agent_id, scope, page, size)
        permissions = self.authorization.allowed_actions(context, [agent])[agent.id]
        can_author = PermissionKey.AGENT_UPDATE in permissions and self._authoring_enabled()
        return PaginatedItems(
            page,
            size,
            total,
            [self._summary_read(row, can_author) for row in rows],
        )

    def get(self, agent_id: UUID, workflow_id: UUID, context: CurrentUserContext) -> WorkflowRead:
        self.authorization.require_visible(context, agent_id)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
        row = self.repository.get_in_scope(workflow_id, agent_id, scope)
        if row is None:
            raise HTTPException(404, "Workflow not found")
        return self._read(row, context)

    def versions(
        self, agent_id: UUID, workflow_id: UUID, context: CurrentUserContext, page: int, size: int
    ) -> PaginatedItems[WorkflowVersionRead]:
        self.get(agent_id, workflow_id, context)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)
        rows, total = self.repository.versions_in_scope(workflow_id, agent_id, scope, page, size)
        return PaginatedItems(page, size, total, [self._version_read(row) for row in rows])

    def create(self, agent_id: UUID, draft: WorkflowDraft, context: CurrentUserContext) -> WorkflowRead:
        self._require_authoring(agent_id, context)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)
        try:
            return self._read(self.repository.create(agent_id, draft, context.user.id, scope), context)
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc

    def save(
        self, agent_id: UUID, workflow_id: UUID, payload: WorkflowVersionCreate, context: CurrentUserContext
    ) -> WorkflowRead:
        self._require_authoring(agent_id, context)
        self.get(agent_id, workflow_id, context)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)
        try:
            return self._read(
                self.repository.save_version(
                    workflow_id, agent_id, scope, payload.expected_revision, payload.draft, context.user.id
                ),
                context,
            )
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc

    def archive(self, agent_id: UUID, workflow_id: UUID, revision: int, context: CurrentUserContext) -> None:
        self._require_authoring(agent_id, context)
        self.get(agent_id, workflow_id, context)
        scope = self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)
        try:
            self.repository.save_version(workflow_id, agent_id, scope, revision, None, context.user.id)
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc

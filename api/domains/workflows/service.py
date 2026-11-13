from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from fastapi import HTTPException
from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.api_keys.models import ApiKeyAccessMode
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.domains.workflows.models import (
    Workflow,
    WorkflowCapabilitiesRead,
    WorkflowCreate,
    WorkflowCreatorRead,
    WorkflowDraft,
    WorkflowRead,
    WorkflowSummaryRead,
    WorkflowUpdate,
    WorkflowVersion,
    WorkflowVersionCreate,
    WorkflowVersionRead,
    WorkflowVersionSummaryRead,
)
from api.domains.workflows.platform_repository import PlatformWorkflowRepository
from api.domains.workflows.repository import (
    UNCHANGED,
    Unchanged,
    WorkflowConflict,
    WorkflowCreator,
    WorkflowRepository,
    WorkflowSummaryRow,
)
from api.infrastructure.shared.models import PaginatedItems

_GOAL_LIMIT = 4000


def fold_step_outputs(draft: WorkflowDraft) -> WorkflowDraft:
    """A step's expected output is part of its goal; fold the earlier separate field into it."""
    steps = []
    for index, step in enumerate(draft.steps, start=1):
        if step.artifact_description is not None:
            goal = f"{step.goal}\n\nOutput: {step.artifact_description}"
            if len(goal) > _GOAL_LIMIT:
                raise HTTPException(
                    422,
                    f"Step {index}: the goal and its output description together exceed {_GOAL_LIMIT} characters; "
                    "shorten the goal",
                )
            step = step.model_copy(update={"goal": goal, "artifact_description": None})
        steps.append(step)
    return draft.model_copy(update={"steps": steps})


@inject
@singleton
@dataclass
class WorkflowService:
    """Workflow definitions belong to the Organization; any Member reads them and creates their own."""

    repository: WorkflowRepository
    policy: PermissionPolicy
    agents: AgentAuthorization
    settings: PlatformWorkflowRepository

    def _authoring_enabled(self) -> bool:
        return self.settings.read().authoring_enabled

    def _member(self, organization_id: UUID, context: CurrentUserContext) -> None:
        self.policy.require_organization(context, organization_id, PermissionKey.ORGANIZATION_READ)

    def _can_manage(
        self, organization_id: UUID, created_by_membership_id: UUID | None, context: CurrentUserContext
    ) -> bool:
        """A workflow is changed or archived by its creator or with ``workflow.manage``."""
        if context.api_key_access_mode == ApiKeyAccessMode.READ_ONLY:
            return False
        if context.require_current_user_organization().id == created_by_membership_id:
            return True
        return self.policy.resolve(context, organization_id, PermissionKey.WORKFLOW_MANAGE) is not None

    def _require_authoring(self) -> None:
        if not self._authoring_enabled():
            raise HTTPException(409, "Workflow authoring is disabled for this installation")

    def _require_manage(self, organization_id: UUID, workflow_id: UUID, context: CurrentUserContext) -> Workflow:
        self._member(organization_id, context)
        workflow = self._found(organization_id, workflow_id)
        if not self._can_manage(organization_id, workflow.created_by_membership_id, context):
            raise HTTPException(403, "Only the workflow's creator or an Organization Owner or Admin can change it")
        self._require_authoring()
        return workflow

    def _found(self, organization_id: UUID, workflow_id: UUID) -> Workflow:
        workflow = self.repository.get(workflow_id, organization_id)
        if workflow is None:
            raise HTTPException(404, "Workflow not found")
        return workflow

    def _default_agent(self, agent_id: UUID | None, context: CurrentUserContext) -> UUID | None:
        """A default Agent must be one the author can see; it grants nobody anything."""
        if agent_id is not None:
            self.agents.require_visible(context, agent_id)
        return agent_id

    def _readable_agents(self, agent_ids: set[UUID | None], context: CurrentUserContext) -> dict[UUID, str]:
        scope = self.agents.authorization_scope(context, PermissionKey.AGENT_READ)
        return self.repository.readable_agents(agent_ids, scope)

    def capabilities(self, organization_id: UUID, context: CurrentUserContext) -> WorkflowCapabilitiesRead:
        self._member(organization_id, context)
        return WorkflowCapabilitiesRead(authoring=self._authoring_enabled(), execution=True)

    def _actions(self, archived_at: datetime | None, can_author: bool) -> list[Literal["save_version", "archive"]]:
        if can_author and archived_at is None:
            return ["save_version", "archive"]
        return []

    @staticmethod
    def _creator(creators: dict[UUID, WorkflowCreator], membership_id: UUID | None) -> WorkflowCreatorRead | None:
        creator = creators.get(membership_id) if membership_id else None
        if creator is None:
            return None
        return WorkflowCreatorRead(membership_id=creator.membership_id, user_id=creator.user_id, name=creator.name)

    def _read(self, workflow: Workflow, context: CurrentUserContext) -> WorkflowRead:
        versions, _ = self.repository.versions(
            workflow.id, workflow.organization_id, size=1, max_number=workflow.revision
        )
        if not versions:
            raise HTTPException(404, "Workflow is unavailable")
        creators = self.repository.creators([workflow.created_by_membership_id])
        readable = self._readable_agents({workflow.default_agent_id}, context)
        can_author = (
            self._can_manage(workflow.organization_id, workflow.created_by_membership_id, context)
            and self._authoring_enabled()
        )
        return WorkflowRead(
            id=workflow.id,
            created_by=self._creator(creators, workflow.created_by_membership_id),
            default_agent_id=workflow.default_agent_id if workflow.default_agent_id in readable else None,
            revision=workflow.revision,
            archived_at=workflow.archived_at,
            version=self._version_read(versions[0]),
            allowed_actions=self._actions(workflow.archived_at, can_author),
            execution_available=workflow.archived_at is None,
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
        self,
        organization_id: UUID,
        context: CurrentUserContext,
        page: int,
        size: int,
        *,
        created_by_me: bool = False,
        archived: bool | None = None,
    ) -> PaginatedItems[WorkflowSummaryRead]:
        self._member(organization_id, context)
        membership_id = context.require_current_user_organization().id
        rows, total = self.repository.list_workflows(
            organization_id,
            page,
            size,
            created_by_membership_id=membership_id if created_by_me else None,
            archived=archived,
        )
        creators = self.repository.creators(row.created_by_membership_id for row in rows)
        readable = self._readable_agents({row.default_agent_id for row in rows}, context)
        run_counts = self.repository.run_counts(
            (row.id for row in rows), self.agents.authorization_scope(context, PermissionKey.AGENT_READ)
        )
        authoring = self._authoring_enabled()
        return PaginatedItems(
            page,
            size,
            total,
            [
                self._summary_read(
                    organization_id, row, creators, readable, run_counts.get(row.id, 0), authoring, context
                )
                for row in rows
            ],
        )

    def _summary_read(
        self,
        organization_id: UUID,
        row: WorkflowSummaryRow,
        creators: dict[UUID, WorkflowCreator],
        readable: dict[UUID, str],
        run_count: int,
        authoring: bool,
        context: CurrentUserContext,
    ) -> WorkflowSummaryRead:
        can_author = authoring and self._can_manage(organization_id, row.created_by_membership_id, context)
        return WorkflowSummaryRead(
            id=row.id,
            created_by=self._creator(creators, row.created_by_membership_id),
            default_agent_id=row.default_agent_id if row.default_agent_id in readable else None,
            default_agent_name=readable.get(row.default_agent_id) if row.default_agent_id else None,
            run_count=run_count,
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
            execution_available=row.archived_at is None,
        )

    def get(self, organization_id: UUID, workflow_id: UUID, context: CurrentUserContext) -> WorkflowRead:
        self._member(organization_id, context)
        return self._read(self._found(organization_id, workflow_id), context)

    def versions(
        self, organization_id: UUID, workflow_id: UUID, context: CurrentUserContext, page: int, size: int
    ) -> PaginatedItems[WorkflowVersionRead]:
        self._member(organization_id, context)
        self._found(organization_id, workflow_id)
        rows, total = self.repository.versions(workflow_id, organization_id, page, size)
        return PaginatedItems(page, size, total, [self._version_read(row) for row in rows])

    def create(self, organization_id: UUID, payload: WorkflowCreate, context: CurrentUserContext) -> WorkflowRead:
        self._member(organization_id, context)
        self._require_authoring()
        workflow = self.repository.create(
            organization_id,
            context.require_current_user_organization().id,
            fold_step_outputs(payload.draft),
            context.user.id,
            self._default_agent(payload.default_agent_id, context),
        )
        return self._read(workflow, context)

    def save(
        self, organization_id: UUID, workflow_id: UUID, payload: WorkflowVersionCreate, context: CurrentUserContext
    ) -> WorkflowRead:
        self._require_manage(organization_id, workflow_id, context)
        return self._change(
            organization_id, workflow_id, payload.expected_revision, context, draft=fold_step_outputs(payload.draft)
        )

    def update(
        self, organization_id: UUID, workflow_id: UUID, payload: WorkflowUpdate, context: CurrentUserContext
    ) -> WorkflowRead:
        self._require_manage(organization_id, workflow_id, context)
        return self._change(
            organization_id,
            workflow_id,
            payload.expected_revision,
            context,
            default_agent_id=self._default_agent(payload.default_agent_id, context),
        )

    def archive(self, organization_id: UUID, workflow_id: UUID, revision: int, context: CurrentUserContext) -> None:
        self._require_manage(organization_id, workflow_id, context)
        self._change(organization_id, workflow_id, revision, context, archive=True)

    def _change(
        self,
        organization_id: UUID,
        workflow_id: UUID,
        revision: int,
        context: CurrentUserContext,
        *,
        draft: WorkflowDraft | None = None,
        archive: bool = False,
        default_agent_id: UUID | None | Unchanged = UNCHANGED,
    ) -> WorkflowRead:
        try:
            workflow = self.repository.change(
                workflow_id,
                organization_id,
                revision,
                context.user.id,
                draft=draft,
                archive=archive,
                default_agent_id=default_agent_id,
            )
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        return self._read(workflow, context)

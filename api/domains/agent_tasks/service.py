from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agent_tasks.models import (
    AgentTaskCreate,
    AgentTaskDetail,
    AgentTaskFileCreate,
    AgentTaskFileRead,
    AgentTaskFilter,
    AgentTaskNoteCreate,
    AgentTaskNoteRead,
    AgentTaskRead,
    AgentTaskStatus,
)
from api.domains.agent_tasks.repository import AgentTaskRepository
from api.domains.agents.authorization import AgentAuthorization
from api.domains.artifacts.models import ArtifactLinkRead
from api.domains.artifacts.service import ArtifactService
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.shared.models import PaginatedItems, Pagination

# The Artifact pin kind for Task Files; each pin's owner is the File's id.
_TASK_FILE_PIN = "task"


def _task_not_found(task_id: UUID) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Task {task_id} not found")


@inject
@singleton
@dataclass
class AgentTaskService:
    """Tasks are written by their own Agent and read by people who may read the Agent's Tasks.

    The write methods take the Agent's identity rather than a person's: the caller has
    already authenticated the Agent, so there is no Permission to check.
    """

    repository: AgentTaskRepository
    artifacts: ArtifactService
    agent_authorization: AgentAuthorization

    def create_task(self, organization_id: UUID, agent_id: UUID, data: AgentTaskCreate) -> AgentTaskRead:
        task = self.repository.create_for_live_agent(organization_id, agent_id, data)
        if task is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found")
        return AgentTaskRead.model_validate(task)

    def update_status(
        self, organization_id: UUID, agent_id: UUID, task_id: UUID, task_status: AgentTaskStatus
    ) -> AgentTaskRead:
        task = self.repository.update_status(organization_id, agent_id, task_id, task_status)
        if task is None:
            raise _task_not_found(task_id)
        return AgentTaskRead.model_validate(task)

    def add_note(
        self, organization_id: UUID, agent_id: UUID, task_id: UUID, data: AgentTaskNoteCreate
    ) -> AgentTaskNoteRead:
        note = self.repository.add_note(organization_id, agent_id, task_id, data.body)
        if note is None:
            raise _task_not_found(task_id)
        return AgentTaskNoteRead.model_validate(note)

    def attach_file(
        self, organization_id: UUID, agent_id: UUID, task_id: UUID, data: AgentTaskFileCreate
    ) -> AgentTaskFileRead:
        """Attach one of the Agent's own published Artifacts; attaching it again returns the same File."""
        stored = self.repository.add_file(
            organization_id,
            agent_id,
            task_id,
            data.artifact_id,
            lambda session, file_id: self.artifacts.pin(
                session, data.artifact_id, agent_id, organization_id, _TASK_FILE_PIN, file_id
            ),
        )
        if stored is None:
            raise _task_not_found(task_id)
        return AgentTaskFileRead.model_validate(stored)

    def file_link(self, agent_id: UUID, task_id: UUID, file_id: UUID, context: CurrentUserContext) -> ArtifactLinkRead:
        scope = self._agent_read_scope(agent_id, context)
        stored = self.repository.get_file(agent_id, task_id, file_id, scope)
        if stored is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File {file_id} not found")
        return self.artifacts.link(stored.artifact_id, agent_id, scope)

    def list_agent_tasks(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        task_filter: AgentTaskFilter,
        pagination: Pagination,
    ) -> PaginatedItems[AgentTaskRead]:
        scope = self._agent_read_scope(agent_id, context)
        return self.repository.find_in_organization(
            task_filter.model_copy(update={"agent_id": agent_id}), pagination, scope
        )

    def list_organization_tasks(
        self,
        context: CurrentUserContext,
        task_filter: AgentTaskFilter,
        pagination: Pagination,
    ) -> PaginatedItems[AgentTaskRead]:
        scope = self.agent_authorization.authorization_scope(context, PermissionKey.TASK_READ)
        return self.repository.find_in_organization(task_filter, pagination, scope)

    def get_task(self, agent_id: UUID, task_id: UUID, context: CurrentUserContext) -> AgentTaskDetail:
        scope = self._agent_read_scope(agent_id, context)
        task = self.repository.get_detail(agent_id, task_id, scope)
        if task is None:
            raise _task_not_found(task_id)
        return task

    def _agent_read_scope(self, agent_id: UUID, context: CurrentUserContext) -> AuthorizationScope:
        agent = self.agent_authorization.require_visible(context, agent_id)
        return self.agent_authorization.require_action_for_visible(
            context, agent, PermissionKey.TASK_READ, detail="You don't have permission to view this Agent's Tasks."
        )

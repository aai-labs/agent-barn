from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agent_tasks.file_storage import TaskFileStorage
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
from api.domains.agent_tasks.repository import (
    AgentTaskRepository,
    EmptyTaskFileError,
    OrganizationTaskStorageFullError,
)
from api.domains.agents.authorization import AgentAuthorization
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import AuthorizationScope
from api.infrastructure.shared.models import PaginatedItems, Pagination


class _TaskFileTooLargeError(Exception):
    pass


def _within_file_limit(data: Iterable[bytes], max_bytes: int) -> Iterator[bytes]:
    """Pass the upload through, stopping as soon as it passes the per-file limit."""
    total = 0
    for piece in data:
        total += len(piece)
        if total > max_bytes:
            raise _TaskFileTooLargeError
        yield piece


def _file_too_large(max_bytes: int) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST, detail=f"The file is larger than the {max_bytes}-byte limit."
    )


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

    config: Config
    repository: AgentTaskRepository
    file_storage: TaskFileStorage
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

    @property
    def file_max_bytes(self) -> int:
        return self.config.task_file_max_bytes

    def refuse_oversized_file(self, size_bytes: int) -> None:
        """Refuse an upload whose declared size is already past the per-file limit, before reading it."""
        if size_bytes > self.config.task_file_max_bytes:
            raise _file_too_large(self.config.task_file_max_bytes)

    def attach_file(
        self,
        organization_id: UUID,
        agent_id: UUID,
        task_id: UUID,
        metadata: AgentTaskFileCreate,
        data: Iterable[bytes],
    ) -> AgentTaskFileRead:
        """Store an upload as it is read; it is refused as soon as it passes either limit."""
        max_bytes = self.config.task_file_max_bytes
        try:
            stored = self.repository.add_file(
                organization_id,
                agent_id,
                task_id,
                metadata,
                _within_file_limit(data, max_bytes),
                self.config.task_organization_storage_max_bytes,
            )
        except EmptyTaskFileError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="The file is empty.") from None
        except _TaskFileTooLargeError:
            raise _file_too_large(max_bytes) from None
        except OrganizationTaskStorageFullError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The file is larger than the space left for this Organization's Task Files.",
            ) from None
        if stored is None:
            raise _task_not_found(task_id)
        return AgentTaskFileRead.model_validate(stored)

    def list_own_tasks(
        self, organization_id: UUID, agent_id: UUID, task_status: AgentTaskStatus | None, pagination: Pagination
    ) -> PaginatedItems[AgentTaskRead]:
        """An Agent's own Tasks, for the Agent itself; a deleted Agent has none."""
        return self.repository.find_in_organization(
            AgentTaskFilter(agent_id=agent_id, status=task_status),
            pagination,
            AuthorizationScope(organization_id=organization_id),
        )

    def get_own_task(self, organization_id: UUID, agent_id: UUID, task_id: UUID) -> AgentTaskDetail:
        task = self.repository.get_detail(agent_id, task_id, AuthorizationScope(organization_id=organization_id))
        if task is None:
            raise _task_not_found(task_id)
        return task

    def remove_file(self, organization_id: UUID, agent_id: UUID, task_id: UUID, file_id: UUID) -> None:
        if not self.repository.remove_file(organization_id, agent_id, task_id, file_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File {file_id} not found")

    def read_file(
        self, agent_id: UUID, task_id: UUID, file_id: UUID, context: CurrentUserContext
    ) -> tuple[AgentTaskFileRead, Iterator[bytes]]:
        scope = self._agent_read_scope(agent_id, context)
        stored = self.repository.get_file(agent_id, task_id, file_id, scope)
        if stored is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File {file_id} not found")
        return AgentTaskFileRead.model_validate(stored), self.file_storage.read(stored.id)

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

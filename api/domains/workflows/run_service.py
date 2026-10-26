import math
from dataclasses import dataclass
from typing import Any, cast
from uuid import UUID

from fastapi import HTTPException
from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import AgentStatus, AgentType
from api.domains.auth.models import CurrentUserContext
from api.domains.events.dispatch import EventDeliveryDispatcher
from api.domains.rbac.catalog import PermissionKey
from api.domains.workflows.models import WorkflowDraft, WorkflowVersion
from api.domains.workflows.repository import WorkflowConflict, WorkflowRepository
from api.domains.workflows.run_models import (
    TERMINAL_STATES,
    AttemptFailure,
    AttemptRead,
    AttemptResult,
    RunState,
    WorkflowHistoryRead,
    WorkflowRun,
    WorkflowRunCreate,
    WorkflowRunRead,
)
from api.domains.workflows.run_repository import WorkflowRunRepository
from api.infrastructure.shared.models import PaginatedItems


def validate_inputs(draft: WorkflowDraft, values: dict) -> None:
    declared = {item.key: item for item in draft.inputs}
    if values.keys() - declared.keys():
        raise HTTPException(422, "Unknown workflow inputs")
    for key, item in declared.items():
        if key not in values:
            if item.required:
                raise HTTPException(422, f"{item.label} is required")
            continue
        value = values[key]
        valid = (
            (item.type == "text" and isinstance(value, str) and 0 < len(value.strip()) <= 16000)
            or (item.type == "boolean" and type(value) is bool)
            or (item.type == "number" and type(value) in {int, float} and math.isfinite(value))
        )
        if not valid:
            raise HTTPException(422, f"{item.label} must be a valid {item.type} input")


@inject
@singleton
@dataclass
class WorkflowRunService:
    repository: WorkflowRunRepository
    definitions: WorkflowRepository
    authorization: AgentAuthorization
    dispatcher: EventDeliveryDispatcher

    def _scope(self, agent_id: UUID, context: CurrentUserContext, *, write: bool = False):
        self.authorization.require_action(
            context, agent_id, PermissionKey.AGENT_UPDATE
        ) if write else self.authorization.require_visible(context, agent_id)
        return self.authorization.authorization_scope(
            context, PermissionKey.AGENT_UPDATE if write else PermissionKey.AGENT_READ
        )

    def _read(
        self,
        run: WorkflowRun,
        version: WorkflowVersion,
        agent_id: UUID,
        context: CurrentUserContext,
        can_cancel: bool | None = None,
        step_records: dict[int, dict[str, Any]] | None = None,
        attempt: AttemptRead | None = None,
    ) -> WorkflowRunRead:
        if can_cancel is None:
            agent = self.authorization.require_visible(context, agent_id)
            can_cancel = PermissionKey.AGENT_UPDATE in self.authorization.allowed_actions(context, [agent])[agent.id]
        return WorkflowRunRead(
            id=run.id,
            workflow_id=run.workflow_id,
            version_id=run.version_id,
            version_number=version.number,
            name=version.snapshot["name"],
            initiating_user_id=run.initiating_user_id,
            inputs=run.inputs,
            state=cast(RunState, run.state),
            revision=run.revision,
            next_step=run.next_step,
            generation=run.generation,
            steps=[
                {
                    "id": step["id"],
                    "name": step["name"],
                    "state": "COMPLETED"
                    if index < run.next_step
                    else "RUNNING"
                    if index == run.next_step and run.state == "RUNNING"
                    else "PENDING",
                    "summary": (step_records or {}).get(index, {}).get("summary"),
                    "started_at": (step_records or {}).get(index, {}).get("started_at"),
                    "completed_at": (step_records or {}).get(index, {}).get("completed_at"),
                }
                for index, step in enumerate(version.snapshot["steps"])
            ],
            reason=run.reason,
            final_summary=(step_records or {}).get(len(version.snapshot["steps"]) - 1, {}).get("summary")
            if run.state == "SUCCEEDED"
            else None,
            created_at=run.created_at,
            settled_at=run.settled_at,
            allowed_actions=["cancel"] if can_cancel and run.state not in TERMINAL_STATES | {"CANCELLING"} else [],
            attempt=attempt,
        )

    def get(self, agent_id: UUID, run_id: UUID, context: CurrentUserContext) -> WorkflowRunRead:
        found = self.repository.get(run_id, agent_id, self._scope(agent_id, context))
        if not found:
            raise HTTPException(404, "Workflow run not found")
        return self._read(
            *found,
            agent_id,
            context,
            step_records=self.repository.step_records(found[0].id),
            attempt=self.repository.current_attempt(found[0]),
        )

    def list_runs(
        self, agent_id: UUID, context: CurrentUserContext, page: int, size: int, workflow_id: UUID | None
    ) -> PaginatedItems[WorkflowRunRead]:
        rows, total = self.repository.list_runs(agent_id, self._scope(agent_id, context), page, size, workflow_id)
        agent = self.authorization.require_visible(context, agent_id)
        can_cancel = PermissionKey.AGENT_UPDATE in self.authorization.allowed_actions(context, [agent])[agent.id]
        return PaginatedItems(page, size, total, [self._read(*row, agent_id, context, can_cancel) for row in rows])

    def start(
        self, agent_id: UUID, workflow_id: UUID, payload: WorkflowRunCreate, context: CurrentUserContext
    ) -> WorkflowRunRead:
        scope = self._scope(agent_id, context, write=True)
        workflow = self.definitions.get_in_scope(workflow_id, agent_id, scope)
        if workflow is None:
            raise HTTPException(404, "Workflow not found")
        try:
            existing = self.repository.existing_start(workflow_id, agent_id, scope, payload, context.user.id)
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        if existing:
            return self.get(agent_id, existing, context)
        version = self.definitions.version_in_scope(payload.version_id, workflow_id, agent_id, scope)
        if version is None:
            raise HTTPException(404, "Saved workflow version not found")
        draft = WorkflowDraft.model_validate(version.snapshot)
        validate_inputs(draft, payload.inputs)
        agent = self.authorization.require_visible(context, agent_id)
        if agent.status != AgentStatus.RUNNING:
            raise HTTPException(409, "Start the Agent before running a workflow")
        # Steps run as sessions in this Agent, under its own tools, integrations, approvals and spend limits.
        runtime = AgentType(agent.agent_type).value
        try:
            run, delivery_ids = self.repository.start(
                workflow_id,
                agent_id,
                scope,
                payload,
                context.user.id,
                context.require_current_user_organization().id,
                runtime,
            )
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        self.dispatcher.enqueue_immediate(delivery_ids)
        return self.get(agent_id, run.id, context)

    def cancel(self, agent_id: UUID, run_id: UUID, revision: int, context: CurrentUserContext) -> WorkflowRunRead:
        self.get(agent_id, run_id, context)
        try:
            delivery_ids = self.repository.cancel(
                run_id, agent_id, self._scope(agent_id, context, write=True), revision
            )
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        self.dispatcher.enqueue_immediate(delivery_ids)
        return self.get(agent_id, run_id, context)

    def history(
        self, agent_id: UUID, run_id: UUID, context: CurrentUserContext, page: int, size: int
    ) -> PaginatedItems[WorkflowHistoryRead]:
        self.get(agent_id, run_id, context)
        rows, total = self.repository.history(run_id, agent_id, self._scope(agent_id, context), page, size)
        return PaginatedItems(
            page, size, total, [WorkflowHistoryRead.model_validate(row, from_attributes=True) for row in rows]
        )

    def result(self, attempt_id: UUID, token: str, result: AttemptResult) -> None:
        self.dispatcher.enqueue_immediate(self.repository.complete(attempt_id, token, result))

    def failure(self, attempt_id: UUID, token: str, failure: AttemptFailure) -> None:
        self.dispatcher.enqueue_immediate(self.repository.fail(attempt_id, token, failure))

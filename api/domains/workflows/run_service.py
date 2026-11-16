import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, cast
from uuid import UUID

from fastapi import HTTPException
from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent, AgentStatus, AgentType
from api.domains.auth.models import CurrentUserContext
from api.domains.events.dispatch import EventDeliveryDispatcher
from api.domains.rbac.catalog import PermissionKey
from api.domains.workflows.models import WorkflowDraft, WorkflowVersion
from api.domains.workflows.repository import WorkflowConflict, WorkflowRepository
from api.domains.workflows.run_models import (
    DECIDABLE_APPROVAL_STATES,
    TERMINAL_STATES,
    ApprovalDecisionCreate,
    ApprovalRead,
    AttemptFailure,
    AttemptRead,
    AttemptResult,
    RunState,
    WorkflowFileInput,
    WorkflowHistoryRead,
    WorkflowRun,
    WorkflowRunCreate,
    WorkflowRunRead,
    WorkflowRunRerun,
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
            (item.type == "file" and isinstance(value, WorkflowFileInput))
            or (item.type == "text" and isinstance(value, str) and 0 < len(value.strip()) <= 16000)
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
        can_write: bool | None = None,
        step_records: dict[int, dict[str, Any]] | None = None,
        attempt: AttemptRead | None = None,
        can_start: bool | None = None,
        approval: ApprovalRead | None = None,
        approvals: list[ApprovalRead] | None = None,
    ) -> WorkflowRunRead:
        if can_write is None or can_start is None:
            agent = self.authorization.require_visible(context, agent_id)
            can_write = PermissionKey.AGENT_UPDATE in self.authorization.allowed_actions(context, [agent])[agent.id]
            can_start = self._can_start(agent, bool(self.repository.archived_workflow_ids([run.workflow_id])))
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
                    "output_description": step.get("artifact_description"),
                    "artifacts": (step_records or {}).get(index, {}).get("artifacts", []),
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
            final_output_description=version.snapshot["steps"][-1].get("artifact_description"),
            final_artifacts=(step_records or {}).get(len(version.snapshot["steps"]) - 1, {}).get("artifacts", [])
            if run.state == "SUCCEEDED"
            else [],
            created_at=run.created_at,
            settled_at=run.settled_at,
            rerun_of_run_id=run.rerun_of_run_id,
            allowed_actions=self._allowed_actions(run, can_write, can_start, approval),
            attempt=attempt,
            approval=approval,
            approvals=approvals or [],
        )

    @staticmethod
    def _can_start(agent: Agent, archived: bool) -> bool:
        return agent.status == AgentStatus.RUNNING and not archived

    @staticmethod
    def _allowed_actions(
        run: WorkflowRun, can_write: bool, can_start: bool, approval: ApprovalRead | None = None
    ) -> list[Literal["cancel", "rerun", "decide"]]:
        if not can_write:
            return []
        if run.state in TERMINAL_STATES:
            # Retention removes the inputs a re-run would copy; starting needs a running Agent and a live workflow.
            return ["rerun"] if can_start and not run.content_expired else []
        if run.state == "CANCELLING":
            return []
        # A live request whose window has closed is about to park; deciding it would only conflict.
        decidable = approval is not None and (
            (approval.state == "LIVE" and run.state == "RUNNING" and approval.live_until > datetime.now(UTC))
            or (approval.state == "PARKED" and run.state == "AWAITING_APPROVAL")
        )
        return ["decide", "cancel"] if decidable else ["cancel"]

    def get(self, agent_id: UUID, run_id: UUID, context: CurrentUserContext) -> WorkflowRunRead:
        found = self.repository.get(run_id, agent_id, self._scope(agent_id, context))
        if not found:
            raise HTTPException(404, "Workflow run not found")
        step_records, attempt = self.repository.progress(found[0])
        request = self.repository.current_approval(found[0])
        approval = ApprovalRead.model_validate(request, from_attributes=True) if request else None
        approvals = [
            ApprovalRead.model_validate(item, from_attributes=True) for item in self.repository.approvals([found[0].id])
        ]
        return self._read(
            *found,
            agent_id,
            context,
            step_records=step_records,
            attempt=attempt,
            approval=approval,
            approvals=approvals,
        )

    def list_runs(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        page: int,
        size: int,
        workflow_id: UUID | None,
        awaiting_decision: bool = False,
    ) -> PaginatedItems[WorkflowRunRead]:
        rows, total = self.repository.list_runs(
            agent_id, self._scope(agent_id, context), page, size, workflow_id, awaiting_decision
        )
        # Only a request still awaiting a decision is shown in lists, for the approvals inbox.
        pending = {
            item.run_id: ApprovalRead.model_validate(item, from_attributes=True)
            for item in self.repository.approvals((run.id for run, _ in rows), DECIDABLE_APPROVAL_STATES)
        }
        agent = self.authorization.require_visible(context, agent_id)
        can_write = PermissionKey.AGENT_UPDATE in self.authorization.allowed_actions(context, [agent])[agent.id]
        archived = self.repository.archived_workflow_ids({run.workflow_id for run, _ in rows})
        return PaginatedItems(
            page,
            size,
            total,
            [
                self._read(
                    *row,
                    agent_id,
                    context,
                    can_write,
                    can_start=self._can_start(agent, row[0].workflow_id in archived),
                    approval=pending.get(row[0].id),
                )
                for row in rows
            ],
        )

    def start(
        self, agent_id: UUID, workflow_id: UUID, payload: WorkflowRunCreate, context: CurrentUserContext
    ) -> WorkflowRunRead:
        return self._start(agent_id, workflow_id, payload, context)

    def rerun(
        self, agent_id: UUID, run_id: UUID, payload: WorkflowRunRerun, context: CurrentUserContext
    ) -> WorkflowRunRead:
        """Start a new run of a settled run's own version and inputs, recording where it came from."""
        scope = self._scope(agent_id, context, write=True)
        found = self.repository.get(run_id, agent_id, scope)
        if not found:
            raise HTTPException(404, "Workflow run not found")
        source = found[0]
        if source.state not in TERMINAL_STATES:
            raise HTTPException(409, "Only a settled run can be run again")
        # Stored file inputs include display metadata; admission accepts only the pinned identity.
        inputs = {
            key: {"artifact_id": value["artifact_id"], "checksum": value["checksum"]}
            if isinstance(value, dict)
            else value
            for key, value in source.inputs.items()
        }
        create = WorkflowRunCreate(
            version_id=source.version_id, client_request_id=payload.client_request_id, inputs=inputs
        )
        return self._start(agent_id, source.workflow_id, create, context, source)

    def _start(
        self,
        agent_id: UUID,
        workflow_id: UUID,
        payload: WorkflowRunCreate,
        context: CurrentUserContext,
        rerun_of: WorkflowRun | None = None,
    ) -> WorkflowRunRead:
        scope = self._scope(agent_id, context, write=True)
        workflow = self.definitions.get_in_scope(workflow_id, agent_id, scope)
        if workflow is None:
            raise HTTPException(404, "Workflow not found")
        rerun_of_run_id = rerun_of.id if rerun_of else None
        try:
            existing = self.repository.existing_start(
                workflow_id, agent_id, scope, payload, context.user.id, rerun_of_run_id
            )
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        # A retry of a re-run that already started returns it, even after retention removed the inputs.
        if existing:
            return self.get(agent_id, existing, context)
        if rerun_of and rerun_of.content_expired:
            raise HTTPException(409, "This run's inputs were removed by retention; start a new run instead")
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
                rerun_of_run_id,
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

    def decide(
        self,
        agent_id: UUID,
        run_id: UUID,
        request_id: UUID,
        payload: ApprovalDecisionCreate,
        context: CurrentUserContext,
    ) -> WorkflowRunRead:
        """A person's verdict on one exact request; authority is checked now, not when it was raised."""
        self.get(agent_id, run_id, context)
        try:
            delivery_ids = self.repository.decide(
                run_id,
                request_id,
                agent_id,
                self._scope(agent_id, context, write=True),
                context.user.id,
                payload.decision == "approve",
                payload.guidance,
            )
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        self.dispatcher.enqueue_immediate(delivery_ids)
        return self.get(agent_id, run_id, context)

    def history(
        self,
        agent_id: UUID,
        run_id: UUID,
        context: CurrentUserContext,
        page: int,
        size: int,
        newest_first: bool = False,
    ) -> PaginatedItems[WorkflowHistoryRead]:
        self.get(agent_id, run_id, context)
        rows, total = self.repository.history(
            run_id, agent_id, self._scope(agent_id, context), page, size, newest_first
        )
        return PaginatedItems(
            page, size, total, [WorkflowHistoryRead.model_validate(row, from_attributes=True) for row in rows]
        )

    def result(self, attempt_id: UUID, token: str, result: AttemptResult) -> None:
        self.dispatcher.enqueue_immediate(self.repository.complete(attempt_id, token, result))

    def failure(self, attempt_id: UUID, token: str, failure: AttemptFailure) -> None:
        self.dispatcher.enqueue_immediate(self.repository.fail(attempt_id, token, failure))

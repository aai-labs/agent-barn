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
from api.domains.rbac.policy import AuthorizationScope
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
    """Runs are reached through the Agent that runs them: agent.read to see one, agent.update to act on it."""

    repository: WorkflowRunRepository
    definitions: WorkflowRepository
    authorization: AgentAuthorization
    dispatcher: EventDeliveryDispatcher

    def _read_scope(self, context: CurrentUserContext) -> AuthorizationScope:
        return self.authorization.authorization_scope(context, PermissionKey.AGENT_READ)

    def _write_scope(self, context: CurrentUserContext) -> AuthorizationScope:
        return self.authorization.authorization_scope(context, PermissionKey.AGENT_UPDATE)

    def _found(self, run_id: UUID, context: CurrentUserContext) -> tuple[WorkflowRun, WorkflowVersion]:
        found = self.repository.get(run_id, self._read_scope(context))
        if not found:
            raise HTTPException(404, "Workflow run not found")
        return found

    def _writable(self, run_id: UUID, context: CurrentUserContext) -> tuple[WorkflowRun, WorkflowVersion]:
        """A readable run the caller may also act on; its Agent must still exist."""
        found = self._found(run_id, context)
        agent = self.repository.agents([found[0].agent_id])[found[0].agent_id]
        if agent.deleted_at is not None:
            raise HTTPException(409, "This run's Agent was deleted; the run can only be read")
        self.authorization.require_action_for_visible(context, agent, PermissionKey.AGENT_UPDATE)
        return found

    def _can_write(self, agents: list[Agent], context: CurrentUserContext) -> set[UUID]:
        """The active Agents among these whose runs the caller may act on."""
        active = [agent for agent in agents if agent.deleted_at is None]
        permitted = self.authorization.allowed_actions(context, active)
        return {agent.id for agent in active if PermissionKey.AGENT_UPDATE in permitted[agent.id]}

    def _read(
        self,
        run: WorkflowRun,
        version: WorkflowVersion,
        agent: Agent,
        can_write: bool,
        archived: bool,
        step_records: dict[int, dict[str, Any]] | None = None,
        attempt: AttemptRead | None = None,
        approval: ApprovalRead | None = None,
        approvals: list[ApprovalRead] | None = None,
    ) -> WorkflowRunRead:
        return WorkflowRunRead(
            id=run.id,
            workflow_id=run.workflow_id,
            version_id=run.version_id,
            version_number=version.number,
            name=version.snapshot["name"],
            title=run.title,
            agent_id=agent.id,
            agent_name=agent.name,
            agent_archived=agent.deleted_at is not None,
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
            allowed_actions=self._allowed_actions(run, can_write, self._can_start(agent, archived), approval),
            attempt=attempt,
            approval=approval,
            approvals=approvals or [],
        )

    @staticmethod
    def _can_start(agent: Agent, archived: bool) -> bool:
        return agent.deleted_at is None and agent.status == AgentStatus.RUNNING and not archived

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

    def get(self, run_id: UUID, context: CurrentUserContext) -> WorkflowRunRead:
        run, version = self._found(run_id, context)
        agent = self.repository.agents([run.agent_id])[run.agent_id]
        step_records, attempt = self.repository.progress(run)
        request = self.repository.current_approval(run)
        approval = ApprovalRead.model_validate(request, from_attributes=True) if request else None
        approvals = [
            ApprovalRead.model_validate(item, from_attributes=True) for item in self.repository.approvals([run.id])
        ]
        return self._read(
            run,
            version,
            agent,
            agent.id in self._can_write([agent], context),
            bool(self.repository.archived_workflow_ids([run.workflow_id])),
            step_records=step_records,
            attempt=attempt,
            approval=approval,
            approvals=approvals,
        )

    def list_runs(
        self,
        context: CurrentUserContext,
        page: int,
        size: int,
        workflow_id: UUID | None = None,
        agent_id: UUID | None = None,
        awaiting_decision: bool = False,
        status: Literal["active", "settled"] | None = None,
    ) -> PaginatedItems[WorkflowRunRead]:
        """Runs across every Agent the caller can read, including Agents since deleted."""
        context.require_current_user_organization()
        rows, total = self.repository.list_runs(
            self._read_scope(context),
            page,
            size,
            workflow_id,
            agent_id,
            awaiting_decision,
            None if status is None else status == "settled",
        )
        # Only a request still awaiting a decision is shown in lists, for the approvals inbox.
        pending = {
            item.run_id: ApprovalRead.model_validate(item, from_attributes=True)
            for item in self.repository.approvals((run.id for run, _ in rows), DECIDABLE_APPROVAL_STATES)
        }
        agents = self.repository.agents(run.agent_id for run, _ in rows)
        writable = self._can_write(list(agents.values()), context)
        archived = self.repository.archived_workflow_ids({run.workflow_id for run, _ in rows})
        return PaginatedItems(
            page,
            size,
            total,
            [
                self._read(
                    run,
                    version,
                    agents[run.agent_id],
                    run.agent_id in writable,
                    run.workflow_id in archived,
                    approval=pending.get(run.id),
                )
                for run, version in rows
            ],
        )

    def start(self, payload: WorkflowRunCreate, context: CurrentUserContext) -> WorkflowRunRead:
        return self._start(payload, context)

    def rerun(self, run_id: UUID, payload: WorkflowRunRerun, context: CurrentUserContext) -> WorkflowRunRead:
        """Start a new run of a settled run's own version and inputs on the same Agent."""
        source, _ = self._writable(run_id, context)
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
            workflow_id=source.workflow_id,
            agent_id=source.agent_id,
            version_id=source.version_id,
            title=source.title,
            client_request_id=payload.client_request_id,
            inputs=inputs,
        )
        return self._start(create, context, source)

    def _start(
        self,
        payload: WorkflowRunCreate,
        context: CurrentUserContext,
        rerun_of: WorkflowRun | None = None,
    ) -> WorkflowRunRead:
        membership = context.require_current_user_organization()
        # Starting needs agent.update on the chosen Agent; the workflow itself is open to every Member.
        agent = self.authorization.require_action(context, payload.agent_id, PermissionKey.AGENT_UPDATE)
        scope = self._write_scope(context)
        if self.definitions.get(payload.workflow_id, membership.organization_id) is None:
            raise HTTPException(404, "Workflow not found")
        rerun_of_run_id = rerun_of.id if rerun_of else None
        try:
            existing = self.repository.existing_start(scope, payload, context.user.id, rerun_of_run_id)
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        # A retry of a re-run that already started returns it, even after retention removed the inputs.
        if existing:
            return self.get(existing, context)
        if rerun_of and rerun_of.content_expired:
            raise HTTPException(409, "This run's inputs were removed by retention; start a new run instead")
        version = self.definitions.version(payload.version_id, payload.workflow_id, membership.organization_id)
        if version is None:
            raise HTTPException(404, "Saved workflow version not found")
        draft = WorkflowDraft.model_validate(version.snapshot)
        validate_inputs(draft, payload.inputs)
        if agent.status != AgentStatus.RUNNING:
            raise HTTPException(409, "Start the Agent before running a workflow")
        # Steps run as sessions in this Agent, under its own tools, integrations, approvals and spend limits.
        runtime = AgentType(agent.agent_type).value
        try:
            run, delivery_ids = self.repository.start(
                scope,
                payload,
                context.user.id,
                membership.id,
                runtime,
                rerun_of_run_id,
            )
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        self.dispatcher.enqueue_immediate(delivery_ids)
        return self.get(run.id, context)

    def cancel(self, run_id: UUID, revision: int, context: CurrentUserContext) -> WorkflowRunRead:
        self._writable(run_id, context)
        try:
            delivery_ids = self.repository.cancel(run_id, self._write_scope(context), revision)
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        self.dispatcher.enqueue_immediate(delivery_ids)
        return self.get(run_id, context)

    def decide(
        self,
        run_id: UUID,
        request_id: UUID,
        payload: ApprovalDecisionCreate,
        context: CurrentUserContext,
    ) -> WorkflowRunRead:
        """A person's verdict on one exact request; authority is checked now, not when it was raised."""
        self._writable(run_id, context)
        try:
            delivery_ids = self.repository.decide(
                run_id,
                request_id,
                self._write_scope(context),
                context.user.id,
                payload.decision == "approve",
                payload.guidance,
            )
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        self.dispatcher.enqueue_immediate(delivery_ids)
        return self.get(run_id, context)

    def history(
        self,
        run_id: UUID,
        context: CurrentUserContext,
        page: int,
        size: int,
        newest_first: bool = False,
    ) -> PaginatedItems[WorkflowHistoryRead]:
        self._found(run_id, context)
        rows, total = self.repository.history(run_id, self._read_scope(context), page, size, newest_first)
        return PaginatedItems(
            page, size, total, [WorkflowHistoryRead.model_validate(row, from_attributes=True) for row in rows]
        )

    def result(self, attempt_id: UUID, token: str, result: AttemptResult) -> None:
        self.dispatcher.enqueue_immediate(self.repository.complete(attempt_id, token, result))

    def failure(self, attempt_id: UUID, token: str, failure: AttemptFailure) -> None:
        self.dispatcher.enqueue_immediate(self.repository.fail(attempt_id, token, failure))

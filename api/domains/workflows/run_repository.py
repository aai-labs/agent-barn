import hashlib
import hmac
import json
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, col, select
from sqlmodel.sql.expression import SelectOfScalar

from api.core.config import Config
from api.domains.agents.models import Agent, AgentStatus
from api.domains.agents.repository import agent_scope_predicates
from api.domains.artifacts import config as artifact_config
from api.domains.artifacts.models import Artifact
from api.domains.artifacts.references import attempt_files, pin, release
from api.domains.events.catalog import EVENT_REGISTRY, WORKFLOW_RUN_CHANGED
from api.domains.events.models import ActorIdentity, ActorIdentityType, SubjectIdentity, SubjectIdentityType
from api.domains.events.repository import OutboxMessageRepository
from api.domains.rbac.catalog import IMPLICIT_AGENT_OWNER_ROLES, PermissionKey
from api.domains.rbac.policy import AuthorizationScope
from api.domains.users.models import User
from api.domains.users.organization_users.models import OrganizationUser
from api.domains.workflows import config as workflow_config
from api.domains.workflows.models import Workflow, WorkflowVersion
from api.domains.workflows.repository import WorkflowConflict
from api.domains.workflows.run_models import (
    DECIDABLE_APPROVAL_STATES,
    TERMINAL_STATES,
    ApprovalRaised,
    AttemptFailure,
    AttemptRead,
    AttemptResult,
    WorkflowApprovalRequest,
    WorkflowAttempt,
    WorkflowCheckpoint,
    WorkflowHistory,
    WorkflowRun,
    WorkflowRunCreate,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


def _timeout_cause(accepted: bool) -> str:
    """Why an attempt expired unreported, keeping the failure an earlier attempt reported."""
    timeout = "The attempt timed out" if accepted else "The Agent did not accept the step"
    return timeout


def start_hash(payload: WorkflowRunCreate, user_id: UUID, rerun_of_run_id: UUID | None) -> str:
    if rerun_of_run_id:
        # The source run determines version and inputs, which retention may later remove,
        # so a retry's identity is the source run and actor alone.
        return digest(
            {
                "client_request_id": str(payload.client_request_id),
                "user_id": str(user_id),
                "rerun_of_run_id": str(rerun_of_run_id),
            }
        )
    return digest({**payload.model_dump(mode="json"), "user_id": str(user_id)})


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


@inject
@singleton
@dataclass
class WorkflowRunRepository:
    delegate: PostgresRepositoryDelegate
    outbox: OutboxMessageRepository
    config: Config

    def existing_start(
        self,
        scope: AuthorizationScope,
        payload: WorkflowRunCreate,
        user_id: UUID,
        rerun_of_run_id: UUID | None = None,
    ) -> UUID | None:
        with Session(self.delegate.engine) as session:
            run = session.exec(
                self.scoped(scope).where(
                    col(WorkflowRun.workflow_id) == payload.workflow_id,
                    col(WorkflowRun.agent_id) == payload.agent_id,
                    col(WorkflowRun.client_request_id) == payload.client_request_id,
                )
            ).one_or_none()
            if run is None:
                return None
            if run.request_hash != start_hash(payload, user_id, rerun_of_run_id):
                raise WorkflowConflict("Start request identity was reused with different inputs, version or actor")
            return run.id

    def archived_workflow_ids(self, workflow_ids: Iterable[UUID]) -> set[UUID]:
        with Session(self.delegate.engine) as session:
            return set(
                session.exec(
                    select(Workflow.id).where(
                        col(Workflow.id).in_(set(workflow_ids)), col(Workflow.archived_at).is_not(None)
                    )
                )
            )

    def agents(self, agent_ids: Iterable[UUID]) -> dict[UUID, Agent]:
        """The Agents of already authorized runs, including deleted ones."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            return {agent.id: agent for agent in session.exec(select(Agent).where(col(Agent.id).in_(set(agent_ids))))}

    @staticmethod
    def scoped(scope: AuthorizationScope, *, include_deleted: bool = False) -> SelectOfScalar[WorkflowRun]:
        """Runs on the Agents this scope reaches; reads keep the runs of deleted Agents."""
        return (
            select(WorkflowRun)
            .join(Agent, col(Agent.id) == col(WorkflowRun.agent_id))
            .where(*agent_scope_predicates(scope, include_deleted=include_deleted))
        )

    def get(self, run_id: UUID, scope: AuthorizationScope) -> tuple[WorkflowRun, WorkflowVersion] | None:
        with Session(self.delegate.engine) as session:
            run = session.exec(
                self.scoped(scope, include_deleted=True).where(col(WorkflowRun.id) == run_id)
            ).one_or_none()
            version = session.get(WorkflowVersion, run.version_id) if run else None
            return (run, version) if run and version else None

    def progress(self, run: WorkflowRun) -> tuple[dict[int, dict[str, Any]], AttemptRead | None]:
        """Step results and wall-clock timing plus the running step's live attempt.

        Callers must already have authorized the run."""
        with Session(self.delegate.engine) as session:
            attempts = list(
                session.exec(
                    select(WorkflowAttempt)
                    .where(col(WorkflowAttempt.run_id) == run.id)
                    .order_by(col(WorkflowAttempt.created_at))
                )
            )
            checkpoints = session.exec(select(WorkflowCheckpoint).where(col(WorkflowCheckpoint.run_id) == run.id))
            records: dict[int, dict[str, Any]] = {}
            for attempt in attempts:
                records.setdefault(attempt.step_index, {"started_at": attempt.created_at})
            for checkpoint in checkpoints:
                records.setdefault(checkpoint.step_index, {}).update(
                    summary=checkpoint.result.get("summary"),
                    completed_at=checkpoint.created_at,
                    artifacts=checkpoint.result.get("artifacts", []),
                )
        step_attempts = [attempt for attempt in attempts if attempt.step_index == run.next_step]
        if run.state != "RUNNING" or not step_attempts or step_attempts[-1].state != "REASONING":
            return records, None
        current = step_attempts[-1]
        now = datetime.now(UTC)
        grace = timedelta(seconds=workflow_config.DISPATCH_GRACE_SECONDS)
        return records, AttemptRead(
            number=len(step_attempts),
            started_at=current.created_at,
            expires_at=current.expires_at,
            server_time=now,
            agent_unresponsive=current.dispatched_at is None and now - current.created_at > grace,
        )

    def list_runs(
        self,
        scope: AuthorizationScope,
        page: int,
        size: int,
        workflow_id: UUID | None = None,
        agent_id: UUID | None = None,
        awaiting_decision: bool = False,
        settled: bool | None = None,
    ) -> tuple[list[tuple[WorkflowRun, WorkflowVersion]], int]:
        with Session(self.delegate.engine) as session:
            query = self.scoped(scope, include_deleted=True)
            if workflow_id:
                query = query.where(col(WorkflowRun.workflow_id) == workflow_id)
            if agent_id:
                query = query.where(col(WorkflowRun.agent_id) == agent_id)
            if settled is not None:
                terminal = col(WorkflowRun.state).in_(TERMINAL_STATES)
                query = query.where(terminal if settled else ~terminal)
            if awaiting_decision:
                # Correlated per run, so the open-request partial index serves it for the Agents in scope.
                query = query.where(
                    sa.exists().where(
                        col(WorkflowApprovalRequest.run_id) == WorkflowRun.id,
                        col(WorkflowApprovalRequest.state).in_(DECIDABLE_APPROVAL_STATES),
                    )
                )
            total = session.exec(select(sa.func.count()).select_from(query.subquery())).one()
            rows = session.exec(
                select(WorkflowRun, WorkflowVersion)
                .join(WorkflowVersion, col(WorkflowVersion.id) == col(WorkflowRun.version_id))
                .where(col(WorkflowRun.id).in_(query.with_only_columns(col(WorkflowRun.id))))
                .order_by(col(WorkflowRun.created_at).desc(), col(WorkflowRun.id))
                .offset((page - 1) * size)
                .limit(size)
            ).all()
            return [(run, version) for run, version in rows], total

    def history(
        self, run_id: UUID, scope: AuthorizationScope, page: int, size: int, newest_first: bool = False
    ) -> tuple[list[WorkflowHistory], int]:
        with Session(self.delegate.engine) as session:
            query = select(WorkflowHistory).where(
                col(WorkflowHistory.run_id).in_(
                    self.scoped(scope, include_deleted=True).with_only_columns(col(WorkflowRun.id))
                ),
                col(WorkflowHistory.run_id) == run_id,
            )
            total = session.exec(select(sa.func.count()).select_from(query.subquery())).one()
            order = (col(WorkflowHistory.created_at), col(WorkflowHistory.id))
            if newest_first:
                order = tuple(column.desc() for column in order)
            return list(session.exec(query.order_by(*order).offset((page - 1) * size).limit(size))), total

    def _event(self, session: Session, run: WorkflowRun, kind: str, detail: str) -> list[UUID]:
        now = datetime.now(UTC)
        run.updated_at = now
        session.add(run)
        session.add(WorkflowHistory(run_id=run.id, revision=run.revision, kind=kind, detail=detail))
        agent = session.get_one(Agent, run.agent_id)
        message = self.outbox.stage(
            session=session,
            registry=EVENT_REGISTRY,
            event=EVENT_REGISTRY.build_event(
                event_name=WORKFLOW_RUN_CHANGED,
                schema_version=1,
                occurred_at=now,
                organization_id=agent.organization_id,
                actor=ActorIdentity(type=ActorIdentityType.SYSTEM, id="workflow-controller"),
                subject=SubjectIdentity(
                    type=SubjectIdentityType.AGENT, id=agent.id, organization_id=agent.organization_id
                ),
                correlation_id=run.id,
                payload={"run_id": str(run.id), "revision": run.revision, "state": run.state},
            ),
        )
        return self.outbox.delivery_ids_for_event(session, message.event_id)

    def start(
        self,
        scope: AuthorizationScope,
        payload: WorkflowRunCreate,
        user_id: UUID,
        membership_id: UUID,
        runtime: str,
        rerun_of_run_id: UUID | None = None,
    ) -> tuple[WorkflowRun, list[UUID]]:
        request_hash = start_hash(payload, user_id, rerun_of_run_id)
        workflow_id, agent_id = payload.workflow_id, payload.agent_id
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            # Serialize starts on this Agent, including its first run.
            agent = session.exec(
                select(Agent).where(col(Agent.id) == agent_id, *agent_scope_predicates(scope)).with_for_update(of=Agent)
            ).one_or_none()
            if agent is None:
                raise WorkflowConflict("Workflow access changed")
            workflow = session.exec(
                select(Workflow)
                .where(col(Workflow.id) == workflow_id, col(Workflow.organization_id) == scope.organization_id)
                .with_for_update(of=Workflow)
            ).one_or_none()
            if workflow is None:
                raise WorkflowConflict("Workflow access changed")
            existing = session.exec(
                select(WorkflowRun).where(
                    col(WorkflowRun.workflow_id) == workflow_id,
                    col(WorkflowRun.client_request_id) == payload.client_request_id,
                )
            ).one_or_none()
            if existing:
                if existing.request_hash != request_hash:
                    raise WorkflowConflict(
                        "Start request identity was reused with a different Agent, inputs, version or actor"
                    )
                return existing, []
            if rerun_of_run_id:
                # Retention may have removed the source's inputs since the caller read them.
                source = session.exec(
                    select(WorkflowRun).where(col(WorkflowRun.id) == rerun_of_run_id).with_for_update(of=WorkflowRun)
                ).one_or_none()
                if source is None or source.content_expired:
                    raise WorkflowConflict("The source run's inputs are no longer available")
            version = session.get(WorkflowVersion, payload.version_id)
            if workflow.archived_at or version is None or version.workflow_id != workflow_id:
                raise WorkflowConflict("The saved version is unavailable or the workflow is archived")
            run = WorkflowRun(
                workflow_id=workflow_id,
                agent_id=agent_id,
                version_id=payload.version_id,
                title=payload.title,
                initiating_user_id=user_id,
                initiating_membership_id=membership_id,
                client_request_id=payload.client_request_id,
                request_hash=request_hash,
                inputs=payload.model_dump(mode="json")["inputs"],
                runtime=runtime,
                rerun_of_run_id=rerun_of_run_id,
            )
            file_inputs = [value for value in run.inputs.values() if isinstance(value, dict)]
            if len(file_inputs) > artifact_config.MAX_FILES_PER_ATTEMPT:
                raise WorkflowConflict("At most 16 file inputs are supported; combine files in an archive")
            for value in sorted(file_inputs, key=lambda item: item["artifact_id"]):
                pin(
                    session,
                    UUID(value["artifact_id"]),
                    value["checksum"],
                    agent_id,
                    scope.organization_id,
                    "run",
                    run.id,
                )
                artifact = session.get_one(Artifact, UUID(value["artifact_id"]))
                value.update(filename=artifact.filename, size=artifact.size)
            if len(json.dumps(file_inputs, ensure_ascii=False).encode()) > artifact_config.MAX_RUN_FILE_CONTEXT_BYTES:
                raise WorkflowConflict("Workflow file inputs exceed the file-reference context limit")
            session.add(run)
            session.flush()
            delivery_ids = (
                self._event(
                    session,
                    run,
                    "RERUN_STARTED",
                    f"Re-run of run {str(rerun_of_run_id)[:8]} using version {version.number}",
                )
                if rerun_of_run_id
                else self._event(session, run, "STARTED", f"Run started using version {version.number}")
            )
            session.commit()
            return run, delivery_ids

    def cancel(self, run_id: UUID, scope: AuthorizationScope, revision: int) -> list[UUID]:
        with Session(self.delegate.engine) as session:
            run = session.exec(
                self.scoped(scope).where(col(WorkflowRun.id) == run_id).with_for_update(of=WorkflowRun)
            ).one_or_none()
            if run is None:
                raise WorkflowConflict("Run access changed")
            if run.state in {"CANCELLING", "CANCELLED"}:
                return []
            if run.revision != revision or run.state in TERMINAL_STATES:
                raise WorkflowConflict("Run changed; refresh before cancelling")
            run.state = "CANCELLING"
            run.reason = "Cancellation requested; claimed work is stopping"
            run.revision += 1
            self._lapse(session, run.id)
            delivery_ids = self._event(session, run, "CANCEL_REQUESTED", run.reason)
            session.commit()
            return delivery_ids

    def _authorized(self, session: Session, run: WorkflowRun) -> bool:
        membership = (
            session.get(OrganizationUser, run.initiating_membership_id) if run.initiating_membership_id else None
        )
        if membership is None or membership.user_id != run.initiating_user_id:
            return False
        return self._may_update(session, run, membership)

    def _decider_authorized(self, session: Session, run: WorkflowRun, user_id: UUID | None) -> bool:
        """The person who decided a request must still hold `agent.update` when the session continues."""
        if user_id is None:
            return False
        agent = session.get(Agent, run.agent_id)
        membership = (
            session.exec(
                select(OrganizationUser).where(
                    col(OrganizationUser.user_id) == user_id,
                    col(OrganizationUser.organization_id) == agent.organization_id,
                )
            ).first()
            if agent is not None
            else None
        )
        return membership is not None and self._may_update(session, run, membership, running=False)

    @staticmethod
    def _may_update(session: Session, run: WorkflowRun, membership: OrganizationUser, *, running: bool = True) -> bool:
        """Whether the member holds `agent.update` on the run's Agent (and, by default, the Agent is running)."""
        user = session.get(User, membership.user_id)
        if user is None:
            return False
        scope = (
            AuthorizationScope(organization_id=membership.organization_id)
            if membership.role in IMPLICIT_AGENT_OWNER_ROLES
            else AuthorizationScope(
                organization_id=membership.organization_id,
                membership_id=membership.id,
                permission=PermissionKey.AGENT_UPDATE,
                include_general_access=user.email_verified_at is not None,
            )
        )
        return (
            session.exec(
                select(Agent).where(
                    col(Agent.id) == run.agent_id,
                    *([col(Agent.status) == AgentStatus.RUNNING] if running else []),
                    *agent_scope_predicates(scope),
                )
            ).one_or_none()
            is not None
        )

    def token(self, attempt_id: UUID) -> str:
        return hmac.new(
            self.config.secret_signing_key.encode(), f"workflow-attempt-v1:{attempt_id}".encode(), hashlib.sha256
        ).hexdigest()

    def _bound(self, session: Session, attempt_id: UUID, token: str) -> tuple[WorkflowRun, WorkflowAttempt]:
        attempt = session.get(WorkflowAttempt, attempt_id)
        if attempt is None or not hmac.compare_digest(
            attempt.capability_hash, hashlib.sha256(token.encode()).hexdigest()
        ):
            raise WorkflowConflict("Invalid workflow attempt capability")
        return self._fenced_attempt(session, attempt, lock=True)

    def artifact_attempt(
        self, session: Session, attempt_id: UUID, agent_id: UUID, *, lock: bool = True
    ) -> tuple[WorkflowRun, WorkflowAttempt]:
        """Publication authority comes from the authenticated Agent running the run, never the completion bearer."""
        attempt = session.get(WorkflowAttempt, attempt_id)
        if attempt is None:
            raise WorkflowConflict("Workflow attempt not found")
        run = session.get_one(WorkflowRun, attempt.run_id)
        if run.agent_id != agent_id:
            raise WorkflowConflict("Workflow attempt belongs to another Agent")
        return self._fenced_attempt(session, attempt, lock=lock)

    def _fenced_attempt(
        self, session: Session, attempt: WorkflowAttempt, *, lock: bool
    ) -> tuple[WorkflowRun, WorkflowAttempt]:
        query = select(WorkflowRun).where(col(WorkflowRun.id) == attempt.run_id)
        if lock:
            query = query.with_for_update()
        run = session.exec(query.execution_options(populate_existing=True)).one()
        session.refresh(attempt)
        if (
            run.state != "RUNNING"
            or attempt.state != "REASONING"
            or run.generation != attempt.generation
            or attempt.expires_at <= datetime.now(UTC)
            or not self._authorized(session, run)
        ):
            raise WorkflowConflict("Workflow attempt admission is fenced")
        return run, attempt

    def admit(self, attempt_id: UUID, token: str) -> tuple[WorkflowRun, WorkflowAttempt, dict]:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            run, attempt = self._bound(session, attempt_id, token)
            version = session.get_one(WorkflowVersion, run.version_id)
            checkpoints = list(
                session.exec(
                    select(WorkflowCheckpoint)
                    .where(col(WorkflowCheckpoint.run_id) == run.id)
                    .order_by(col(WorkflowCheckpoint.step_index))
                )
            )
            packet = {
                "attempt_id": str(attempt.id),
                "inputs": run.inputs,
                "step": {
                    **{
                        key: value
                        for key, value in version.snapshot["steps"][attempt.step_index].items()
                        if key != "artifact_description" and not (key == "completion_criteria" and value is None)
                    },
                    "output_description": version.snapshot["steps"][attempt.step_index].get("artifact_description"),
                },
                "completed_steps": [item.result for item in checkpoints],
                "files": list(
                    {
                        item["artifact_id"]: item
                        for item in [
                            *[value for value in run.inputs.values() if isinstance(value, dict)],
                            *[file for checkpoint in checkpoints for file in checkpoint.result.get("artifacts", [])],
                        ]
                    }.values()
                ),
                "final_output_description": version.snapshot["steps"][-1].get("artifact_description")
                if attempt.step_index == len(version.snapshot["steps"]) - 1
                else None,
            }
            continued = self.continuation(session, attempt)
            if continued is not None:
                packet["continuation"] = continued.model_dump(
                    mode="json", include={"session_id", "state", "command", "guidance"}
                )
            session.commit()
            return run, attempt, packet

    def complete(self, attempt_id: UUID, token: str, result: AttemptResult) -> list[UUID]:
        with Session(self.delegate.engine) as session:
            # Exact duplicate result is acknowledged even after progression; never replay it.
            attempt = session.get(WorkflowAttempt, attempt_id)
            result_hash = digest(result.model_dump(mode="json"))
            if (
                attempt
                and hmac.compare_digest(attempt.capability_hash, hashlib.sha256(token.encode()).hexdigest())
                and attempt.state == "COMPLETED"
                and attempt.result_hash == result_hash
            ):
                return []
            run, attempt = self._bound(session, attempt_id, token)
            version = session.get_one(WorkflowVersion, run.version_id)
            step = version.snapshot["steps"][attempt.step_index]
            files = attempt_files(session, attempt.id)
            checkpoint = {
                "summary": result.summary,
                "step_id": step["id"],
                "artifacts": files,
                "output_description": step.get("artifact_description"),
            }
            session.add(
                WorkflowCheckpoint(
                    run_id=run.id, attempt_id=attempt.id, step_index=attempt.step_index, result=checkpoint
                )
            )
            attempt.state, attempt.result_hash = "COMPLETED", result_hash
            session.add(attempt)
            run.next_step += 1
            run.revision += 1
            run.reason = None
            run.state = "SUCCEEDED" if run.next_step == len(version.snapshot["steps"]) else "QUEUED"
            if run.state == "SUCCEEDED":
                self._settle(session, run)
            delivery_ids = self._event(session, run, "STEP_COMPLETED", result.summary)
            session.commit()
            return delivery_ids

    def fail(self, attempt_id: UUID, token: str, failure: AttemptFailure) -> list[UUID]:
        """The Agent reported that its session for this step ended without a result."""
        with Session(self.delegate.engine) as session:
            run, attempt = self._bound(session, attempt_id, token)
            run.revision += 1
            attempt.state = "STOPPED"
            session.add(attempt)
            run.state = "BLOCKED" if failure.needs_attention or failure.retryable else "FAILED"
            run.reason = failure.reason
            # The session that held any open request has ended; nothing is left to decide.
            self._lapse(session, run.id)
            if run.state == "FAILED":
                self._settle(session, run)
            delivery_ids = self._event(
                session, run, "NEEDS_ATTENTION" if failure.needs_attention else "ATTEMPT_FAILED", failure.reason
            )
            session.commit()
            return delivery_ids

    def mark_dispatched(self, attempt_id: UUID) -> None:
        with Session(self.delegate.engine) as session:
            attempt = session.get(WorkflowAttempt, attempt_id)
            if attempt is not None and attempt.dispatched_at is None:
                attempt.dispatched_at = datetime.now(UTC)
                session.add(attempt)
                session.commit()

    def _settle(self, session: Session, run: WorkflowRun) -> None:
        self._lapse(session, run.id)
        release(session, "run", run.id, self.config.artifact_retention_days)
        run.settled_at = datetime.now(UTC)

    def active_ids(self, limit: int = 100) -> list[UUID]:
        """Select and rotate active recovery work; no-op dispatches cannot starve newer runs."""
        return self._recovery_ids(("QUEUED", "RUNNING", "CANCELLING"), limit)

    def parked_ids(self, limit: int = 100) -> list[UUID]:
        """Audit parked runs separately for lifecycle and authorization changes."""
        return self._recovery_ids(("BLOCKED", "PAUSED", "AWAITING_APPROVAL"), limit)

    # Approvals. A request is answered live while the step's session holds it, or after the
    # session was stopped (parked); a late decision continues the same session in a new attempt.

    @staticmethod
    def _latest_request(session: Session, attempt_id: UUID) -> WorkflowApprovalRequest | None:
        return session.exec(
            select(WorkflowApprovalRequest)
            .where(col(WorkflowApprovalRequest.attempt_id) == attempt_id)
            .order_by(col(WorkflowApprovalRequest.created_at).desc())
            .limit(1)
        ).one_or_none()

    @staticmethod
    def _lapse(session: Session, run_id: UUID) -> None:
        session.exec(
            sa.update(WorkflowApprovalRequest)
            .where(
                col(WorkflowApprovalRequest.run_id) == run_id,
                col(WorkflowApprovalRequest.state).in_(DECIDABLE_APPROVAL_STATES),
            )
            .values(state="LAPSED", updated_at=datetime.now(UTC))
        )

    def _park(self, session: Session, run: WorkflowRun, request: WorkflowApprovalRequest) -> None:
        request.state = "PARKED"
        session.add(request)
        run.state = "AWAITING_APPROVAL"
        run.reason = f"Waiting for approval to run {request.command[:500]}"

    @staticmethod
    def continuation(session: Session, attempt: WorkflowAttempt) -> WorkflowApprovalRequest | None:
        """The late decision this attempt continues, claiming it on first sight."""
        # Live declines continue inside their own attempt, so one attempt may claim several.
        claimed = session.exec(
            select(WorkflowApprovalRequest)
            .where(col(WorkflowApprovalRequest.continued_by_attempt_id) == attempt.id)
            .order_by(col(WorkflowApprovalRequest.created_at).desc())
            .limit(1)
        ).one_or_none()
        if claimed is not None:
            return claimed
        request = session.exec(
            select(WorkflowApprovalRequest)
            .where(
                col(WorkflowApprovalRequest.run_id) == attempt.run_id,
                col(WorkflowApprovalRequest.step_index) == attempt.step_index,
                col(WorkflowApprovalRequest.state).in_(("APPROVED", "DECLINED")),
                col(WorkflowApprovalRequest.continued_by_attempt_id).is_(None),
                col(WorkflowApprovalRequest.attempt_id) != attempt.id,
            )
            .order_by(col(WorkflowApprovalRequest.created_at).desc())
            .limit(1)
        ).one_or_none()
        if request is not None:
            request.continued_by_attempt_id = attempt.id
            session.add(request)
        return request

    def raise_approval(
        self, attempt_id: UUID, token: str, raised: ApprovalRaised
    ) -> tuple[WorkflowApprovalRequest, list[UUID]]:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            run, attempt = self._bound(session, attempt_id, token)
            command_sha256 = hashlib.sha256(raised.command.encode()).hexdigest()
            # A retried report is the same request in whatever state it reached meanwhile; only a
            # released request was acted on, so the same command asked again after it is a new ask.
            reported = session.exec(
                select(WorkflowApprovalRequest)
                .where(
                    col(WorkflowApprovalRequest.attempt_id) == attempt.id,
                    col(WorkflowApprovalRequest.runtime_run_id) == raised.runtime_run_id,
                    col(WorkflowApprovalRequest.command_sha256) == command_sha256,
                    col(WorkflowApprovalRequest.state) != "RELEASED",
                )
                .order_by(col(WorkflowApprovalRequest.created_at).desc())
                .limit(1)
            ).one_or_none()
            if reported is not None:
                session.commit()
                return reported, []
            latest = self._latest_request(session, attempt.id)
            if latest is not None and latest.state == "LIVE":
                raise WorkflowConflict("Another approval request is already live for this attempt")
            continued = self.continuation(session, attempt)
            now = datetime.now(UTC)
            # Hermes's own approval clock started when it raised the event, not when it reached us.
            live_seconds = max(workflow_config.APPROVAL_LIVE_SECONDS - raised.age_seconds, 0)
            request = WorkflowApprovalRequest(
                run_id=run.id,
                attempt_id=attempt.id,
                step_index=attempt.step_index,
                session_id=continued.session_id if continued else f"workflow-{attempt.id}",
                runtime_run_id=raised.runtime_run_id,
                command=raised.command,
                command_sha256=command_sha256,
                live_until=now + timedelta(seconds=live_seconds),
            )
            session.add(request)
            # The deadline covers the whole window; a decision gives back the part not waited.
            attempt.expires_at += request.live_until - now + timedelta(seconds=workflow_config.DISPATCH_GRACE_SECONDS)
            session.add(attempt)
            run.revision += 1
            delivery_ids = self._event(
                session, run, "APPROVAL_REQUESTED", f"Approval requested to run {raised.command[:500]}"
            )
            session.commit()
            return request, delivery_ids

    def _bound_request(
        self, session: Session, attempt_id: UUID, token: str, request_id: UUID
    ) -> tuple[WorkflowRun, WorkflowAttempt, WorkflowApprovalRequest]:
        run, attempt = self._bound(session, attempt_id, token)
        request = session.get(WorkflowApprovalRequest, request_id)
        if request is None or request.attempt_id != attempt.id:
            raise WorkflowConflict("Approval request belongs to another attempt")
        return run, attempt, request

    def approval_status(self, attempt_id: UUID, token: str, request_id: UUID) -> WorkflowApprovalRequest:
        """Polled by the step while the request is live. A decline is claimed here for continuation."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            _, attempt, request = self._bound_request(session, attempt_id, token, request_id)
            if request.state == "DECLINED" and request.continued_by_attempt_id is None:
                request.continued_by_attempt_id = attempt.id
                session.add(request)
            session.commit()
            return request

    def park(self, attempt_id: UUID, token: str, request_id: UUID) -> tuple[WorkflowApprovalRequest, list[UUID]]:
        """Close the live window; a decision that already arrived wins and is returned instead."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            run, attempt, request = self._bound_request(session, attempt_id, token, request_id)
            if request.state != "LIVE":
                session.commit()
                return request, []
            self._park(session, run, request)
            attempt.state = "STOPPED"
            session.add(attempt)
            run.revision += 1
            delivery_ids = self._event(session, run, "APPROVAL_PARKED", run.reason or "Waiting for approval")
            session.commit()
            return request, delivery_ids

    def released(self, attempt_id: UUID, token: str, request_id: UUID) -> list[UUID]:
        """The runtime confirmed it received the approval; until then the outcome is uncertain."""
        with Session(self.delegate.engine) as session:
            run, _, request = self._bound_request(session, attempt_id, token, request_id)
            if request.state == "RELEASED":
                return []
            if request.state != "APPROVED":
                raise WorkflowConflict("Approval request was not approved")
            request.state = "RELEASED"
            session.add(request)
            run.revision += 1
            delivery_ids = self._event(
                session, run, "APPROVAL_RELEASED", f"Approved command released: {request.command[:500]}"
            )
            session.commit()
            return delivery_ids

    def decide(
        self,
        run_id: UUID,
        request_id: UUID,
        scope: AuthorizationScope,
        user_id: UUID,
        approve: bool,
        guidance: str | None,
    ) -> list[UUID]:
        with Session(self.delegate.engine) as session:
            run = session.exec(
                self.scoped(scope).where(col(WorkflowRun.id) == run_id).with_for_update(of=WorkflowRun)
            ).one_or_none()
            if run is None:
                raise WorkflowConflict("Run access changed")
            request = session.get(WorkflowApprovalRequest, request_id)
            if request is None or request.run_id != run.id or request.state not in DECIDABLE_APPROVAL_STATES:
                raise WorkflowConflict("This approval request is no longer awaiting a decision")
            now = datetime.now(UTC)
            attempt = session.get_one(WorkflowAttempt, request.attempt_id)
            if request.state == "LIVE" and (
                run.state != "RUNNING" or attempt.state != "REASONING" or request.live_until <= now
            ):
                raise WorkflowConflict("This approval request is closing; refresh and decide again")
            if request.state == "PARKED" and run.state != "AWAITING_APPROVAL":
                raise WorkflowConflict("Run changed; refresh before deciding")
            live = request.state == "LIVE"
            request.state = "APPROVED" if approve else "DECLINED"
            request.decided_by_user_id, request.decided_at = user_id, now
            request.guidance = None if approve else (guidance or "").strip() or None
            session.add(request)
            session.flush()
            declines = session.exec(
                select(sa.func.count()).where(
                    col(WorkflowApprovalRequest.run_id) == run.id,
                    col(WorkflowApprovalRequest.step_index) == request.step_index,
                    col(WorkflowApprovalRequest.state) == "DECLINED",
                )
            ).one()
            run.revision += 1
            if not approve and declines >= workflow_config.MAX_DECLINES_PER_STEP:
                # The step's session sees its admission fenced and stops; nothing is continued.
                request.continued_by_attempt_id = request.attempt_id
                attempt.state = "STOPPED"
                session.add(attempt)
                run.state = "BLOCKED"
                run.reason = (
                    f"The Agent's commands were declined {declines} times in this step; cancel the run "
                    "and revise the workflow"
                )
            elif live:
                # Only the time actually spent waiting is added to the step's budget.
                attempt.expires_at -= request.live_until - now
                session.add(attempt)
            else:
                self._continue_when_ready(session, run)
            verdict = "approved" if approve else "declined"
            delivery_ids = self._event(session, run, "APPROVAL_DECIDED", f"Command {verdict}: {request.command[:500]}")
            session.commit()
            return delivery_ids

    @staticmethod
    def _decided(session: Session, run: WorkflowRun) -> WorkflowApprovalRequest | None:
        """A late decision on the current step that no attempt has continued yet."""
        return session.exec(
            select(WorkflowApprovalRequest)
            .where(
                col(WorkflowApprovalRequest.run_id) == run.id,
                col(WorkflowApprovalRequest.step_index) == run.next_step,
                col(WorkflowApprovalRequest.state).in_(("APPROVED", "DECLINED")),
                col(WorkflowApprovalRequest.continued_by_attempt_id).is_(None),
            )
            .order_by(col(WorkflowApprovalRequest.created_at).desc())
            .limit(1)
        ).one_or_none()

    def _continue_when_ready(self, session: Session, run: WorkflowRun) -> None:
        """Queue a late decision's continuation, or keep it waiting until the session may continue.

        Lifecycle changes never lapse a parked or decided request: the run keeps Awaiting Approval
        and continues once the Agent runs, the initiator keeps authority, and the decider still may.
        """
        decided = self._decided(session, run)
        if decided is None:
            return
        if not self._decider_authorized(session, run, decided.decided_by_user_id):
            # Authority is required when deciding and again when the session continues.
            decided.state, decided.decided_by_user_id, decided.decided_at, decided.guidance = "PARKED", None, None, None
            session.add(decided)
            self._park(session, run, decided)
            run.reason = f"The decider no longer has access; decide again on {decided.command[:500]}"
        elif self._authorized(session, run):
            run.state, run.reason = "QUEUED", None
        else:
            run.state = "AWAITING_APPROVAL"
            run.reason = "Decided; continues once the Agent is running and the run's initiator still has access"

    def approvals(self, run_ids: Iterable[UUID], states: Iterable[str] | None = None) -> list[WorkflowApprovalRequest]:
        """Requests of these runs, oldest first. Callers must already have authorized the runs."""
        query = select(WorkflowApprovalRequest).where(col(WorkflowApprovalRequest.run_id).in_(set(run_ids)))
        if states is not None:
            query = query.where(col(WorkflowApprovalRequest.state).in_(set(states)))
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            return list(session.exec(query.order_by(col(WorkflowApprovalRequest.created_at))))

    def current_approval(self, run: WorkflowRun) -> WorkflowApprovalRequest | None:
        """The latest request of the run's current step. Callers must already have authorized the run."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            return session.exec(
                select(WorkflowApprovalRequest)
                .where(
                    col(WorkflowApprovalRequest.run_id) == run.id,
                    col(WorkflowApprovalRequest.step_index) == run.next_step,
                )
                .order_by(col(WorkflowApprovalRequest.created_at).desc())
                .limit(1)
            ).one_or_none()

    def _recovery_ids(self, states: tuple[str, ...], limit: int) -> list[UUID]:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            rows = list(
                session.exec(
                    select(WorkflowRun)
                    .where(col(WorkflowRun.state).in_(states))
                    .order_by(col(WorkflowRun.updated_at), col(WorkflowRun.id))
                    .limit(limit)
                    .with_for_update(skip_locked=True)
                )
            )
            now = datetime.now(UTC)
            for row in rows:
                row.updated_at = now
                session.add(row)
            session.commit()
            return [row.id for row in rows]

    def inspect(self, run_id: UUID) -> tuple[WorkflowRun, WorkflowAttempt | None] | None:
        with Session(self.delegate.engine) as session:
            run = session.get(WorkflowRun, run_id)
            if run is None:
                return None
            attempt = session.exec(
                select(WorkflowAttempt).where(
                    col(WorkflowAttempt.run_id) == run_id, col(WorkflowAttempt.generation) == run.generation
                )
            ).one_or_none()
            return run, attempt

    def advance(
        self, run_id: UUID, *, stopped: bool = False, lost: bool = False
    ) -> tuple[WorkflowAttempt | None, list[UUID]]:
        """Serialize all progression. Recovery never replays completed checkpoints."""
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            run = session.exec(select(WorkflowRun).where(col(WorkflowRun.id) == run_id).with_for_update()).one_or_none()
            if run is None or run.state in TERMINAL_STATES:
                return None, []
            agent = session.get(Agent, run.agent_id)
            if agent is None or agent.deleted_at is not None:
                run.state = "CANCELLING"
            attempt = session.exec(
                select(WorkflowAttempt).where(
                    col(WorkflowAttempt.run_id) == run.id, col(WorkflowAttempt.generation) == run.generation
                )
            ).one_or_none()
            if run.state == "PAUSED" and (attempt is None or attempt.state not in {"REASONING", "STOPPING"}):
                return None, []
            continuing = False
            if run.state in {"QUEUED", "AWAITING_APPROVAL"} and self._decided(session, run) is not None:
                # A late decision continues only while every authority it needs still holds.
                before = (run.state, run.reason)
                self._continue_when_ready(session, run)
                if run.state != "QUEUED":
                    if (run.state, run.reason) == before:
                        return None, []
                    run.revision += 1
                    delivery_ids = self._event(session, run, "APPROVAL_WAITING", run.reason or "Awaiting approval")
                    session.commit()
                    return None, delivery_ids
                continuing = True
            elif run.state == "AWAITING_APPROVAL":
                # A parked request survives Agent stops, updates and authority changes; it is
                # checked again when someone decides and when the continuation starts.
                return None, []
            authorized = self._authorized(session, run)
            if not authorized and run.state != "CANCELLING":
                run.state, run.reason = "PAUSED", "Initiator authority or Agent lifecycle changed"
                self._lapse(session, run.id)
            expired = (
                attempt is not None
                and attempt.state in {"REASONING", "STOPPING"}
                and (attempt.expires_at <= datetime.now(UTC) or lost or attempt.state == "STOPPING")
            )
            if run.state in {"CANCELLING", "PAUSED"} or expired:
                if attempt and attempt.state in {"REASONING", "STOPPING"}:
                    attempt.state = "STOPPED" if stopped else "STOPPING"
                    session.add(attempt)
                    if not stopped:
                        session.add(run)
                        session.commit()
                        return None, []
                if run.state == "CANCELLING":
                    run.state, run.reason = "CANCELLED", "Cancelled; completed step summaries are preserved"
                    self._settle(session, run)
                elif expired and attempt is not None and authorized and run.state != "PAUSED":
                    # Even with a request still open, an ended session is no evidence that nothing ran:
                    # Hermes may have denied the command itself and carried on.
                    self._lapse(session, run.id)
                    run.state, run.reason = (
                        "BLOCKED",
                        (
                            f"{_timeout_cause(attempt.dispatched_at is not None)}; "
                            "outcome is uncertain; inspect external effects before starting another run"
                        ),
                    )
                run.revision += 1
                delivery_ids = self._event(session, run, "FENCED", run.reason or "Attempt stopped")
                session.commit()
                return None, delivery_ids
            if run.state != "QUEUED":
                return (attempt if attempt and attempt.state == "REASONING" else None), []
            run.generation += 1
            run.state = "RUNNING"
            run.revision += 1
            attempt_id = uuid4()
            attempt = WorkflowAttempt(
                id=attempt_id,
                run_id=run.id,
                generation=run.generation,
                step_index=run.next_step,
                capability_hash=hashlib.sha256(self.token(attempt_id).encode()).hexdigest(),
                expires_at=datetime.now(UTC) + timedelta(seconds=workflow_config.ATTEMPT_TIMEOUT_SECONDS),
            )
            session.add(attempt)
            delivery_ids = self._event(
                session,
                run,
                "ATTEMPT_STARTED",
                f"Step {run.next_step + 1} continued in its previous session after an approval decision"
                if continuing
                else f"Step {run.next_step + 1} started in a fresh session",
            )
            session.commit()
            return attempt, delivery_ids

    def expire_content(self, limit: int = 100) -> None:
        """Operator-only retention pass for settled text inputs and results."""
        now = datetime.now(UTC)
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            settled = list(
                session.exec(
                    select(WorkflowRun)
                    .where(
                        col(WorkflowRun.settled_at) <= now - timedelta(days=workflow_config.HISTORY_RETENTION_DAYS),
                        col(WorkflowRun.content_expired).is_(False),
                    )
                    .limit(limit)
                )
            )
            for run in settled:
                run.inputs = {}
                run.content_expired = True
                session.add(run)
                session.exec(sa.delete(WorkflowCheckpoint).where(col(WorkflowCheckpoint.run_id) == run.id))
                session.exec(
                    sa.update(WorkflowHistory)
                    .where(col(WorkflowHistory.run_id) == run.id)
                    .values(detail="Content expired under the installation retention policy")
                )
                # Commands and guidance are content too; who decided and when remain.
                session.exec(
                    sa.update(WorkflowApprovalRequest)
                    .where(col(WorkflowApprovalRequest.run_id) == run.id)
                    .values(
                        command="Content expired under the installation retention policy",
                        command_sha256="",
                        guidance=None,
                    )
                )
            session.commit()

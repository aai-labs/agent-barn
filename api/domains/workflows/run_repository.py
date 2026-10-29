import hashlib
import hmac
import json
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
    TERMINAL_STATES,
    AttemptFailure,
    AttemptResult,
    WorkflowAttempt,
    WorkflowCheckpoint,
    WorkflowHistory,
    WorkflowRun,
    WorkflowRunCreate,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


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
        self, workflow_id: UUID, agent_id: UUID, scope: AuthorizationScope, payload: WorkflowRunCreate, user_id: UUID
    ) -> UUID | None:
        with Session(self.delegate.engine) as session:
            run = session.exec(
                self.scoped(agent_id, scope).where(
                    col(WorkflowRun.workflow_id) == workflow_id,
                    col(WorkflowRun.client_request_id) == payload.client_request_id,
                )
            ).one_or_none()
            if run is None:
                return None
            if run.request_hash != digest({**payload.model_dump(mode="json"), "user_id": str(user_id)}):
                raise WorkflowConflict("Start request identity was reused with different inputs, version or actor")
            return run.id

    def owning_agent_id(self, workflow_id: UUID) -> UUID:
        with Session(self.delegate.engine) as session:
            return session.get_one(Workflow, workflow_id).agent_id

    @staticmethod
    def scoped(agent_id: UUID, scope: AuthorizationScope) -> SelectOfScalar[WorkflowRun]:
        return (
            select(WorkflowRun)
            .join(Workflow, col(Workflow.id) == col(WorkflowRun.workflow_id))
            .join(Agent, col(Agent.id) == col(Workflow.agent_id))
            .where(col(Workflow.agent_id) == agent_id, *agent_scope_predicates(scope))
        )

    def get(
        self, run_id: UUID, agent_id: UUID, scope: AuthorizationScope
    ) -> tuple[WorkflowRun, WorkflowVersion] | None:
        with Session(self.delegate.engine) as session:
            run = session.exec(self.scoped(agent_id, scope).where(col(WorkflowRun.id) == run_id)).one_or_none()
            version = session.get(WorkflowVersion, run.version_id) if run else None
            return (run, version) if run and version else None

    def step_records(self, run_id: UUID) -> dict[int, dict[str, Any]]:
        """Results and wall-clock timing. Callers must already have authorized the run."""
        with Session(self.delegate.engine) as session:
            records: dict[int, dict[str, Any]] = {}
            attempts = session.exec(
                select(WorkflowAttempt)
                .where(col(WorkflowAttempt.run_id) == run_id)
                .order_by(col(WorkflowAttempt.created_at))
            )
            for attempt in attempts:
                records.setdefault(attempt.step_index, {"started_at": attempt.created_at})
            checkpoints = session.exec(select(WorkflowCheckpoint).where(col(WorkflowCheckpoint.run_id) == run_id))
            for checkpoint in checkpoints:
                records.setdefault(checkpoint.step_index, {}).update(
                    summary=checkpoint.result.get("summary"),
                    completed_at=checkpoint.created_at,
                    artifacts=checkpoint.result.get("artifacts", []),
                )
            return records

    def list_runs(
        self, agent_id: UUID, scope: AuthorizationScope, page: int, size: int, workflow_id: UUID | None
    ) -> tuple[list[tuple[WorkflowRun, WorkflowVersion]], int]:
        with Session(self.delegate.engine) as session:
            query = self.scoped(agent_id, scope)
            if workflow_id:
                query = query.where(col(WorkflowRun.workflow_id) == workflow_id)
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
        self, run_id: UUID, agent_id: UUID, scope: AuthorizationScope, page: int, size: int
    ) -> tuple[list[WorkflowHistory], int]:
        with Session(self.delegate.engine) as session:
            query = select(WorkflowHistory).where(
                col(WorkflowHistory.run_id).in_(self.scoped(agent_id, scope).with_only_columns(col(WorkflowRun.id))),
                col(WorkflowHistory.run_id) == run_id,
            )
            total = session.exec(select(sa.func.count()).select_from(query.subquery())).one()
            return list(
                session.exec(
                    query.order_by(col(WorkflowHistory.created_at), col(WorkflowHistory.id))
                    .offset((page - 1) * size)
                    .limit(size)
                )
            ), total

    def _event(self, session: Session, run: WorkflowRun, kind: str, detail: str) -> list[UUID]:
        now = datetime.now(UTC)
        run.updated_at = now
        session.add(run)
        session.add(WorkflowHistory(run_id=run.id, revision=run.revision, kind=kind, detail=detail))
        workflow = session.get_one(Workflow, run.workflow_id)
        agent = session.get_one(Agent, workflow.agent_id)
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
        workflow_id: UUID,
        agent_id: UUID,
        scope: AuthorizationScope,
        payload: WorkflowRunCreate,
        user_id: UUID,
        membership_id: UUID,
        runtime: str,
    ) -> tuple[WorkflowRun, list[UUID]]:
        request_hash = digest({**payload.model_dump(mode="json"), "user_id": str(user_id)})
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            # Serialize starts across this Agent's definitions, including its first run.
            agent = session.exec(
                select(Agent).where(col(Agent.id) == agent_id, *agent_scope_predicates(scope)).with_for_update(of=Agent)
            ).one_or_none()
            if agent is None:
                raise WorkflowConflict("Workflow access changed")
            workflow = session.exec(
                select(Workflow)
                .join(Agent, col(Agent.id) == col(Workflow.agent_id))
                .where(
                    col(Workflow.id) == workflow_id, col(Workflow.agent_id) == agent_id, *agent_scope_predicates(scope)
                )
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
                    raise WorkflowConflict("Start request identity was reused with different inputs, version or actor")
                return existing, []
            version = session.get(WorkflowVersion, payload.version_id)
            if workflow.archived_at or version is None or version.workflow_id != workflow_id:
                raise WorkflowConflict("The saved version is unavailable or the workflow is archived")
            run = WorkflowRun(
                workflow_id=workflow_id,
                version_id=payload.version_id,
                initiating_user_id=user_id,
                initiating_membership_id=membership_id,
                client_request_id=payload.client_request_id,
                request_hash=request_hash,
                inputs=payload.model_dump(mode="json")["inputs"],
                runtime=runtime,
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
            delivery_ids = self._event(session, run, "STARTED", f"Run started using version {version.number}")
            session.commit()
            return run, delivery_ids

    def cancel(self, run_id: UUID, agent_id: UUID, scope: AuthorizationScope, revision: int) -> list[UUID]:
        with Session(self.delegate.engine) as session:
            run = session.exec(
                self.scoped(agent_id, scope).where(col(WorkflowRun.id) == run_id).with_for_update(of=WorkflowRun)
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
            delivery_ids = self._event(session, run, "CANCEL_REQUESTED", run.reason)
            session.commit()
            return delivery_ids

    def _authorized(self, session: Session, run: WorkflowRun) -> bool:
        membership = (
            session.get(OrganizationUser, run.initiating_membership_id) if run.initiating_membership_id else None
        )
        if membership is None or membership.user_id != run.initiating_user_id:
            return False
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
        workflow = session.get_one(Workflow, run.workflow_id)
        return (
            session.exec(
                select(Agent).where(
                    col(Agent.id) == workflow.agent_id,
                    col(Agent.status) == AgentStatus.RUNNING,
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
        """Publication authority comes from an authenticated owning Agent, never the completion bearer."""
        attempt = session.get(WorkflowAttempt, attempt_id)
        if attempt is None:
            raise WorkflowConflict("Workflow attempt not found")
        run = session.get_one(WorkflowRun, attempt.run_id)
        workflow = session.get_one(Workflow, run.workflow_id)
        if workflow.agent_id != agent_id:
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
            run.state, run.reason = "BLOCKED", failure.reason
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
        release(session, "run", run.id, self.config.artifact_retention_days)
        run.settled_at = datetime.now(UTC)

    def active_ids(self, limit: int = 100) -> list[UUID]:
        """Operator/controller-only scan; HTTP callers use scoped queries above."""
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(WorkflowRun.id)
                    .where(col(WorkflowRun.state).not_in(TERMINAL_STATES))
                    .order_by(col(WorkflowRun.updated_at))
                    .limit(limit)
                )
            )

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
            workflow = session.get_one(Workflow, run.workflow_id)
            agent = session.get(Agent, workflow.agent_id)
            if agent is None or agent.deleted_at is not None:
                run.state = "CANCELLING"
            attempt = session.exec(
                select(WorkflowAttempt).where(
                    col(WorkflowAttempt.run_id) == run.id, col(WorkflowAttempt.generation) == run.generation
                )
            ).one_or_none()
            if run.state == "PAUSED" and (attempt is None or attempt.state not in {"REASONING", "STOPPING"}):
                return None, []
            authorized = self._authorized(session, run)
            if not authorized and run.state != "CANCELLING":
                run.state, run.reason = "PAUSED", "Initiator authority or Agent lifecycle changed"
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
                elif expired and authorized and run.state != "PAUSED":
                    run.state, run.reason = (
                        "BLOCKED",
                        "Attempt outcome is uncertain; inspect external effects before starting another run",
                    )
                run.revision += 1
                delivery_ids = self._event(session, run, "FENCED", run.reason or "Attempt stopped")
                session.commit()
                return None, delivery_ids
            if run.state != "QUEUED":
                return (attempt if attempt and attempt.state == "REASONING" else None), []
            run.generation += 1
            run.state, run.reason = "RUNNING", None
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
                session, run, "ATTEMPT_STARTED", f"Step {run.next_step + 1} started in a fresh session"
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
            session.commit()

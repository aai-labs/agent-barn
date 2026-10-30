import hmac
import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from fastapi import HTTPException
from injector import inject, singleton
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, col, select
from sqlmodel.sql.expression import SelectOfScalar

from api.core.config import Config
from api.domains.agents.models import Agent, AgentStatus
from api.domains.agents.repository import agent_scope_predicates
from api.domains.artifacts import config as artifact_config
from api.domains.artifacts.buckets import ArtifactBucketRepository, bucket_name
from api.domains.artifacts.credentials import runtime_token
from api.domains.artifacts.models import Artifact, ArtifactCreate, ArtifactReference
from api.domains.rbac.policy import AuthorizationScope
from api.domains.workflows.models import WorkflowVersion
from api.domains.workflows.run_models import TERMINAL_STATES, WorkflowRun
from api.domains.workflows.run_repository import WorkflowRunRepository
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


def object_key(row: Artifact) -> str:
    return f"artifacts/{row.organization_id}/{row.agent_id}/{row.id}"


class PublicationBusy(HTTPException):
    """Retryable contention must never mark another publication's file as failed."""

    def __init__(self) -> None:
        super().__init__(409, "Artifact publication in progress; retry this artifact")


@inject
@singleton
@dataclass
class ArtifactRepository:
    delegate: PostgresRepositoryDelegate
    workflows: WorkflowRunRepository
    config: Config
    buckets: ArtifactBucketRepository

    def authenticate(self, token: str) -> Agent:
        try:
            agent_id = UUID(token.split(".", 1)[0])
        except ValueError:
            raise HTTPException(401, "Invalid artifact credential") from None
        with Session(self.delegate.engine) as session:
            agent = session.get(Agent, agent_id)
            if not agent or agent.deleted_at or agent.status != AgentStatus.RUNNING or not agent.ingest_key_encrypted:
                raise HTTPException(401, "Invalid artifact credential")
            key = decrypt_token(agent.ingest_key_encrypted, self.config.agent_token_encryption_key)
            if not hmac.compare_digest(token, runtime_token(agent.id, key)):
                raise HTTPException(401, "Invalid artifact credential")
            return agent

    @staticmethod
    def scoped(agent_id: UUID, scope: AuthorizationScope) -> SelectOfScalar[Artifact]:
        return (
            select(Artifact)
            .join(Agent, col(Agent.id) == col(Artifact.agent_id))
            .where(
                col(Artifact.agent_id) == agent_id,
                col(Artifact.organization_id) == scope.organization_id,
                *agent_scope_predicates(scope),
            )
        )

    def get(self, artifact_id: UUID, agent_id: UUID, scope: AuthorizationScope) -> Artifact:
        with Session(self.delegate.engine) as session:
            row = session.exec(self.scoped(agent_id, scope).where(col(Artifact.id) == artifact_id)).one_or_none()
            if row is None or row.state not in {"READY", "UPLOADING"}:
                raise HTTPException(404, "Artifact not found")
            return row

    def list_ready(
        self,
        agent_id: UUID,
        scope: AuthorizationScope,
        page: int,
        size: int,
        run_id: UUID | None = None,
        step_id: UUID | None = None,
    ) -> tuple[list[Artifact], int]:
        with Session(self.delegate.engine) as session:
            query = self.scoped(agent_id, scope).where(col(Artifact.state) == "READY")
            if run_id:
                query = query.where(col(Artifact.run_id) == run_id)
            if step_id:
                query = query.where(col(Artifact.step_id) == step_id)
            total = session.exec(select(sa.func.count()).select_from(query.subquery())).one()
            rows = session.exec(
                query.order_by(col(Artifact.created_at).desc(), col(Artifact.id).desc())
                .offset((page - 1) * size)
                .limit(size)
            ).all()
            return list(rows), total

    def create(
        self,
        agent_id: UUID,
        scope: AuthorizationScope,
        payload: ArtifactCreate,
        source: str,
        user_id: UUID | None,
        attempt_id: UUID | None,
    ) -> Artifact:
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            run = attempt = None
            if attempt_id:
                run, attempt = self.workflows.artifact_attempt(session, attempt_id, agent_id)
                files = session.exec(
                    select(Artifact).where(
                        col(Artifact.run_id) == run.id, col(Artifact.state).in_(["UPLOADING", "READY"])
                    )
                ).all()
                if sum(item.attempt_id == attempt_id for item in files) >= artifact_config.MAX_FILES_PER_ATTEMPT:
                    raise HTTPException(
                        409,
                        f"Workflow attempt file limit reached ({artifact_config.MAX_FILES_PER_ATTEMPT}); combine files or use an archive",
                    )
                # Reserve context for text; names and UTF-8 width count towards the file budget.
                entries = [
                    {
                        "artifact_id": str(item.id),
                        "checksum": item.checksum,
                        "filename": item.filename,
                        "size": item.size,
                    }
                    for item in files
                ]
                entries.append(
                    {
                        "artifact_id": str(agent_id),
                        "checksum": payload.checksum,
                        "filename": payload.filename,
                        "size": payload.size,
                    }
                )
                if len(json.dumps(entries, ensure_ascii=False).encode()) > artifact_config.MAX_RUN_FILE_CONTEXT_BYTES:
                    raise HTTPException(
                        409,
                        f"Workflow file-reference context limit reached ({artifact_config.MAX_RUN_FILE_CONTEXT_BYTES} bytes)",
                    )
            agent = session.exec(
                select(Agent).where(col(Agent.id) == agent_id, *agent_scope_predicates(scope))
            ).one_or_none()
            if not agent:
                raise HTTPException(404, "Agent not found")
            try:
                bucket = self.buckets.ready_name(agent.id, agent.organization_id, session)
            except ValueError:
                raise HTTPException(503, "Agent file storage is initializing; retry shortly") from None
            if source == "chat":
                # Serialize admission for this Agent so simultaneous identical uploads
                # share one staging identity before either has finished publishing.
                session.connection().execute(
                    sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                    {"key": f"chat-artifact:{agent.organization_id}:{agent.id}"},
                )
                existing = session.exec(
                    self.scoped(agent_id, scope)
                    .where(
                        col(Artifact.bucket) == bucket,
                        col(Artifact.filename) == payload.filename,
                        col(Artifact.size) == payload.size,
                        col(Artifact.checksum) == payload.checksum,
                        col(Artifact.expires_at) > datetime.now(UTC),
                        sa.or_(
                            col(Artifact.state) == "READY",
                            sa.and_(col(Artifact.source) == "chat", col(Artifact.state) == "UPLOADING"),
                        ),
                    )
                    .order_by(sa.case((col(Artifact.state) == "READY", 0), else_=1), col(Artifact.created_at))
                ).first()
                if existing is not None:
                    return existing
            row = Artifact(
                **payload.model_dump(),
                organization_id=agent.organization_id,
                agent_id=agent.id,
                bucket=bucket,
                object_key="pending",
                source=source,
                created_by_user_id=user_id,
                expires_at=datetime.now(UTC) + timedelta(hours=1),
            )
            row.object_key = object_key(row)
            if run is not None and attempt is not None:
                version = session.get_one(WorkflowVersion, run.version_id)
                row.workflow_id, row.run_id = run.workflow_id, run.id
                row.attempt_id, row.generation = attempt.id, attempt.generation
                row.step_id = UUID(version.snapshot["steps"][attempt.step_index]["id"])
            session.add(row)
            session.commit()
            return row

    @contextmanager
    def publication(
        self,
        artifact_id: UUID,
        agent_id: UUID,
        scope: AuthorizationScope,
        *,
        runtime: bool,
        revalidate: Callable[[], None],
    ) -> Iterator[Artifact]:
        snapshot = self.get(artifact_id, agent_id, scope)
        if snapshot.attempt_id:
            if not runtime:
                raise HTTPException(403, "Workflow publication requires the owning runtime credential")
            with Session(self.delegate.engine) as admission:
                self.workflows.artifact_attempt(admission, snapshot.attempt_id, agent_id, lock=False)
        # Only the file lock crosses storage I/O. Cancel, completion and reconciliation
        # can acquire the run lock while an upload is in flight.
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            row = self._publication_row(session, artifact_id, agent_id, scope)
            yield row
            session.commit()
        # Release the file lock before acquiring run -> file locks, matching settlement.
        # An intervening deletion or attempt change fences finalization instead of
        # publishing bytes that lost their owner/authority while S3 was being written.
        revalidate()
        with Session(self.delegate.engine, expire_on_commit=False) as session:
            if snapshot.attempt_id:
                self.workflows.artifact_attempt(session, snapshot.attempt_id, agent_id)
            finalized = self._publication_row(session, artifact_id, agent_id, scope)
            if finalized.state == "UPLOADING":
                finalized.state, finalized.published_at = "READY", datetime.now(UTC)
                finalized.expires_at = finalized.published_at + timedelta(days=self.config.artifact_retention_days)
                if finalized.run_id:
                    session.add(
                        ArtifactReference(
                            artifact_id=finalized.id, checksum=finalized.checksum, kind="run", owner_id=finalized.run_id
                        )
                    )
                session.add(finalized)
            session.commit()
            row.state, row.published_at, row.expires_at = finalized.state, finalized.published_at, finalized.expires_at

    def _publication_row(
        self, session: Session, artifact_id: UUID, agent_id: UUID, scope: AuthorizationScope
    ) -> Artifact:
        try:
            row = session.exec(
                self.scoped(agent_id, scope)
                .where(col(Artifact.id) == artifact_id)
                .with_for_update(of=Artifact, nowait=True)
            ).one_or_none()
        except OperationalError as exc:
            if (getattr(exc.orig, "sqlstate", None) or getattr(exc.orig, "pgcode", None)) == "55P03":
                raise PublicationBusy() from exc
            raise
        if row is None or row.state not in {"UPLOADING", "READY"}:
            raise HTTPException(409, "Artifact is no longer publishable")
        if row.state == "UPLOADING" and row.expires_at <= datetime.now(UTC):
            raise HTTPException(409, "Upload expired")
        return row

    def failed(self, artifact_id: UUID) -> None:
        with Session(self.delegate.engine) as session:
            session.exec(
                sa.update(Artifact)
                .where(col(Artifact.id) == artifact_id, col(Artifact.state) == "UPLOADING")
                .values(state="DELETING", expires_at=datetime.now(UTC))
            )
            session.commit()

    def delete(self, artifact_id: UUID, agent_id: UUID, scope: AuthorizationScope) -> None:
        with Session(self.delegate.engine) as session:
            row = session.exec(
                self.scoped(agent_id, scope).where(col(Artifact.id) == artifact_id).with_for_update(of=Artifact)
            ).one_or_none()
            if row is None or row.state == "DELETED":
                raise HTTPException(404, "Artifact not found")
            if session.exec(
                select(ArtifactReference).where(
                    col(ArtifactReference.artifact_id) == row.id, col(ArtifactReference.released_at).is_(None)
                )
            ).first():
                raise HTTPException(409, "An active run or review pins this file")
            row.state, row.expires_at = "DELETING", datetime.now(UTC)
            session.add(row)
            session.commit()

    def cleanup_candidates(self, limit: int = 100) -> list[UUID]:
        """Operator-only scan. Owner loss cannot cascade away cleanup evidence."""
        now = datetime.now(UTC)
        with Session(self.delegate.engine) as session:
            # Releases are normally transactional with settlement; repair deleted run owners too.
            refs = session.exec(
                select(ArtifactReference)
                .outerjoin(WorkflowRun, col(WorkflowRun.id) == col(ArtifactReference.owner_id))
                .where(
                    col(ArtifactReference.released_at).is_(None),
                    col(ArtifactReference.kind) == "run",
                    sa.or_(col(WorkflowRun.id).is_(None), col(WorkflowRun.state).in_(TERMINAL_STATES)),
                )
                .limit(limit)
            ).all()
            for ref in refs:
                run = session.get(WorkflowRun, ref.owner_id)
                if run is None or run.state in TERMINAL_STATES:
                    artifact = session.exec(
                        select(Artifact).where(col(Artifact.id) == ref.artifact_id).with_for_update()
                    ).one()
                    ref.released_at = now
                    session.add(ref)
                    if artifact.state == "READY":
                        artifact.expires_at = now + timedelta(days=self.config.artifact_retention_days)
                    session.add(artifact)
            session.flush()
            pinned = sa.exists(
                select(ArtifactReference.id).where(
                    col(ArtifactReference.artifact_id) == col(Artifact.id), col(ArtifactReference.released_at).is_(None)
                )
            )
            rows = session.exec(
                select(Artifact)
                .outerjoin(Agent, col(Agent.id) == col(Artifact.agent_id))
                .where(
                    col(Artifact.state) != "DELETED",
                    sa.or_(col(Artifact.state) != "DELETING", col(Artifact.expires_at) <= now),
                    sa.or_(
                        col(Agent.id).is_(None),
                        col(Agent.deleted_at).is_not(None),
                        sa.and_(col(Artifact.expires_at) <= now, ~pinned),
                    ),
                )
                .order_by(col(Artifact.expires_at))
                .limit(limit)
                .with_for_update(of=Artifact, skip_locked=True)
            ).all()
            ids = []
            for row in rows:
                # The selection snapshot may predate a reference-only pin commit.
                # Recheck under the artifact lock in a fresh statement; pin() takes
                # this same lock, so a successful live-owner pin cannot be lost.
                live_owner = sa.exists(
                    select(Agent.id).where(col(Agent.id) == row.agent_id, col(Agent.deleted_at).is_(None))
                )
                active_reference = session.exec(
                    select(ArtifactReference.id)
                    .where(
                        col(ArtifactReference.artifact_id) == row.id,
                        col(ArtifactReference.released_at).is_(None),
                        live_owner,
                    )
                    .limit(1)
                ).first()
                if active_reference is not None:
                    continue
                if row.state != "DELETING":
                    row.expires_at = now
                row.state = "DELETING"
                session.add(row)
                ids.append(row.id)
            session.commit()
            return ids

    @contextmanager
    def purge_target(self, artifact_id: UUID) -> Iterator[Artifact | None]:
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(Artifact).where(col(Artifact.id) == artifact_id).with_for_update(skip_locked=True)
            ).one_or_none()
            if row is None or row.state != "DELETING":
                yield None
                return
            row.purge_attempts += 1
            try:
                if row.bucket != bucket_name(row.agent_id) or row.object_key != object_key(row):
                    raise ValueError("Unsafe artifact purge target")
                yield row
            except Exception:
                row.expires_at = datetime.now(UTC) + timedelta(seconds=min(3600, 2 ** min(row.purge_attempts, 12)))
                session.add(row)
                session.commit()
                raise
            row.state = "DELETED"
            session.add(row)
            session.commit()

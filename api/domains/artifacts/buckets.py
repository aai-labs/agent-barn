"""Tenant-bound credentials and the durable operator-only bucket/key journal."""

import logging
import secrets
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, col, select

from api.core.config import Config
from api.domains.agents.models import Agent
from api.domains.artifacts.models import Artifact, ArtifactBucket
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

logger = logging.getLogger(__name__)


def bucket_name(agent_id: UUID) -> str:
    return f"agent-artifacts-{agent_id.hex}"


@dataclass(frozen=True)
class BucketCredentials:
    name: str
    access_key: str
    secret_key: str = field(repr=False)


@dataclass(frozen=True)
class BucketWork:
    bucket: ArtifactBucket
    owner_deleted: bool
    has_files: bool


@inject
@singleton
@dataclass
class ArtifactBucketRepository:
    delegate: PostgresRepositoryDelegate
    config: Config

    def ready_name(self, agent_id: UUID, organization_id: UUID, session: Session) -> str:
        row = session.exec(
            select(ArtifactBucket).where(
                col(ArtifactBucket.agent_id) == agent_id,
                col(ArtifactBucket.organization_id) == organization_id,
                col(ArtifactBucket.state) == "READY",
            )
        ).one_or_none()
        if row is None or row.name != bucket_name(agent_id):
            raise ValueError("Agent file storage is not ready")
        return row.name

    def credentials(self, artifact: Artifact) -> BucketCredentials:
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(ArtifactBucket).where(
                    col(ArtifactBucket.agent_id) == artifact.agent_id,
                    col(ArtifactBucket.organization_id) == artifact.organization_id,
                    col(ArtifactBucket.name) == artifact.bucket,
                    col(ArtifactBucket.state).in_(["READY", "DELETING"]),
                )
            ).one_or_none()
            if row is None or row.name != bucket_name(artifact.agent_id):
                raise ValueError("Invalid Agent storage target")
            return BucketCredentials(
                row.name,
                row.access_key,
                decrypt_token(row.secret_key_encrypted, self.config.agent_token_encryption_key),
            )

    def request_buckets(self, limit: int) -> None:
        """Operator-only scan: derive ownership exclusively from live persisted Agents."""
        if not self.config.artifact_s3_endpoint_url:
            return
        with Session(self.delegate.engine) as session:
            agents = session.exec(
                select(Agent)
                .outerjoin(ArtifactBucket, col(ArtifactBucket.agent_id) == col(Agent.id))
                .where(col(Agent.deleted_at).is_(None), col(ArtifactBucket.id).is_(None))
                .order_by(col(Agent.id))
                .limit(limit)
                .with_for_update(of=Agent, skip_locked=True)
            ).all()
            for agent in agents:
                session.add(
                    ArtifactBucket(
                        organization_id=agent.organization_id,
                        agent_id=agent.id,
                        name=bucket_name(agent.id),
                        access_key="GK" + secrets.token_hex(16),
                        secret_key_encrypted=encrypt_token(
                            secrets.token_hex(32), self.config.agent_token_encryption_key
                        ),
                        retry_at=datetime.now(UTC),
                    )
                )
            # Persist intent and key material BEFORE any provider I/O.
            session.commit()

    def due(self, limit: int) -> list[UUID]:
        with Session(self.delegate.engine) as session:
            return list(
                session.exec(
                    select(ArtifactBucket.id)
                    .outerjoin(Agent, col(Agent.id) == col(ArtifactBucket.agent_id))
                    .where(
                        col(ArtifactBucket.state) != "DELETED",
                        col(ArtifactBucket.retry_at) <= datetime.now(UTC),
                        sa.or_(
                            col(ArtifactBucket.state).in_(["PENDING", "DELETING"]),
                            col(Agent.id).is_(None),
                            col(Agent.deleted_at).is_not(None),
                        ),
                    )
                    .order_by(col(ArtifactBucket.retry_at), col(ArtifactBucket.id))
                    .limit(limit)
                ).all()
            )

    @contextmanager
    def operation(self, bucket_id: UUID) -> Iterator[BucketWork | None]:
        """Serialize bounded provider work per bucket, not on the owning Agent."""
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(ArtifactBucket).where(col(ArtifactBucket.id) == bucket_id).with_for_update(skip_locked=True)
            ).one_or_none()
            now = datetime.now(UTC)
            if row is None or row.state == "DELETED" or row.retry_at > now:
                yield None
                return
            row.attempts += 1
            try:
                if row.name != bucket_name(row.agent_id):
                    raise ValueError("Unsafe Agent bucket target")
                agent = session.get(Agent, row.agent_id)
                if agent and agent.organization_id != row.organization_id:
                    raise ValueError("Bucket owner Organization mismatch")
                owner_deleted = agent is None or agent.deleted_at is not None
                outstanding = (
                    owner_deleted
                    and session.exec(
                        select(Artifact.id)
                        .where(col(Artifact.agent_id) == row.agent_id, col(Artifact.state) != "DELETED")
                        .limit(1)
                    ).first()
                    is not None
                )
                yield BucketWork(row, owner_deleted, outstanding)
                row.last_error = None
                row.attempts = 0
                row.retry_at = now + timedelta(seconds=10)
            except Exception as exc:
                row.last_error = type(exc).__name__
                row.retry_at = now + timedelta(seconds=min(3600, 2 ** min(row.attempts, 12)))
                logger.warning("Agent bucket %s will retry (%s)", row.id, type(exc).__name__)
                session.add(row)
                session.commit()
                raise
            session.add(row)
            session.commit()

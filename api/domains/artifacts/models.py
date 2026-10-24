"""Immutable Agent files; ownership survives aggregate deletion for retryable cleanup."""

import unicodedata
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from pydantic import BaseModel as DTO
from pydantic import ConfigDict, Field, field_validator
from sqlmodel import Field as SqlField

from api.infrastructure.postgres.models import BaseModel


class Artifact(BaseModel, table=True):
    __tablename__: str = "artifact"
    __table_args__ = (
        sa.CheckConstraint("state IN ('UPLOADING','READY','DELETING','DELETED')", name="ck_artifact_state"),
        sa.CheckConstraint("size >= 0", name="ck_artifact_size"),
    )
    # Deliberately no cascading owner/provenance FKs: these rows are the object deletion journal.
    organization_id: UUID = SqlField(index=True)
    agent_id: UUID = SqlField(index=True)
    filename: str
    content_type: str
    size: int = SqlField(sa_type=sa.BigInteger)
    checksum: str
    state: str = "UPLOADING"
    bucket: str
    object_key: str = SqlField(unique=True)
    published_at: datetime | None = SqlField(default=None, sa_column=sa.Column(sa.DateTime(timezone=True)))
    expires_at: datetime = SqlField(sa_column=sa.Column(sa.DateTime(timezone=True), nullable=False, index=True))
    workflow_id: UUID | None = None
    run_id: UUID | None = SqlField(default=None, index=True)
    step_id: UUID | None = None
    attempt_id: UUID | None = None
    generation: int | None = None
    source: str
    created_by_user_id: UUID | None = None
    purge_attempts: int = 0


class ArtifactReference(BaseModel, table=True):
    __tablename__: str = "artifact_reference"
    __table_args__ = (sa.UniqueConstraint("artifact_id", "kind", "owner_id", name="uq_artifact_reference"),)
    artifact_id: UUID = SqlField(foreign_key="artifact.id", ondelete="CASCADE", index=True)
    checksum: str
    kind: str  # run/checkpoint/review; only trusted services can acquire/release references.
    owner_id: UUID = SqlField(index=True)
    released_at: datetime | None = SqlField(default=None, sa_column=sa.Column(sa.DateTime(timezone=True)))


class ArtifactCreate(DTO):
    model_config = ConfigDict(extra="forbid")
    filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(
        default="application/octet-stream", min_length=1, max_length=128, pattern=r"^[\w.+-]+/[\w.+-]+$"
    )
    size: int = Field(ge=0)
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value: str) -> str:
        if value in {".", ".."} or any(unicodedata.category(c) in {"Cc", "Cf"} or c in "/\\" for c in value):
            raise ValueError("Provide a display filename, without paths or control characters")
        return value


class ArtifactRead(DTO):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    filename: str
    content_type: str
    size: int
    checksum: str
    state: str
    source: str
    published_at: datetime | None
    workflow_id: UUID | None
    run_id: UUID | None
    step_id: UUID | None
    attempt_id: UUID | None


class ArtifactLinkRead(DTO):
    artifact: ArtifactRead
    url: str
    expires_at: datetime

"""Transaction-local immutable handoff and pin operations for trusted workflow/review services."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import Session, col, select

from api.domains.artifacts.models import Artifact, ArtifactReference


def pin(
    session: Session, artifact_id: UUID, checksum: str, agent_id: UUID, organization_id: UUID, kind: str, owner_id: UUID
) -> None:
    artifact = session.exec(select(Artifact).where(col(Artifact.id) == artifact_id).with_for_update()).one_or_none()
    if (
        artifact is None
        or artifact.agent_id != agent_id
        or artifact.organization_id != organization_id
        or artifact.state != "READY"
    ):
        raise HTTPException(404, "Artifact not found")
    if artifact.checksum != checksum:
        raise HTTPException(409, "Artifact checksum does not match the immutable reference")
    existing = session.exec(
        select(ArtifactReference).where(
            col(ArtifactReference.artifact_id) == artifact_id,
            col(ArtifactReference.kind) == kind,
            col(ArtifactReference.owner_id) == owner_id,
        )
    ).one_or_none()
    if existing is None:
        session.add(ArtifactReference(artifact_id=artifact_id, checksum=checksum, kind=kind, owner_id=owner_id))
    elif existing.released_at is not None:
        raise HTTPException(409, "Released artifact references cannot be reactivated")


def pin_published(
    session: Session, artifact_id: UUID, agent_id: UUID, organization_id: UUID, kind: str, owner_id: UUID
) -> Artifact:
    """Pin a READY Artifact by id alone, for owners that never recorded its checksum.

    The row is locked on this first read: `pin` locks it again, but the session hands back
    this same object without refreshing it, so an unlocked read here would check stale state."""
    artifact = session.exec(select(Artifact).where(col(Artifact.id) == artifact_id).with_for_update()).one_or_none()
    if artifact is None:
        raise HTTPException(404, "Artifact not found")
    pin(session, artifact_id, artifact.checksum, agent_id, organization_id, kind, owner_id)
    return artifact


def attempt_files(session: Session, attempt_id: UUID) -> list[dict]:
    rows = session.exec(
        select(Artifact)
        .where(col(Artifact.attempt_id) == attempt_id, col(Artifact.state) == "READY")
        .order_by(col(Artifact.created_at))
    ).all()
    return [
        {"artifact_id": str(row.id), "checksum": row.checksum, "filename": row.filename, "size": row.size}
        for row in rows
    ]


def release(session: Session, kind: str, owner_id: UUID, retention_days: int) -> None:
    refs = session.exec(
        select(ArtifactReference)
        .where(
            col(ArtifactReference.kind) == kind,
            col(ArtifactReference.owner_id) == owner_id,
            col(ArtifactReference.released_at).is_(None),
        )
        .order_by(col(ArtifactReference.artifact_id))
    ).all()
    _release_references(session, refs, retention_days)


def release_beyond_newest(session: Session, kind: str, agent_id: UUID, keep: int, retention_days: int) -> None:
    """Release the Agent's `kind` pins past its newest `keep`, oldest first to go."""
    refs = session.exec(
        select(ArtifactReference)
        .join(Artifact, col(Artifact.id) == col(ArtifactReference.artifact_id))
        .where(
            col(ArtifactReference.kind) == kind,
            col(ArtifactReference.released_at).is_(None),
            col(Artifact.agent_id) == agent_id,
        )
        .order_by(col(ArtifactReference.id).desc())
        .offset(keep)
    ).all()
    _release_references(session, refs, retention_days)


def _release_references(session: Session, refs: Sequence[ArtifactReference], retention_days: int) -> None:
    now = datetime.now(UTC)
    for ref in refs:
        artifact = session.exec(select(Artifact).where(col(Artifact.id) == ref.artifact_id).with_for_update()).one()
        ref.released_at = now
        if artifact.state == "READY":
            artifact.expires_at = now + timedelta(days=retention_days)
        session.add(ref)
        session.add(artifact)

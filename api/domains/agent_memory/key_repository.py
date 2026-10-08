import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.agent_memory.models import MemoryKeyRevocation, OrganizationMemoryKey
from api.domains.organizations.models import Organization
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class MemoryKeyRepository:
    delegate: PostgresRepositoryDelegate

    @staticmethod
    def _try_revoke(revoke: Callable[[str], bool], key_hash: str) -> bool:
        try:
            return revoke(key_hash)
        except Exception as exc:
            logger.warning("Memory credential revocation deferred: %s", type(exc).__name__)
            return False

    @staticmethod
    def _lock(session: Session, organization_id: UUID) -> None:
        session.connection().execute(
            sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
            {"key": f"organization-memory-key:{organization_id}"},
        )

    def resolve(
        self,
        organization_id: UUID,
        encryption_key: str,
        create: Callable[[], str],
        validate: Callable[[str], bool],
        revoke: Callable[[str], bool],
    ) -> str:
        with Session(self.delegate.engine) as session:
            self._lock(session, organization_id)
            organization = session.exec(select(Organization).where(Organization.id == organization_id)).first()
            if organization is None:
                raise ValueError("Organization not found")
            row = session.exec(
                select(OrganizationMemoryKey).where(OrganizationMemoryKey.organization_id == organization_id)
            ).first()
            if row:
                key = decrypt_token(row.key_encrypted, encryption_key)
                if validate(key):
                    return key
                session.add(MemoryKeyRevocation(organization_id=organization_id, key_hash=row.key_hash))
            key = create()
            key_hash = hashlib.sha256(key.encode()).hexdigest()
            try:
                if row is None:
                    row = OrganizationMemoryKey(
                        organization_id=organization_id,
                        key_encrypted=encrypt_token(key, encryption_key),
                        key_hash=key_hash,
                    )
                else:
                    row.key_encrypted = encrypt_token(key, encryption_key)
                    row.key_hash = key_hash
                session.add(row)
                session.commit()
            except Exception:
                session.rollback()
                # Remote issuance cannot participate in the database transaction.
                # Revoke immediately; persist a retry if the proxy is unavailable.
                if not self._try_revoke(revoke, key_hash):
                    session.add(MemoryKeyRevocation(organization_id=organization_id, key_hash=key_hash))
                    session.commit()
                raise
        self.revoke_pending(revoke, organization_id=organization_id)
        return key

    def enqueue_deletion(self, organization_id: UUID, session: Session) -> None:
        self._lock(session, organization_id)
        completed = session.exec(
            select(MemoryKeyRevocation).where(
                MemoryKeyRevocation.organization_id == organization_id,
                col(MemoryKeyRevocation.revoked_at).is_not(None),
            )
        ).all()
        for completed_row in completed:
            session.delete(completed_row)
        row = session.exec(
            select(OrganizationMemoryKey).where(OrganizationMemoryKey.organization_id == organization_id)
        ).first()
        if row:
            session.add(MemoryKeyRevocation(organization_id=organization_id, key_hash=row.key_hash))

    def revoke_pending(
        self,
        revoke: Callable[[str], bool],
        limit: int = 20,
        organization_id: UUID | None = None,
    ) -> int:
        removed = 0
        with Session(self.delegate.engine) as session:
            # A cleanup may complete concurrently with Organization deletion.
            orphaned = session.exec(
                select(MemoryKeyRevocation)
                .where(
                    col(MemoryKeyRevocation.revoked_at).is_not(None),
                    ~col(MemoryKeyRevocation.organization_id).in_(select(Organization.id)),
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).all()
            for row in orphaned:
                session.delete(row)
            query = select(MemoryKeyRevocation).where(col(MemoryKeyRevocation.revoked_at).is_(None))
            if organization_id is not None:
                query = query.where(MemoryKeyRevocation.organization_id == organization_id)
            rows = session.exec(
                query.order_by(col(MemoryKeyRevocation.updated_at)).limit(limit).with_for_update(skip_locked=True)
            ).all()
            for row in rows:
                if self._try_revoke(revoke, row.key_hash):
                    if session.get(Organization, row.organization_id) is None:
                        session.delete(row)
                    else:
                        row.revoked_at = datetime.now(UTC)
                        session.add(row)
                    removed += 1
                else:
                    row.updated_at = datetime.now(UTC)
                    session.add(row)
            session.commit()
        return removed

    def hashes(self) -> dict[str, UUID]:
        with Session(self.delegate.engine) as session:
            current = {row.key_hash: row.organization_id for row in session.exec(select(OrganizationMemoryKey)).all()}
            # Retired hashes keep delayed billing attributable while their Organization exists.
            retired = session.exec(
                select(MemoryKeyRevocation).join(
                    Organization, col(Organization.id) == col(MemoryKeyRevocation.organization_id)
                )
            ).all()
            return {**current, **{row.key_hash: row.organization_id for row in retired}}

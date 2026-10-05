import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from injector import inject, singleton
from sqlmodel import Session, select

from api.domains.agent_memory.models import OrganizationMemoryKey
from api.domains.organizations.models import Organization
from api.infrastructure.crypto import decrypt_token, encrypt_token
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class MemoryKeyRepository:
    delegate: PostgresRepositoryDelegate

    def resolve(self, organization_id: UUID, encryption_key: str, create: Callable[[], str]) -> str:
        with Session(self.delegate.engine) as session:
            session.connection().execute(
                sa.text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"organization-memory-key:{organization_id}"},
            )
            organization = session.exec(select(Organization).where(Organization.id == organization_id)).first()
            if organization is None:
                raise ValueError("Organization not found")
            row = session.exec(
                select(OrganizationMemoryKey).where(OrganizationMemoryKey.organization_id == organization_id)
            ).first()
            if row:
                return decrypt_token(row.key_encrypted, encryption_key)
            key = create()
            session.add(
                OrganizationMemoryKey(
                    organization_id=organization_id,
                    key_encrypted=encrypt_token(key, encryption_key),
                    key_hash=hashlib.sha256(key.encode()).hexdigest(),
                )
            )
            session.commit()
            return key

    def hashes(self) -> dict[str, UUID]:
        with Session(self.delegate.engine) as session:
            return {row.key_hash: row.organization_id for row in session.exec(select(OrganizationMemoryKey)).all()}

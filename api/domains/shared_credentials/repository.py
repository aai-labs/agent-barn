from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentSecret
from api.domains.shared_credentials.exceptions import SharedCredentialNameConflictHTTPException
from api.domains.shared_credentials.models import (
    SharedCredential,
    SharedCredentialFilter,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate
from api.infrastructure.shared.models import Pagination


@inject
@singleton
@dataclass
class SharedCredentialRepository:
    delegate: PostgresRepositoryDelegate

    def save(self, credential: SharedCredential) -> SharedCredential:
        try:
            self.delegate.save(credential)
        except IntegrityError as e:
            if "uq_shared_credential_org_name" in str(e).lower():
                raise SharedCredentialNameConflictHTTPException(credential.name)
            raise
        return credential

    def get_by_id_and_org(self, credential_id: UUID, org_id: UUID) -> SharedCredential | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(SharedCredential)
                .where(col(SharedCredential.id) == credential_id)
                .where(col(SharedCredential.organization_id) == org_id)
            )
            return session.exec(query).first()

    def find_all_for_org(
        self,
        org_id: UUID,
        cred_filter: SharedCredentialFilter,
        pagination: Pagination,
    ) -> tuple[list[SharedCredential], int]:
        with Session(self.delegate.engine) as session:
            conditions = [col(SharedCredential.organization_id) == org_id]
            if cred_filter.search:
                conditions.append(col(SharedCredential.name).ilike(f"%{cred_filter.search}%"))
            if cred_filter.provider is not None:
                conditions.append(col(SharedCredential.provider) == cred_filter.provider)

            count_query = select(func.count()).select_from(SharedCredential)
            for condition in conditions:
                count_query = count_query.where(condition)
            total = session.scalar(count_query) or 0

            query = select(SharedCredential)
            for condition in conditions:
                query = query.where(condition)
            query = (
                query.order_by(col(SharedCredential.created_at).desc())
                .offset((pagination.page - 1) * pagination.size)
                .limit(pagination.size)
            )
            return list(session.exec(query).all()), total

    def find_all_briefs_for_org(self, org_id: UUID) -> list[SharedCredential]:
        with Session(self.delegate.engine) as session:
            query = (
                select(SharedCredential)
                .where(col(SharedCredential.organization_id) == org_id)
                .order_by(col(SharedCredential.name).asc())
            )
            return list(session.exec(query).all())

    def delete(self, credential: SharedCredential) -> None:
        self.delegate.delete(credential)

    def count_agent_references(self, credential_id: UUID) -> int:
        with Session(self.delegate.engine) as session:
            query = (
                select(func.count())
                .select_from(AgentSecret)
                .join(Agent, col(AgentSecret.agent_id) == col(Agent.id))
                .where(col(AgentSecret.shared_credential_id) == credential_id)
                .where(col(Agent.deleted_at).is_(None))
            )
            return session.scalar(query) or 0

    def delete_orphaned_references(self, credential_id: UUID) -> int:
        with Session(self.delegate.engine) as session:
            orphaned = (
                select(AgentSecret)
                .join(Agent, col(AgentSecret.agent_id) == col(Agent.id))
                .where(col(AgentSecret.shared_credential_id) == credential_id)
                .where(col(Agent.deleted_at).is_not(None))
            )
            rows = list(session.exec(orphaned).all())
            for row in rows:
                session.delete(row)
            if rows:
                session.commit()
            return len(rows)

    def get_by_ids_and_org(self, ids: list[UUID], org_id: UUID) -> list[SharedCredential]:
        if not ids:
            return []
        with Session(self.delegate.engine) as session:
            query = (
                select(SharedCredential)
                .where(col(SharedCredential.id).in_(ids))
                .where(col(SharedCredential.organization_id) == org_id)
            )
            return list(session.exec(query).all())

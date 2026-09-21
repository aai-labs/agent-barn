from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.memory_groups.exceptions import MemoryGroupNameConflictHTTPException
from api.domains.memory_groups.models import MemoryGroup
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class MemoryGroupRepository:
    delegate: PostgresRepositoryDelegate

    def save(self, group: MemoryGroup) -> MemoryGroup:
        try:
            self.delegate.save(group)
        except IntegrityError as e:
            if "uq_memory_group_org_name" in str(e).lower():
                raise MemoryGroupNameConflictHTTPException(group.name)
            raise
        return group

    def get_by_id_and_org(self, group_id: UUID, org_id: UUID) -> MemoryGroup | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(MemoryGroup)
                .where(col(MemoryGroup.id) == group_id)
                .where(col(MemoryGroup.organization_id) == org_id)
            )
            return session.exec(query).first()

    def find_all_for_org(self, org_id: UUID) -> list[MemoryGroup]:
        with Session(self.delegate.engine) as session:
            query = (
                select(MemoryGroup)
                .where(col(MemoryGroup.organization_id) == org_id)
                .order_by(col(MemoryGroup.name).asc())
            )
            return list(session.exec(query).all())

    def delete(self, group: MemoryGroup) -> None:
        self.delegate.delete(group)

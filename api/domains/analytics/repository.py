from dataclasses import dataclass, field
from uuid import UUID

from injector import inject, singleton
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, col, select

from api.domains.analytics.models import Installation
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class InstallationRepository:
    delegate: PostgresRepositoryDelegate
    _installation_id: UUID | None = field(default=None, init=False)

    def get_id(self) -> UUID:
        if self._installation_id is None:
            self._installation_id = self._get_or_create_id()
        return self._installation_id

    def _get_or_create_id(self) -> UUID:
        with Session(self.delegate.engine) as session:
            session.exec(
                insert(Installation).values(singleton=True).on_conflict_do_nothing(index_elements=["singleton"])
            )
            installation_id = session.exec(select(col(Installation.id))).one()
            session.commit()
            return installation_id

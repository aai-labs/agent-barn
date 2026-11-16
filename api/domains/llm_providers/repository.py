from dataclasses import dataclass

from injector import inject, singleton
from sqlmodel import Session, col, select

from api.domains.llm_providers.models import LlmProviderConnection
from api.domains.users.models import User
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class LlmProviderRepository:
    delegate: PostgresRepositoryDelegate

    def find_active(self, slug: str) -> tuple[LlmProviderConnection, str | None] | None:
        """The connection, and the name of whoever last changed it."""
        with Session(self.delegate.engine) as session:
            row = session.exec(
                select(LlmProviderConnection, User.full_name, User.email)
                .outerjoin(User, col(User.id) == col(LlmProviderConnection.updated_by))
                .where(LlmProviderConnection.slug == slug, col(LlmProviderConnection.deleted_at).is_(None))
            ).first()
        if row is None:
            return None
        connection, full_name, email = row
        return connection, full_name or email

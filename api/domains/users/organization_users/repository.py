from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, col, select

from api.domains.users.models import User
from api.domains.users.organization_users.exceptions import (
    OneOwnerPerOrganizationException,
    UserAlreadyPartOfOrganizationException,
)
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUser,
)
from api.infrastructure.postgres.repository import PostgresRepositoryDelegate


@inject
@singleton
@dataclass
class OrganizationUserRepository:
    delegate: PostgresRepositoryDelegate

    def get_by_user_id_and_organization_id(
        self, user_id: UUID, organization_id: UUID
    ) -> OrganizationUser | None:
        return self.delegate.find_one(
            OrganizationUser, user_id=user_id, organization_id=organization_id
        )

    def get_by_user_id(self, user_id: UUID) -> list[OrganizationUser]:
        return self.delegate.find_all(OrganizationUser, user_id=user_id)

    def save(self, user_organization: OrganizationUser) -> OrganizationUser:
        user_id = user_organization.user_id
        organization_id = user_organization.organization_id
        try:
            self.delegate.save(user_organization)
            return user_organization
        except IntegrityError as e:
            if "uq_user_organization_one_owner_per_org" in str(e).lower():
                raise OneOwnerPerOrganizationException(organization_id)
            if "uq_user_organization" in str(e).lower():
                raise UserAlreadyPartOfOrganizationException(user_id, organization_id)
            raise

    def save_with_session(
        self, user_organization: OrganizationUser, session: Session
    ) -> OrganizationUser:
        user_id = user_organization.user_id
        organization_id = user_organization.organization_id
        try:
            session.add(user_organization)
            session.flush()
            return user_organization
        except IntegrityError as e:
            if "uq_user_organization_one_owner_per_org" in str(e).lower():
                raise OneOwnerPerOrganizationException(organization_id)
            if "uq_user_organization" in str(e).lower():
                raise UserAlreadyPartOfOrganizationException(user_id, organization_id)
            raise

    def delete_all_by_user_id(self, user_id: UUID) -> bool:
        organization_users = self.get_by_user_id(user_id)
        if not organization_users:
            return True
        return self.delegate.delete_many(organization_users)

    def get_member_with_user(
        self, user_id: UUID, organization_id: UUID
    ) -> tuple[OrganizationUser, User] | None:
        with Session(self.delegate.engine) as session:
            query = (
                select(OrganizationUser, User)
                .join(User, col(User.id) == col(OrganizationUser.user_id))
                .where(
                    col(OrganizationUser.user_id) == user_id,
                    col(OrganizationUser.organization_id) == organization_id,
                )
            )
            return session.exec(query).first()

    def get_members_with_users(
        self,
        organization_id: UUID,
        *,
        search: str | None = None,
        limit: int | None = None,
    ) -> list[tuple[OrganizationUser, User]]:
        with Session(self.delegate.engine) as session:
            query = (
                select(OrganizationUser, User)
                .join(User, col(User.id) == col(OrganizationUser.user_id))
                .where(col(OrganizationUser.organization_id) == organization_id)
            )
            if search:
                pattern = f"%{search}%"
                query = query.where(
                    col(User.full_name).ilike(pattern) | col(User.email).ilike(pattern)
                )
            query = query.order_by(col(OrganizationUser.created_at).asc())
            if limit is not None:
                query = query.limit(limit)
            return list(session.exec(query).all())

    def delete(self, membership: OrganizationUser) -> bool:
        return self.delegate.delete(membership)

    def transfer_ownership(
        self, organization_id: UUID, current_owner_id: UUID, new_owner_id: UUID
    ) -> None:
        """Atomically demote the current owner to ADMIN and promote the new owner to
        OWNER. The demote must be flushed before the promote so the one-owner-per-org
        partial unique index is never violated mid-transaction."""
        with Session(self.delegate.engine) as session:
            current = session.exec(
                select(OrganizationUser).where(
                    col(OrganizationUser.organization_id) == organization_id,
                    col(OrganizationUser.user_id) == current_owner_id,
                )
            ).first()
            new = session.exec(
                select(OrganizationUser).where(
                    col(OrganizationUser.organization_id) == organization_id,
                    col(OrganizationUser.user_id) == new_owner_id,
                )
            ).first()
            if current is None or new is None:
                raise ValueError("Owner or target membership not found for transfer")

            current.role = OrganizationRole.ADMIN
            session.add(current)
            session.flush()
            new.role = OrganizationRole.OWNER
            session.add(new)
            session.flush()
            session.commit()

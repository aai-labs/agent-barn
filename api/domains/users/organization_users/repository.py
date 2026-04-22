from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session

from api.domains.users.organization_users.exceptions import (
    OneOwnerPerOrganizationException,
    UserAlreadyPartOfOrganizationException,
)
from api.domains.users.organization_users.models import OrganizationUser
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

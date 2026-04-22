from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.organization_users.exceptions import (
    UserAlreadyPartOfOrganizationException,
)
from api.domains.users.organization_users.models import (
    OrganizationUser,
    OrganizationUserRead,
)
from api.domains.users.organization_users.repository import OrganizationUserRepository


@inject
@singleton
@dataclass
class OrganizationUserService:
    organization_user_repository: OrganizationUserRepository
    organization_repository: OrganizationRepository

    def find_by_user_id_and_organization_id(
        self, user_id: UUID, organization_id: UUID
    ) -> OrganizationUserRead:
        organization_user = (
            self.organization_user_repository.get_by_user_id_and_organization_id(
                user_id, organization_id
            )
        )
        if not organization_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization user with user ID {user_id} and organization ID {organization_id} not found",
            )

        organization = self.organization_repository.get_read(
            organization_user.organization_id
        )
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
            )

        return OrganizationUserRead(
            **organization_user.model_dump(),
            organization=organization,
        )

    def create_user_organization(
        self, user_data: OrganizationUser
    ) -> OrganizationUserRead:
        try:
            organization = self.organization_repository.get_read(
                user_data.organization_id
            )
            if not organization:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Organization not found",
                )

            organization_user = self.organization_user_repository.save(user_data)
            return OrganizationUserRead(
                **organization_user.model_dump(),
                organization=organization,
            )
        except UserAlreadyPartOfOrganizationException as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User {e.user_id} is already part of organization {e.organization_id}",
            )

    def find_by_user_id(self, user_id: UUID) -> list[OrganizationUserRead]:
        organization_users = self.organization_user_repository.get_by_user_id(user_id)
        if not organization_users:
            return []

        organization_reads: list[OrganizationUserRead] = []
        for organization_user in organization_users:
            organization = self.organization_repository.get_read(
                organization_user.organization_id
            )
            if not organization:
                continue

            organization_reads.append(
                OrganizationUserRead(
                    **organization_user.model_dump(),
                    organization=organization,
                )
            )

        return organization_reads

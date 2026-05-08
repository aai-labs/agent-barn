from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.auth.models import CurrentUserContext
from api.domains.organizations.models import (
    Organization,
    OrganizationFilter,
    OrganizationRead,
    OrganizationUpdate,
)
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.organization_users.models import (
    OrganizationRole,
)
from api.domains.users.organization_users.service import OrganizationUserService
from api.infrastructure.shared.models import PaginatedItems, Pagination


@inject
@singleton
@dataclass
class OrganizationService:
    organization_repository: OrganizationRepository
    user_organization_service: OrganizationUserService

    def get_organization(self, organization_id: UUID) -> OrganizationRead:
        organization = self.organization_repository.get_read(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        return organization

    def ensure_default_organization(self) -> Organization:
        existing = self.organization_repository.find_default()
        if existing:
            return existing
        org = Organization(name="default", is_default=True)
        return self.organization_repository.save(org)

    def get_paginated_organizations(
        self,
        context: CurrentUserContext,
        org_filter: OrganizationFilter = OrganizationFilter(),
        page: int = 1,
        page_size: int = 15,
    ) -> PaginatedItems[OrganizationRead]:
        pagination = Pagination(page=page, size=page_size)
        user_id = None if context.user.is_superuser else context.user.id
        return self.organization_repository.find_all_paginated_read(
            pagination=pagination,
            organization_filter=org_filter,
            user_id=user_id,
        )

    def _ensure_can_manage_organization(self, context: CurrentUserContext) -> None:
        if context.user.is_superuser:
            return
        org_user = context.current_user_organization
        if not org_user or org_user.role not in {
            OrganizationRole.OWNER,
            OrganizationRole.ADMIN,
        }:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You don't have permission for this organization",
            )

    def update_organization(
        self,
        organization_id: UUID,
        organization_data: OrganizationUpdate,
        context: CurrentUserContext,
    ) -> OrganizationRead:
        self._ensure_can_manage_organization(context)
        organization = self.organization_repository.get(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )

        for key, value in organization_data.model_dump(exclude_unset=True).items():
            setattr(organization, key, value)
        organization = self.organization_repository.save(organization)

        organization_read = self.organization_repository.get_read(organization.id)
        if not organization_read:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to load organization",
            )
        return organization_read

    def delete_organization(
        self,
        organization_id: UUID,
        context: CurrentUserContext,
    ) -> None:
        self._ensure_can_manage_organization(context)
        organization = self.organization_repository.get(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        self.organization_repository.delete(organization.id)

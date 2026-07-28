from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlmodel import Session

from api.domains.agents.service import AgentService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.service import AuthService
from api.domains.organizations.models import (
    Organization,
    OrganizationCreate,
    OrganizationCreateResult,
    OrganizationFilter,
    OrganizationRead,
    OrganizationUpdate,
)
from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import ORG_OWNER_ONLY_ROLES, PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUser,
)
from api.domains.users.organization_users.service import OrganizationUserService
from api.infrastructure.shared.models import PaginatedItems, Pagination


@inject
@singleton
@dataclass
class OrganizationService:
    organization_repository: OrganizationRepository
    user_organization_service: OrganizationUserService
    auth_service: AuthService
    agent_service: AgentService
    permission_policy: PermissionPolicy

    def get_organization(self, organization_id: UUID, context: CurrentUserContext) -> OrganizationRead:
        # Any member (or a platform administrator in explicit Organization context) may
        # view the org; non-members are refused before the fetch so a 403-vs-404
        # difference can't confirm an org's existence.
        self._ensure_can_view_organization(organization_id, context)
        organization = self.organization_repository.get_read(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        return organization

    def create_organization(self, data: OrganizationCreate, actor: CurrentUserContext) -> OrganizationCreateResult:
        actor.require_platform_admin(detail="Only a platform administrator can create organizations")

        # Org, owner-invite (user + token) and the OWNER membership all commit together,
        # so a failed step can't leave an org with no owner. The invite email is sent
        # only after commit.
        organization = Organization(name=data.name, description=data.description)
        with Session(self.organization_repository.delegate.engine, expire_on_commit=False) as session:
            self.organization_repository.save_with_session(organization, session)
            prepared = self.auth_service.prepare_invite(session, email=str(data.owner_email), full_name=data.owner_name)
            self.user_organization_service.add_membership_with_session(
                OrganizationUser(
                    user_id=prepared.user.id,
                    organization_id=organization.id,
                    role=OrganizationRole.OWNER,
                ),
                session,
            )
            session.commit()

        # Predefined templates are global platform resources seeded once at
        # startup, so a new org needs no per-org catalog clone.
        self.auth_service.send_prepared_invite(prepared)

        organization_read = self.organization_repository.get_read(organization.id)
        if not organization_read:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to load organization",
            )
        return OrganizationCreateResult(organization=organization_read, invite_link=prepared.invite_link)

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

    def _ensure_can_view_organization(
        self,
        organization_id: UUID,
        context: CurrentUserContext,
    ) -> None:
        self.permission_policy.require_organization(
            context,
            organization_id,
            PermissionKey.ORGANIZATION_READ,
            detail="You don't have permission for this organization",
        )

    def _ensure_is_owner(
        self,
        organization_id: UUID,
        context: CurrentUserContext,
    ) -> None:
        self.permission_policy.require_organization(
            context,
            organization_id,
            PermissionKey.ORGANIZATION_DELETE,
            detail="You don't have permission for this organization",
        )
        context.require_org_role(
            organization_id,
            ORG_OWNER_ONLY_ROLES,
            detail="You don't have permission for this organization",
        )

    def update_organization(
        self,
        organization_id: UUID,
        organization_data: OrganizationUpdate,
        context: CurrentUserContext,
    ) -> OrganizationRead:
        self.permission_policy.require_organization(
            context,
            organization_id,
            PermissionKey.ORGANIZATION_UPDATE,
            detail="You don't have permission for this organization",
        )
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
        # Deleting an org cascades its agents/templates/skills and orphans running
        # pods, so it is owner/platform-admin only — admins can rename but not destroy.
        self._ensure_is_owner(organization_id, context)
        organization = self.organization_repository.get(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        # Deleting an org would cascade its agents and orphan their running pods.
        # Require an explicit teardown: the agents must be deleted first.
        active_agents = self.agent_service.count_active_agents(organization_id)
        if active_agents > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(f"Delete this organization's agents before deleting it ({active_agents} still active)."),
            )
        self.organization_repository.delete(organization.id)

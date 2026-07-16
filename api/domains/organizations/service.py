from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from uuid import UUID
import fnmatch

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlmodel import Session

from api.core.config import get_config
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
from api.domains.templates.service import TemplateService
from api.domains.users.organization_users.models import (
    ORG_MANAGER_ROLES,
    ORG_OWNER_ONLY_ROLES,
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
    template_service: TemplateService

    def get_organization(
        self, organization_id: UUID, context: CurrentUserContext
    ) -> OrganizationRead:
        # Any member (or a superuser) may view the org; non-members are refused before
        # the fetch so a 403-vs-404 difference can't confirm an org's existence.
        self._ensure_can_view_organization(organization_id, context)
        organization = self.organization_repository.get_read(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        return organization

    def _validate_allowed_models(self, allowed_models: list[str]) -> None:
        if not allowed_models:
            return
        try:
            catalog = self.agent_service.openrouter.list_models()
        except Exception:
            # If the OpenRouter catalog is unavailable (e.g. no API key locally),
            # skip validation so admins can still configure the allowlist.
            return
        if not catalog:
            return
        for pattern in allowed_models:
            # Strip any litellm gateway prefix so patterns match the bare OpenRouter slug.
            bare = pattern.strip().lower().removeprefix("litellm/openrouter/")
            catalog_ids_lower = [m["id"].lower() for m in catalog]
            if not any(fnmatch.fnmatch(cid, bare) for cid in catalog_ids_lower):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Model pattern '{pattern}' does not match any known models in the catalog.",
                )

    def create_organization(
        self, data: OrganizationCreate, actor: CurrentUserContext
    ) -> OrganizationCreateResult:
        actor.require_superuser(detail="Only a superuser can create organizations")

        config = get_config()
        allowed_models = data.allowed_models if data.allowed_models is not None else [config.agent_default_model]
        self._validate_allowed_models(allowed_models)

        # Org, owner-invite (user + token) and the OWNER membership all commit together,
        # so a failed step can't leave an org with no owner. The invite email is sent
        # only after commit.
        organization = Organization(
            name=data.name, description=data.description, is_default=False, allowed_models=allowed_models
        )
        with Session(
            self.organization_repository.delegate.engine, expire_on_commit=False
        ) as session:
            self.organization_repository.save_with_session(organization, session)
            prepared = self.auth_service.prepare_invite(
                session, email=str(data.owner_email), full_name=data.owner_name
            )
            self.user_organization_service.add_membership_with_session(
                OrganizationUser(
                    user_id=prepared.user.id,
                    organization_id=organization.id,
                    role=OrganizationRole.OWNER,
                ),
                session,
            )
            session.commit()

        # Templates are per-org (unlike global skills), so a new org needs its own copy
        # of the predefined catalog. Idempotent; runs post-commit like the invite email.
        self.template_service.seed_predefined_templates(organization.id)
        self.auth_service.send_prepared_invite(prepared)

        organization_read = self.organization_repository.get_read(organization.id)
        if not organization_read:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to load organization",
            )
        return OrganizationCreateResult(
            organization=organization_read, invite_link=prepared.invite_link
        )

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

    def _ensure_can_view_organization(
        self,
        organization_id: UUID,
        context: CurrentUserContext,
    ) -> None:
        # Any membership can view the org; authorized against the *target* org (path
        # param), never the header org. frozenset(OrganizationRole) so a future role is
        # included automatically rather than silently 403'd out.
        context.require_org_role(
            organization_id,
            frozenset(OrganizationRole),
            detail="You don't have permission for this organization",
        )

    def _ensure_can_manage_organization(
        self,
        organization_id: UUID,
        context: CurrentUserContext,
        required_roles: AbstractSet[OrganizationRole] = ORG_MANAGER_ROLES,
    ) -> None:
        # Authorized against the *target* org (path param), never the header org —
        # see CurrentUserContext.require_org_role.
        context.require_org_role(
            organization_id,
            required_roles,
            detail="You don't have permission for this organization",
        )

    def update_organization(
        self,
        organization_id: UUID,
        organization_data: OrganizationUpdate,
        context: CurrentUserContext,
    ) -> OrganizationRead:
        self._ensure_can_manage_organization(organization_id, context)

        dump = organization_data.model_dump(exclude_unset=True)

        # Fetch, mutate, and commit inside a single live session
        # so SQLAlchemy properly tracks list mutations and flushes the UPDATE.
        with Session(self.organization_repository.delegate.engine, expire_on_commit=False) as session:
            from sqlmodel import select
            organization = session.exec(select(Organization).where(Organization.id == organization_id)).first()
            if not organization:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Organization {organization_id} not found",
                )

            for key, value in dump.items():
                setattr(organization, key, value)
            
            from sqlalchemy.orm.attributes import flag_modified
            if "allowed_models" in dump:
                flag_modified(organization, "allowed_models")

            session.commit()

        organization_read = self.organization_repository.get_read(organization_id)
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
        # pods, so it is owner/superuser only — admins can rename but not destroy.
        self._ensure_can_manage_organization(
            organization_id, context, required_roles=ORG_OWNER_ONLY_ROLES
        )
        organization = self.organization_repository.get(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        if organization.is_default:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The default organization cannot be deleted",
            )
        # Deleting an org would cascade its agents and orphan their running pods.
        # Require an explicit teardown: the agents must be deleted first.
        active_agents = self.agent_service.count_active_agents(organization_id)
        if active_agents > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Delete this organization's agents before deleting it "
                    f"({active_agents} still active)."
                ),
            )
        self.organization_repository.delete(organization.id)

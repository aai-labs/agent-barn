import fnmatch
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlmodel import Session, select

from api.core.config import get_config
from api.domains.agents.service import AgentService
from api.domains.auth.models import CurrentUserContext
from api.domains.events import (
    EventDelivery,
    EventDeliveryDispatcher,
    SubjectIdentity,
    SubjectIdentityType,
    resolve_actor_identity,
)
from api.domains.events.catalog import EVENT_REGISTRY, ORGANIZATION_MODEL_ALLOWLIST_CHANGED
from api.domains.organizations.exceptions import OrganizationCreationLimitReached
from api.domains.organizations.models import (
    Organization,
    OrganizationCreate,
    OrganizationFilter,
    OrganizationRead,
    OrganizationUpdate,
    PlatformOrganizationRead,
)
from api.domains.organizations.repository import OrganizationRepository
from api.domains.rbac.catalog import ORG_OWNER_ONLY_ROLES, PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.shared.models import PaginatedItems, Pagination

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class OrganizationService:
    organization_repository: OrganizationRepository
    agent_service: AgentService
    permission_policy: PermissionPolicy
    event_delivery_dispatcher: EventDeliveryDispatcher

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

    def get_platform_organization(self, organization_id: UUID) -> PlatformOrganizationRead:
        # Platform Administrators have no Membership in arbitrary Organizations, so this
        # deliberately skips _ensure_can_view_organization and returns the dedicated
        # Platform Oversight read model instead of the member-facing OrganizationRead.
        organization = self.organization_repository.get_platform_read(organization_id)
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization {organization_id} not found",
            )
        return organization

    @staticmethod
    def _bare_model(pattern: str) -> str:
        # Strip any litellm gateway prefix so patterns match the bare OpenRouter slug.
        return pattern.strip().lower().removeprefix("litellm/openrouter/")

    def _validate_allowed_models(self, allowed_models: list[str], existing: list[str] | None = None) -> None:
        if not allowed_models:
            return
        try:
            catalog = self.agent_service.openrouter.list_models()
        except Exception as e:
            # If the OpenRouter catalog is unavailable (e.g. no API key locally, a
            # transient outage), skip validation so admins can still configure the
            # allowlist — but log it so a silently-skipped validation is debuggable.
            logger.warning("OpenRouter catalog unavailable, skipping model allowlist validation: %s", e)
            return
        if not catalog:
            return
        # Entries already stored on the org are exempt from catalog validation:
        # a model OpenRouter has since removed ("orphaned") must be preservable on
        # save. Only newly-added patterns are checked against the live catalog.
        existing_bare = {self._bare_model(m) for m in (existing or [])}
        catalog_ids_lower = [m["id"].lower() for m in catalog]
        for pattern in allowed_models:
            bare = self._bare_model(pattern)
            if bare in existing_bare:
                continue
            if not any(fnmatch.fnmatch(cid, bare) for cid in catalog_ids_lower):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Model pattern '{pattern}' does not match any known models in the catalog.",
                )

    def create_organization_for_current_user(
        self,
        data: OrganizationCreate,
        actor: CurrentUserContext,
    ) -> OrganizationRead:
        config = get_config()
        allowed_models = [config.agent_default_model.removeprefix("litellm/openrouter/")]

        organization = Organization(
            name=data.name,
            description=data.description,
            created_by_user_id=actor.user.id,
            allowed_models=allowed_models,
        )
        try:
            # Organization creation and the creator's Owner Membership are one
            # transaction, including the concurrency-safe quota check.
            self.organization_repository.create_for_user(
                organization,
                actor.user.id,
                config.organization_creation_limit,
            )
        except OrganizationCreationLimitReached as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"You can create up to {error.limit} organizations",
            ) from error

        organization_read = self.organization_repository.get_read(organization.id)
        if not organization_read:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to load organization",
            )
        return organization_read

    def get_paginated_organizations(
        self,
        context: CurrentUserContext,
        org_filter: OrganizationFilter = OrganizationFilter(),
        page: int = 1,
        page_size: int = 15,
    ) -> PaginatedItems[PlatformOrganizationRead]:
        pagination = Pagination(page=page, size=page_size)
        return self.organization_repository.find_all_paginated_platform_read(
            pagination=pagination,
            organization_filter=org_filter,
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

        dump = organization_data.model_dump(exclude_unset=True)
        delivery_ids: list[UUID] = []

        # Mutate and commit inside a single live session
        # so SQLAlchemy properly tracks list mutations and flushes the UPDATE.
        with Session(self.organization_repository.delegate.engine, expire_on_commit=False) as session:
            session.add(organization)

            from sqlalchemy.orm.attributes import flag_modified

            added_models: list[str] = []
            removed_models: list[str] = []
            allowlist_changed = False
            if "allowed_models" in dump:
                if dump["allowed_models"] is None:
                    # An explicit null is a no-op: allowed_models is non-nullable at
                    # the model level, so never overwrite the stored list with NULL.
                    del dump["allowed_models"]
                else:
                    self._validate_allowed_models(dump["allowed_models"], existing=organization.allowed_models)
                    dump["allowed_models"] = [m.removeprefix("litellm/openrouter/") for m in dump["allowed_models"]]
                    previous_set = set(organization.allowed_models)
                    new_set = set(dump["allowed_models"])
                    added_models = sorted(new_set - previous_set)
                    removed_models = sorted(previous_set - new_set)
                    allowlist_changed = bool(added_models or removed_models)
                    flag_modified(organization, "allowed_models")

            for key, value in dump.items():
                setattr(organization, key, value)
            session.flush()

            if allowlist_changed:
                actor = resolve_actor_identity(context, organization_id)
                event = EVENT_REGISTRY.build_event(
                    event_name=ORGANIZATION_MODEL_ALLOWLIST_CHANGED,
                    schema_version=1,
                    occurred_at=datetime.now(UTC),
                    organization_id=organization_id,
                    actor=actor,
                    subject=SubjectIdentity(
                        type=SubjectIdentityType.ORGANIZATION,
                        id=organization_id,
                        organization_id=organization_id,
                    ),
                    correlation_id=uuid4(),
                    payload={
                        "organization_id": organization_id,
                        "added": added_models,
                        "removed": removed_models,
                        "actor_display": context.user.full_name or context.user.email,
                        "subject_display": organization.name,
                    },
                )
                self.organization_repository.outbox_repository.stage(
                    session=session, registry=EVENT_REGISTRY, event=event
                )
                delivery_ids = list(
                    session.exec(select(EventDelivery.id).where(EventDelivery.event_id == event.event_id))
                )

            session.commit()

        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)

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

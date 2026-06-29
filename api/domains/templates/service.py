import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.auth.models import CurrentUserContext
from api.domains.templates.defaults import (
    DEFAULT_AGENTS_MD,
    DEFAULT_BOOT_MD,
    DEFAULT_BOOTSTRAP_MD,
    DEFAULT_HEARTBEAT_MD,
    DEFAULT_IDENTITY_MD,
    DEFAULT_SOUL_MD,
    DEFAULT_TOOLS_MD,
    DEFAULT_USER_MD,
)
from api.domains.templates.models import (
    AgentTemplate,
    TemplateCreate,
    TemplateFilter,
    TemplateRead,
    TemplateSource,
    TemplateUpdate,
)
from api.domains.templates.repository import TemplateRepository
from api.domains.templates.seeding import (
    build_predefined_templates,
    copy_predefined_content,
    predefined_content_differs,
)
from api.domains.templates.slug import slugify
from api.infrastructure.shared.models import PaginatedItems, Pagination

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class TemplateService:
    repository: TemplateRepository

    def _org_id(self, context: CurrentUserContext) -> UUID:
        return context.require_current_user_organization().organization_id

    def _get_latest_or_404(self, org_id: UUID, slug: str) -> AgentTemplate:
        template = self.repository.get_latest_template(org_id, slug)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template {slug} not found",
            )
        return template

    def list_templates(
        self,
        template_filter: TemplateFilter,
        pagination: Pagination,
        context: CurrentUserContext,
    ) -> PaginatedItems[TemplateRead]:
        org_id = self._org_id(context)
        templates, total = self.repository.find_latest_templates(
            org_id, template_filter, pagination
        )
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=[TemplateRead.model_validate(t) for t in templates],
        )

    def get_template(self, slug: str, context: CurrentUserContext) -> TemplateRead:
        org_id = self._org_id(context)
        return TemplateRead.model_validate(self._get_latest_or_404(org_id, slug))

    def list_template_versions(
        self, slug: str, context: CurrentUserContext
    ) -> list[TemplateRead]:
        org_id = self._org_id(context)
        versions = self.repository.find_versions(org_id, slug)
        if not versions:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template {slug} not found",
            )
        return [TemplateRead.model_validate(v) for v in versions]

    def create_template(
        self, data: TemplateCreate, context: CurrentUserContext
    ) -> TemplateRead:
        org_id = self._org_id(context)
        slug = slugify(data.template_name)
        if not slug:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="template_name must contain at least one alphanumeric character",
            )
        if self.repository.get_latest_template(org_id, slug) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A template with slug {slug} already exists",
            )
        template = AgentTemplate(
            organization_id=org_id,
            template_slug=slug,
            template_name=data.template_name,
            template_source=TemplateSource.CUSTOM,
            version=1,
            description=data.description,
            soul_md=data.soul_md or DEFAULT_SOUL_MD,
            identity_md=data.identity_md or DEFAULT_IDENTITY_MD,
            user_md=data.user_md or DEFAULT_USER_MD,
            tools_md=data.tools_md or DEFAULT_TOOLS_MD,
            agents_md=data.agents_md or DEFAULT_AGENTS_MD,
            boot_md=data.boot_md or DEFAULT_BOOT_MD,
            bootstrap_md=data.bootstrap_md or DEFAULT_BOOTSTRAP_MD,
            heartbeat_md=data.heartbeat_md or DEFAULT_HEARTBEAT_MD,
        )
        self.repository.save_template(template)
        return TemplateRead.model_validate(template)

    def update_template(
        self, slug: str, data: TemplateUpdate, context: CurrentUserContext
    ) -> TemplateRead:
        org_id = self._org_id(context)
        old = self._get_latest_or_404(org_id, slug)
        updated = data.model_dump(exclude_unset=True)
        # Every update publishes a new immutable version of the lineage; the
        # slug never changes and agent pins are left untouched.
        new_template = AgentTemplate(
            organization_id=org_id,
            template_slug=old.template_slug,
            template_name=updated.get("template_name", old.template_name),
            template_source=old.template_source,
            version=old.version + 1,
            description=updated.get("description", old.description),
            soul_md=updated.get("soul_md", old.soul_md),
            identity_md=updated.get("identity_md", old.identity_md),
            user_md=updated.get("user_md", old.user_md),
            tools_md=updated.get("tools_md", old.tools_md),
            agents_md=updated.get("agents_md", old.agents_md),
            boot_md=updated.get("boot_md", old.boot_md),
            bootstrap_md=updated.get("bootstrap_md", old.bootstrap_md),
            heartbeat_md=updated.get("heartbeat_md", old.heartbeat_md),
        )
        self.repository.save_template(new_template)
        return TemplateRead.model_validate(new_template)

    def seed_predefined_templates(self, org_id: UUID) -> None:
        """Insert missing pre-defined templates and refresh stale ones in place.

        Pre-defined templates are system-managed. When the code's content changes,
        the original v1 seed is overwritten in place so both new agents (created
        from the latest version) and existing agents (which re-render their pinned
        template on every start) pick up the change. A lineage the user has edited
        (version > 1) is left untouched so customizations are never clobbered.
        """
        for template in build_predefined_templates(org_id):
            existing = self.repository.get_latest_template(
                org_id, template.template_slug
            )
            if existing is None:
                self.repository.save_template(template)
                logger.warning(
                    "Seeded predefined template: %s v1", template.template_slug
                )
            elif (
                existing.version == 1
                and existing.template_source == TemplateSource.PRE_DEFINED
                and predefined_content_differs(existing, template)
            ):
                copy_predefined_content(existing, template)
                self.repository.save_template(existing)
                logger.warning(
                    "Refreshed predefined template in place: %s v1",
                    template.template_slug,
                )

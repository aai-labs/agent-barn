import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError

from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.domains.skills.models import SkillRead
from api.domains.skills.repository import SkillRepository
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
from api.domains.templates.predefined import PREDEFINED_TEMPLATES
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
    skill_repository: SkillRepository
    permission_policy: PermissionPolicy

    def _org_id(self, context: CurrentUserContext) -> UUID:
        return context.require_current_user_organization().organization_id

    def _validate_skill_ids(self, skill_ids: list[UUID], org_id: UUID) -> None:
        accessible = {s.id for s in self.skill_repository.find_accessible_for_org(org_id)}
        for skill_id in skill_ids:
            if skill_id not in accessible:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Skill {skill_id} not found",
                )

    def _with_required_skills(self, read: TemplateRead) -> TemplateRead:
        skills = self.repository.get_required_skills(read.id)
        return read.model_copy(update={"required_skills": [SkillRead.model_validate(s) for s in skills]})

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
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_READ)
        templates, total = self.repository.find_latest_templates(org_id, template_filter, pagination)
        template_ids = [t.id for t in templates]
        skills_by_template = self.repository.get_required_skills_for_templates(template_ids)
        used_slugs = self.repository.get_slugs_used_by_live_agents(org_id, [t.template_slug for t in templates])
        items = []
        for t in templates:
            read = TemplateRead.model_validate(t)
            skills = skills_by_template.get(t.id, [])
            read = read.model_copy(
                update={
                    "required_skills": [SkillRead.model_validate(s) for s in skills],
                    "in_use": t.template_slug in used_slugs,
                }
            )
            items.append(read)
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=items,
        )

    def get_template(self, slug: str, context: CurrentUserContext) -> TemplateRead:
        org_id = self._org_id(context)
        template = self._get_latest_or_404(org_id, slug)
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_READ)
        read = TemplateRead.model_validate(template)
        read = read.model_copy(update={"in_use": self.repository.is_lineage_used_by_live_agent(org_id, slug)})
        return self._with_required_skills(read)

    def list_template_versions(self, slug: str, context: CurrentUserContext) -> list[TemplateRead]:
        org_id = self._org_id(context)
        versions = self.repository.find_versions(org_id, slug)
        if not versions:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template {slug} not found",
            )
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_READ)
        template_ids = [v.id for v in versions]
        skills_by_template = self.repository.get_required_skills_for_templates(template_ids)
        result = []
        for v in versions:
            read = TemplateRead.model_validate(v)
            skills = skills_by_template.get(v.id, [])
            read = read.model_copy(update={"required_skills": [SkillRead.model_validate(s) for s in skills]})
            result.append(read)
        return result

    def create_template(self, data: TemplateCreate, context: CurrentUserContext) -> TemplateRead:
        org_id = self._org_id(context)
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_MANAGE)
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
        if data.required_skill_ids:
            self._validate_skill_ids(data.required_skill_ids, org_id)
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
        if data.required_skill_ids:
            self.repository.save_template_skills(template.id, data.required_skill_ids)
        return self._with_required_skills(TemplateRead.model_validate(template))

    def update_template(self, slug: str, data: TemplateUpdate, context: CurrentUserContext) -> TemplateRead:
        org_id = self._org_id(context)
        old = self._get_latest_or_404(org_id, slug)
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_MANAGE)
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
        if data.required_skill_ids is None:
            resolved_ids = list(self.repository.get_required_skill_ids(old.id))
        else:
            if data.required_skill_ids:
                self._validate_skill_ids(data.required_skill_ids, org_id)
            resolved_ids = data.required_skill_ids
        self.repository.save_template(new_template)
        self.repository.save_template_skills(new_template.id, resolved_ids)
        return self._with_required_skills(TemplateRead.model_validate(new_template))

    def delete_template(self, slug: str, context: CurrentUserContext) -> None:
        org_id = self._org_id(context)
        latest = self._get_latest_or_404(org_id, slug)
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_MANAGE)
        if latest.template_source == TemplateSource.PRE_DEFINED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete pre-defined templates",
            )
        if self.repository.is_lineage_used_by_live_agent(org_id, slug):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Template is being used by one or more agents",
            )
        try:
            self.repository.purge_template_lineage(org_id, slug)
        except IntegrityError:
            # An agent was created from this template between the check and
            # the delete; the RESTRICT FK rejected the purge.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Template is being used by one or more agents",
            )

    def seed_predefined_templates(self, org_id: UUID) -> None:
        """Insert missing pre-defined templates and refresh stale ones in place.

        Pre-defined templates are system-managed. When the code's content changes,
        the original v1 seed is overwritten in place so both new agents (created
        from the latest version) and existing agents (which re-render their pinned
        template on every start) pick up the change. A lineage the user has edited
        (version > 1) is left untouched so customizations are never clobbered.
        """
        for predefined, template in zip(PREDEFINED_TEMPLATES, build_predefined_templates(org_id)):
            existing = self.repository.get_latest_template(org_id, template.template_slug)
            if existing is None:
                self.repository.save_template(template)
                existing = template
                logger.warning("Seeded predefined template: %s v1", template.template_slug)
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

            if existing.version == 1 and existing.template_source == TemplateSource.PRE_DEFINED:
                desired_ids = [
                    skill.id
                    for name in predefined.required_skill_names
                    if (skill := self.skill_repository.get_by_name_global(name))
                ]
                existing_ids = self.repository.get_required_skill_ids(existing.id)
                if set(desired_ids) != existing_ids:
                    self.repository.save_template_skills(existing.id, desired_ids)

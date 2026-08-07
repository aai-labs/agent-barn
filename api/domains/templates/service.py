import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError

from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
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
    PlatformTemplate,
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
    event_delivery_dispatcher: EventDeliveryDispatcher

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

    def _to_read_with_skills(self, template: AgentTemplate | PlatformTemplate) -> TemplateRead:
        skills = self.repository.get_required_skills_for(template)
        return self.repository.to_read(template, skills)

    def _get_latest_or_404(self, org_id: UUID, slug: str) -> AgentTemplate | PlatformTemplate:
        template = self.repository.resolve_latest_template(org_id, slug)
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
        items, total = self.repository.find_latest_templates(org_id, template_filter, pagination)
        used_slugs = self.repository.get_slugs_used_by_live_agents(org_id, [item.template_slug for item in items])
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=[item.model_copy(update={"in_use": item.template_slug in used_slugs}) for item in items],
        )

    def get_template(self, slug: str, context: CurrentUserContext) -> TemplateRead:
        org_id = self._org_id(context)
        template = self._get_latest_or_404(org_id, slug)
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_READ)
        read = self._to_read_with_skills(template)
        in_use = slug in self.repository.get_slugs_used_by_live_agents(org_id, [slug])
        return read.model_copy(update={"in_use": in_use})

    def list_template_versions(self, slug: str, context: CurrentUserContext) -> list[TemplateRead]:
        org_id = self._org_id(context)
        versions = self.repository.resolve_versions(org_id, slug)
        if not versions:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template {slug} not found",
            )
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_READ)
        in_use = slug in self.repository.get_slugs_used_by_live_agents(org_id, [slug])
        return [self._to_read_with_skills(v).model_copy(update={"in_use": in_use}) for v in versions]

    def create_template(self, data: TemplateCreate, context: CurrentUserContext) -> TemplateRead:
        org_id = self._org_id(context)
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_MANAGE)
        slug = slugify(data.template_name)
        if not slug:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="template_name must contain at least one alphanumeric character",
            )
        if self.repository.resolve_latest_template(org_id, slug) is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A template with slug {slug} already exists",
            )
        group_skill_ids = [sid for group in data.required_skill_groups for sid in group.skill_ids]
        if data.required_skill_ids or group_skill_ids:
            self._validate_skill_ids(data.required_skill_ids + group_skill_ids, org_id)
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
        skills_map: dict[UUID, str | None] = {sid: None for sid in data.required_skill_ids}
        for group in data.required_skill_groups:
            skills_map.update(dict.fromkeys(group.skill_ids, group.group_key))
        result = self.repository.save_template_with_created_event(
            template,
            skills_map,
            actor=resolve_actor_identity(context, org_id),
            actor_display=context.user.full_name or context.user.email,
        )
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return self._to_read_with_skills(result.template)

    def update_template(self, slug: str, data: TemplateUpdate, context: CurrentUserContext) -> TemplateRead:
        org_id = self._org_id(context)
        old = self._get_latest_or_404(org_id, slug)
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_MANAGE)
        updated = data.model_dump(exclude_unset=True)
        # Every update publishes a new immutable org-scoped version of the
        # lineage; the slug never changes and agent pins are left untouched.
        # Editing a platform predefined template forks it into the org's
        # agent_template table (version = platform v + 1, forked_from set).
        forked_from = old.id if isinstance(old, PlatformTemplate) else old.forked_from_platform_template_id
        source = TemplateSource.PRE_DEFINED if isinstance(old, PlatformTemplate) else old.template_source
        new_template = AgentTemplate(
            organization_id=org_id,
            forked_from_platform_template_id=forked_from,
            template_slug=old.template_slug,
            template_name=updated.get("template_name", old.template_name),
            template_source=source,
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
        old_map = self.repository.get_required_skill_map_for(old)
        if data.required_skill_ids is None:
            standalone_ids = {sid for sid, group_key in old_map.items() if group_key is None}
        else:
            if data.required_skill_ids:
                self._validate_skill_ids(data.required_skill_ids, org_id)
            standalone_ids = set(data.required_skill_ids)
        if data.required_skill_groups is None:
            groups_map = {sid: group_key for sid, group_key in old_map.items() if group_key is not None}
        else:
            group_skill_ids = [sid for group in data.required_skill_groups for sid in group.skill_ids]
            if group_skill_ids:
                self._validate_skill_ids(group_skill_ids, org_id)
            groups_map = {sid: group.group_key for group in data.required_skill_groups for sid in group.skill_ids}
        overlap = standalone_ids & groups_map.keys()
        if overlap:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Skills cannot be both standalone required and part of a group: {sorted(str(s) for s in overlap)}"
                ),
            )
        field_changes: dict[str, dict[str, Any]] = {}
        for field in ("template_name", "description"):
            previous_value = getattr(old, field)
            new_value = getattr(new_template, field)
            if previous_value != new_value:
                field_changes[field] = {"previous": previous_value, "new": new_value}
        result = self.repository.save_template_with_updated_event(
            new_template,
            {sid: None for sid in standalone_ids} | groups_map,
            previous_version=old.version,
            field_changes=field_changes,
            actor=resolve_actor_identity(context, org_id),
            actor_display=context.user.full_name or context.user.email,
        )
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return self._to_read_with_skills(result.template)

    def delete_template(self, slug: str, context: CurrentUserContext) -> None:
        org_id = self._org_id(context)
        latest = self._get_latest_or_404(org_id, slug)
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_MANAGE)
        if not isinstance(latest, AgentTemplate):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete platform templates",
            )
        if latest.template_source == TemplateSource.PRE_DEFINED:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete pre-defined templates",
            )
        if self.repository.is_org_lineage_used_by_live_agent(org_id, slug):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Template is being used by one or more agents",
            )
        try:
            delivery_ids = self.repository.purge_org_template_lineage_with_event(
                org_id,
                slug,
                actor=resolve_actor_identity(context, org_id),
                actor_display=context.user.full_name or context.user.email,
            )
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Template is being used by one or more agents",
            ) from None
        self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)

    def seed_predefined_templates(self) -> None:
        """Insert missing global pre-defined templates and refresh stale ones in place.

        Pre-defined templates are system-managed platform/global resources
        living in the platform_template table (no organization_id), seeded
        once for the whole platform. When the code's content changes, the
        platform v1 seed is overwritten in place so both new agents (created
        from the latest version) and existing agents (which re-render their
        pinned template on every start) pick up the change. Org forks
        (org-scoped agent_template rows with version > 1) are left untouched so
        customizations are never clobbered; the seeder only ever touches the
        platform v1 row.
        """
        for predefined, template in zip(PREDEFINED_TEMPLATES, build_predefined_templates()):
            existing = self.repository.get_latest_platform_template(template.template_slug)
            if existing is None:
                self.repository.save_platform_template(template)
                existing = template
                logger.warning("Seeded platform predefined template: %s v1", template.template_slug)
            elif predefined_content_differs(existing, template):
                copy_predefined_content(existing, template)
                self.repository.save_platform_template(existing)
                logger.warning(
                    "Refreshed platform predefined template in place: %s v1",
                    template.template_slug,
                )

            desired_map: dict[UUID, str | None] = {}
            for entry in predefined.required_skill_names:
                names = (entry,) if isinstance(entry, str) else entry
                # A tuple entry is an "at least one of" group; its key is
                # derived from the member names so it's stable across
                # re-seeds. A single name is a standalone AND requirement.
                group_key = None if isinstance(entry, str) else "-or-".join(slugify(n) for n in names)
                for name in names:
                    if skill := self.skill_repository.get_by_name_global(name):
                        desired_map[skill.id] = group_key
            if desired_map != self.repository.get_platform_required_skill_map(existing.id):
                self.repository.save_platform_template_skills(existing.id, desired_map)

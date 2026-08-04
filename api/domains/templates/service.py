import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError

from api.domains.auth.models import CurrentUserContext
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
    PlatformTemplateAdminSummary,
    PlatformTemplateDraft,
    PlatformTemplateDraftCreate,
    PlatformTemplateDraftRead,
    PlatformTemplateDraftUpdate,
    TemplateCreate,
    TemplateFilter,
    TemplateRead,
    TemplateSkillGroup,
    TemplateSource,
    TemplateUpdate,
)
from api.domains.templates.predefined import PREDEFINED_TEMPLATES
from api.domains.templates.repository import TemplateRepository
from api.domains.templates.seeding import build_predefined_templates
from api.domains.templates.slug import slugify
from api.infrastructure.shared.models import PaginatedItems, Pagination

logger = logging.getLogger(__name__)

_TEMPLATE_CONTENT_FIELDS = (
    "description",
    "soul_md",
    "identity_md",
    "user_md",
    "tools_md",
    "agents_md",
    "boot_md",
    "bootstrap_md",
    "heartbeat_md",
)


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
        self.repository.save_template(template)
        skills_map: dict[UUID, str | None] = {sid: None for sid in data.required_skill_ids}
        for group in data.required_skill_groups:
            skills_map.update(dict.fromkeys(group.skill_ids, group.group_key))
        if skills_map:
            self.repository.save_org_template_skills(template.id, skills_map)
        return self._to_read_with_skills(template)

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
        fork_baseline = (
            old.id
            if isinstance(old, PlatformTemplate)
            else (old.fork_baseline_platform_template_id or old.forked_from_platform_template_id)
        )
        source = TemplateSource.PRE_DEFINED if isinstance(old, PlatformTemplate) else old.template_source
        new_template = AgentTemplate(
            organization_id=org_id,
            forked_from_platform_template_id=forked_from,
            fork_baseline_platform_template_id=fork_baseline,
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
        self.repository.save_template(new_template)
        self.repository.save_org_template_skills(new_template.id, {sid: None for sid in standalone_ids} | groups_map)
        return self._to_read_with_skills(new_template)

    def update_from_platform(self, slug: str, context: CurrentUserContext) -> TemplateRead:
        """Rebase an organization fork onto its origin's newest platform version.

        A field is considered an organization override when it differs from the
        fork's baseline. Those overrides win; every other field comes from the
        newly published platform version. Required skills use the same
        three-way rule as one aggregate field so an org's skill customization
        is preserved without silently combining incompatible requirements.
        """
        org_id = self._org_id(context)
        current = self.repository.get_latest_org_template(org_id, slug)
        if current is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {slug} not found")
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_MANAGE)

        if current.forked_from_platform_template_id is None or current.template_source != TemplateSource.PRE_DEFINED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Template Update is only available for organization forks of Platform Templates",
            )

        baseline_id = current.fork_baseline_platform_template_id or current.forked_from_platform_template_id
        baseline = self.repository.get_platform_template_by_id(baseline_id) if baseline_id is not None else None
        latest_platform = self.repository.get_latest_platform_template(slug)
        if baseline is None or baseline.template_slug != slug or latest_platform is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The fork's Platform Template baseline is no longer available",
            )
        if latest_platform.version <= baseline.version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No newer Platform Template Version is available",
            )

        merged_values = {
            field: getattr(current, field)
            if getattr(current, field) != getattr(baseline, field)
            else getattr(latest_platform, field)
            for field in _TEMPLATE_CONTENT_FIELDS
        }
        current_skill_map = self.repository.get_org_required_skill_map(current.id)
        baseline_skill_map = self.repository.get_platform_required_skill_map(baseline.id)
        latest_skill_map = self.repository.get_platform_required_skill_map(latest_platform.id)
        merged_skill_map = current_skill_map if current_skill_map != baseline_skill_map else latest_skill_map

        updated = AgentTemplate(
            organization_id=org_id,
            forked_from_platform_template_id=current.forked_from_platform_template_id,
            fork_baseline_platform_template_id=latest_platform.id,
            template_slug=current.template_slug,
            template_name=current.template_name,
            template_source=current.template_source,
            version=current.version + 1,
            description=merged_values["description"],
            soul_md=merged_values["soul_md"],
            identity_md=merged_values["identity_md"],
            user_md=merged_values["user_md"],
            tools_md=merged_values["tools_md"],
            agents_md=merged_values["agents_md"],
            boot_md=merged_values["boot_md"],
            bootstrap_md=merged_values["bootstrap_md"],
            heartbeat_md=merged_values["heartbeat_md"],
        )
        self.repository.save_org_template_version_with_skills(updated, merged_skill_map)
        return self._to_read_with_skills(updated)

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
            self.repository.purge_org_template_lineage(org_id, slug)
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Template is being used by one or more agents",
            ) from None

    def seed_predefined_templates(self) -> None:
        """One-time bootstrap: insert a lineage's v1 row from the seed files if it doesn't exist yet.

        Pre-defined templates are system-managed platform/global resources
        living in the platform_template table (no organization_id). This
        bootstrap only ever inserts a lineage's v1 row the first time it is
        seen (new environment or brand-new lineage); it never overwrites an
        existing row. Once a lineage exists, its content is owned by the
        Draft Template Version admin authoring flow, not these seed files —
        see docs/adr/2026-08-03-platform-template-file-based-bootstrap.md.
        Org forks (org-scoped agent_template rows) are untouched either way.
        """
        for predefined, template in zip(PREDEFINED_TEMPLATES, build_predefined_templates()):
            existing = self.repository.get_latest_platform_template(template.template_slug)
            if existing is not None:
                # Lineage already exists — ownership has passed to the admin
                # authoring flow, so the bootstrap leaves it untouched.
                continue

            self.repository.save_platform_template(template)
            existing = template
            logger.warning("Seeded platform predefined template: %s v1", template.template_slug)

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
            if desired_map:
                self.repository.save_platform_template_skills(existing.id, desired_map)

    # --- Draft Template Version (Platform Administrator authoring) ---
    #
    # Callers are gated on Platform Administrator authority at the route layer
    # (require_platform_admin); these methods assume that check already passed.

    def _validate_global_skill_ids(self, skill_ids: list[UUID]) -> None:
        for skill_id in skill_ids:
            skill = self.skill_repository.get_by_id(skill_id)
            if skill is None or skill.organization_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Skill {skill_id} not found",
                )

    def _skills_map(
        self, required_skill_ids: list[UUID], required_skill_groups: list[TemplateSkillGroup]
    ) -> dict[UUID, str | None]:
        skills_map: dict[UUID, str | None] = {sid: None for sid in required_skill_ids}
        for group in required_skill_groups:
            skills_map.update(dict.fromkeys(group.skill_ids, group.group_key))
        return skills_map

    def list_platform_lineages_for_admin(self) -> list[PlatformTemplateAdminSummary]:
        return self.repository.list_platform_lineages_for_admin()

    def get_published_platform_template_for_admin(self, slug: str) -> TemplateRead:
        template = self.repository.get_latest_platform_template(slug)
        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {slug} not found")
        return self._to_read_with_skills(template)

    def list_published_platform_template_versions_for_admin(self, slug: str) -> list[TemplateRead]:
        versions = self.repository.find_platform_versions(slug)
        if not versions:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {slug} not found")
        return [self._to_read_with_skills(version) for version in versions]

    def get_draft(self, slug: str) -> PlatformTemplateDraftRead:
        draft = self.repository.get_draft(slug)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for {slug}")
        skills = self.repository.get_draft_required_skills(draft.id)
        return self.repository.to_draft_read(draft, skills)

    def start_draft_for_existing_lineage(
        self, slug: str, source_version: int | None = None
    ) -> PlatformTemplateDraftRead:
        """Get-or-create the single in-flight draft for an already-published lineage,
        seeded from a selected published version or, by default, the latest version."""
        existing_draft = self.repository.get_draft(slug)
        if existing_draft is not None:
            if source_version is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A draft already exists; discard it before restoring another published version",
                )
            skills = self.repository.get_draft_required_skills(existing_draft.id)
            return self.repository.to_draft_read(existing_draft, skills)

        source = (
            self.repository.get_platform_template_by_slug_version(slug, source_version)
            if source_version is not None
            else self.repository.get_latest_platform_template(slug)
        )
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {slug} not found")

        draft = PlatformTemplateDraft(
            template_slug=source.template_slug,
            template_name=source.template_name,
            description=source.description,
            soul_md=source.soul_md,
            identity_md=source.identity_md,
            user_md=source.user_md,
            tools_md=source.tools_md,
            agents_md=source.agents_md,
            boot_md=source.boot_md,
            bootstrap_md=source.bootstrap_md,
            heartbeat_md=source.heartbeat_md,
        )
        self.repository.save_draft(draft)
        skill_map = self.repository.get_platform_required_skill_map(source.id)
        if skill_map:
            self.repository.save_draft_skills(draft.id, skill_map)
        return self.get_draft(slug)

    def create_new_template_draft(self, data: PlatformTemplateDraftCreate) -> PlatformTemplateDraftRead:
        """Starts a draft for a lineage that has never been published."""
        slug = slugify(data.template_name)
        if not slug:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="template_name must contain at least one alphanumeric character",
            )
        if (
            self.repository.get_latest_platform_template(slug) is not None
            or self.repository.get_draft(slug) is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"A platform template with slug {slug} already exists",
            )
        group_skill_ids = [sid for group in data.required_skill_groups for sid in group.skill_ids]
        if data.required_skill_ids or group_skill_ids:
            self._validate_global_skill_ids(data.required_skill_ids + group_skill_ids)
        draft = PlatformTemplateDraft(
            template_slug=slug,
            template_name=data.template_name,
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
        self.repository.save_draft(draft)
        skills_map = self._skills_map(data.required_skill_ids, data.required_skill_groups)
        if skills_map:
            self.repository.save_draft_skills(draft.id, skills_map)
        return self.get_draft(slug)

    def update_draft(self, slug: str, data: PlatformTemplateDraftUpdate) -> PlatformTemplateDraftRead:
        draft = self.repository.get_draft(slug)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for {slug}")
        updated = data.model_dump(exclude_unset=True)
        for field in (
            "description",
            "soul_md",
            "identity_md",
            "user_md",
            "tools_md",
            "agents_md",
            "boot_md",
            "bootstrap_md",
            "heartbeat_md",
        ):
            if field in updated:
                setattr(draft, field, updated[field])
        self.repository.save_draft(draft)

        old_map = self.repository.get_draft_required_skill_map(draft.id)
        if data.required_skill_ids is None:
            standalone_ids = {sid for sid, group_key in old_map.items() if group_key is None}
        else:
            if data.required_skill_ids:
                self._validate_global_skill_ids(data.required_skill_ids)
            standalone_ids = set(data.required_skill_ids)
        if data.required_skill_groups is None:
            groups_map = {sid: group_key for sid, group_key in old_map.items() if group_key is not None}
        else:
            group_skill_ids = [sid for group in data.required_skill_groups for sid in group.skill_ids]
            if group_skill_ids:
                self._validate_global_skill_ids(group_skill_ids)
            groups_map = {sid: group.group_key for group in data.required_skill_groups for sid in group.skill_ids}
        self.repository.save_draft_skills(draft.id, {sid: None for sid in standalone_ids} | groups_map)
        return self.get_draft(slug)

    def discard_draft(self, slug: str) -> None:
        draft = self.repository.get_draft(slug)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for {slug}")
        self.repository.delete_draft(draft.id)

    def publish_draft(self, slug: str) -> TemplateRead:
        """Converts a lineage's Draft Template Version into the next immutable
        platform_template row, carries over its required-skill selection, then
        clears the draft slot so a new draft can start."""
        draft = self.repository.get_draft(slug)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for {slug}")
        latest = self.repository.get_latest_platform_template(slug)
        published = PlatformTemplate(
            template_slug=draft.template_slug,
            template_name=draft.template_name,
            version=(latest.version + 1) if latest is not None else 1,
            description=draft.description,
            soul_md=draft.soul_md,
            identity_md=draft.identity_md,
            user_md=draft.user_md,
            tools_md=draft.tools_md,
            agents_md=draft.agents_md,
            boot_md=draft.boot_md,
            bootstrap_md=draft.bootstrap_md,
            heartbeat_md=draft.heartbeat_md,
        )
        self.repository.save_platform_template(published)
        skill_map = self.repository.get_draft_required_skill_map(draft.id)
        if skill_map:
            self.repository.save_platform_template_skills(published.id, skill_map)
        self.repository.delete_draft(draft.id)
        skills = self.repository.get_platform_required_skills(published.id)
        return self.repository.to_read(published, skills)

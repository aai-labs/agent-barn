import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypeVar
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
from api.domains.templates.repository import TemplateKeyCollisionError, TemplateRepository
from api.domains.templates.seeding import build_predefined_templates
from api.domains.templates.slug import generate_template_key, slugify
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
_MAX_KEY_GENERATION_ATTEMPTS = 5
_KEY_COLLISION_ERRORS = (TemplateKeyCollisionError, IntegrityError)

_T = TypeVar("_T")
_R = TypeVar("_R")


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

    def _resolve_skill_map(
        self,
        standalone_ids: list[UUID],
        groups: list[TemplateSkillGroup],
        org_id: UUID | None,
        *,
        global_only: bool = False,
        requested_versions: dict[UUID, int] | None = None,
    ) -> dict[UUID, tuple[int, str | None]]:
        group_ids = [skill_id for group in groups for skill_id in group.skill_ids]
        all_ids = standalone_ids + group_ids
        requested_versions = requested_versions or {}
        unknown_version_ids = set(requested_versions) - set(all_ids)
        if unknown_version_ids:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Required Skill versions must reference a selected required Skill",
            )
        if global_only:
            self._validate_global_skill_ids(all_ids)
        elif all_ids and org_id is not None:
            self._validate_skill_ids(all_ids, org_id)
        versions = self.skill_repository.get_latest_version_numbers(all_ids)
        unpublished_ids = set(all_ids) - versions.keys()
        if unpublished_ids:
            skill_id = min(unpublished_ids, key=str)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Skill {skill_id} must have a published version before it can be required",
            )
        for skill_id, version in requested_versions.items():
            if self.skill_repository.get_version(skill_id, version) is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Skill Version {skill_id} v{version} not found",
                )
        resolved = {
            skill_id: (requested_versions.get(skill_id, versions[skill_id]), None) for skill_id in standalone_ids
        }
        for group in groups:
            for skill_id in group.skill_ids:
                resolved[skill_id] = (requested_versions.get(skill_id, versions[skill_id]), group.group_key)
        return resolved

    def _resolve_updated_skill_map(
        self,
        old_map: dict[UUID, tuple[int, str | None]],
        standalone_ids: list[UUID] | None,
        groups: list[TemplateSkillGroup] | None,
        org_id: UUID | None,
        *,
        global_only: bool = False,
        requested_versions: dict[UUID, int] | None = None,
    ) -> dict[UUID, tuple[int, str | None]]:
        """Resolve one complete requirement set while preserving omitted pins.

        Updating only one side of the standalone/group pair must not resolve the
        other side independently: doing so rejects version entries for the other
        side and can accidentally repin unchanged requirements to the latest
        version. Explicit version requests win; retained requirements keep their
        existing immutable pin.
        """
        if standalone_ids is None and groups is None and requested_versions is None:
            return dict(old_map)

        effective_standalone_ids = (
            standalone_ids
            if standalone_ids is not None
            else [skill_id for skill_id, (_, group_key) in old_map.items() if group_key is None]
        )
        if groups is not None:
            effective_groups = groups
        else:
            grouped: dict[str, list[UUID]] = {}
            for skill_id, (_, group_key) in old_map.items():
                if group_key is not None:
                    grouped.setdefault(group_key, []).append(skill_id)
            effective_groups = [
                TemplateSkillGroup(group_key=group_key, skill_ids=skill_ids) for group_key, skill_ids in grouped.items()
            ]

        group_ids = {skill_id for group in effective_groups for skill_id in group.skill_ids}
        overlap = set(effective_standalone_ids) & group_ids
        if overlap:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Skills cannot be both standalone required and part of a group: "
                    f"{sorted(str(skill_id) for skill_id in overlap)}"
                ),
            )

        effective_ids = set(effective_standalone_ids) | {
            skill_id for group in effective_groups for skill_id in group.skill_ids
        }
        requested = dict(requested_versions or {})
        for skill_id in effective_ids:
            if skill_id in old_map and skill_id not in requested:
                requested[skill_id] = old_map[skill_id][0]
        return self._resolve_skill_map(
            effective_standalone_ids,
            effective_groups,
            org_id,
            global_only=global_only,
            requested_versions=requested,
        )

    def _mark_platform_updates(self, reads: list[TemplateRead]) -> list[TemplateRead]:
        flags = self.repository.get_platform_update_flags(reads)
        return [read.model_copy(update={"platform_update_available": flags.get(read.id, False)}) for read in reads]

    def _to_read_with_skills(self, template: AgentTemplate | PlatformTemplate) -> TemplateRead:
        skills = self.repository.get_required_skills_for(template)
        read = self.repository.to_read(template, skills)
        return self._mark_platform_updates([read])[0]

    def _allocate_unique_key(self, build: Callable[[str], _T], save: Callable[[_T], _R]) -> _R:
        for _ in range(_MAX_KEY_GENERATION_ATTEMPTS):
            entity = build(generate_template_key())
            try:
                return save(entity)
            except _KEY_COLLISION_ERRORS:
                # A concurrent request may have won the same random key.
                continue

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not allocate a unique template key; please try again",
        )

    def _get_latest_or_404(self, org_id: UUID, template_key: str) -> AgentTemplate | PlatformTemplate:
        template = self.repository.resolve_latest_template(org_id, template_key)
        if not template:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template {template_key} not found",
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
        used_keys = self.repository.get_keys_used_by_live_agents(org_id, [item.template_key for item in items])
        reads = [item.model_copy(update={"in_use": item.template_key in used_keys}) for item in items]
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=self._mark_platform_updates(reads),
        )

    def get_template(self, template_key: str, context: CurrentUserContext) -> TemplateRead:
        org_id = self._org_id(context)
        template = self._get_latest_or_404(org_id, template_key)
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_READ)
        read = self._to_read_with_skills(template)
        in_use = template_key in self.repository.get_keys_used_by_live_agents(org_id, [template_key])
        return read.model_copy(update={"in_use": in_use})

    def list_template_versions(self, template_key: str, context: CurrentUserContext) -> list[TemplateRead]:
        org_id = self._org_id(context)
        versions = self.repository.resolve_versions(org_id, template_key)
        if not versions:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Template {template_key} not found",
            )
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_READ)
        in_use = template_key in self.repository.get_keys_used_by_live_agents(org_id, [template_key])
        reads = [self._to_read_with_skills(v).model_copy(update={"in_use": in_use}) for v in versions]
        return self._mark_platform_updates(reads)

    def create_template(self, data: TemplateCreate, context: CurrentUserContext) -> TemplateRead:
        org_id = self._org_id(context)
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_MANAGE)
        skills_map = self._resolve_skill_map(
            data.required_skill_ids,
            data.required_skill_groups,
            org_id,
            requested_versions=data.required_skill_versions,
        )

        def build(template_key: str) -> AgentTemplate:
            return AgentTemplate(
                organization_id=org_id,
                template_key=template_key,
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

        result = self._allocate_unique_key(
            build,
            lambda t: self.repository.save_new_org_template_with_skills_and_event(
                t,
                skills_map,
                actor=resolve_actor_identity(context, org_id),
                actor_display=context.user.full_name or context.user.email,
            ),
        )
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return self._to_read_with_skills(result.template)

    def update_template(self, template_key: str, data: TemplateUpdate, context: CurrentUserContext) -> TemplateRead:
        org_id = self._org_id(context)
        old = self._get_latest_or_404(org_id, template_key)
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_MANAGE)
        updated = data.model_dump(exclude_unset=True)
        # Every update publishes a new immutable organization version of the
        # lineage; the template_key never changes and agent pins are left
        # untouched. Organization-owned version numbers start at 1, separately
        # from the platform version sequence.
        forked_from = old.id if isinstance(old, PlatformTemplate) else old.forked_from_platform_template_id
        fork_baseline = (
            old.id
            if isinstance(old, PlatformTemplate)
            else (old.fork_baseline_platform_template_id or old.forked_from_platform_template_id)
        )
        fork_baseline_version = old.version if isinstance(old, PlatformTemplate) else old.fork_baseline_platform_version
        source = TemplateSource.PRE_DEFINED if isinstance(old, PlatformTemplate) else old.template_source
        new_template = AgentTemplate(
            organization_id=org_id,
            forked_from_platform_template_id=forked_from,
            fork_baseline_platform_template_id=fork_baseline,
            fork_baseline_platform_version=fork_baseline_version,
            template_key=old.template_key,
            template_name=updated.get("template_name", old.template_name),
            template_source=source,
            version=self.repository.get_next_org_template_version(org_id, old.template_key),
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
        resolved_map = self._resolve_updated_skill_map(
            old_map,
            data.required_skill_ids,
            data.required_skill_groups,
            org_id,
            requested_versions=data.required_skill_versions,
        )
        standalone_map = {sid: value for sid, value in resolved_map.items() if value[1] is None}
        groups_map = {sid: value for sid, value in resolved_map.items() if value[1] is not None}
        overlap = set(standalone_map) & groups_map.keys()
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
            standalone_map | groups_map,
            previous_version=old.version,
            field_changes=field_changes,
            actor=resolve_actor_identity(context, org_id),
            actor_display=context.user.full_name or context.user.email,
        )
        self.event_delivery_dispatcher.enqueue_immediate(result.delivery_ids)
        return self._to_read_with_skills(result.template)

    def update_from_platform(self, template_key: str, context: CurrentUserContext) -> TemplateRead:
        """Clone the newest platform snapshot into the next org version.

        Platform updates intentionally replace the organization's current
        content and required skills. Existing agent pins remain on their
        previous immutable organization version.
        """
        org_id = self._org_id(context)
        current = self.repository.get_latest_org_template(org_id, template_key)
        if current is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {template_key} not found")
        self.permission_policy.require_organization(context, org_id, PermissionKey.TEMPLATE_MANAGE)

        if current.forked_from_platform_template_id is None or current.template_source != TemplateSource.PRE_DEFINED:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Template Update is only available for organization forks of Platform Templates",
            )

        baseline_version = current.fork_baseline_platform_version
        latest_platform = self.repository.get_latest_platform_template(template_key)
        if baseline_version is None or latest_platform is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The fork's Platform Template baseline is no longer available",
            )
        if latest_platform.version <= baseline_version:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No newer Platform Template Version is available",
            )

        updated = AgentTemplate(
            organization_id=org_id,
            forked_from_platform_template_id=current.forked_from_platform_template_id,
            fork_baseline_platform_template_id=latest_platform.id,
            fork_baseline_platform_version=latest_platform.version,
            template_key=latest_platform.template_key,
            template_name=latest_platform.template_name,
            template_source=TemplateSource.PRE_DEFINED,
            version=self.repository.get_next_org_template_version(org_id, current.template_key),
            **{field: getattr(latest_platform, field) for field in _TEMPLATE_CONTENT_FIELDS},
        )
        latest_skill_map = self.repository.get_platform_required_skill_map(latest_platform.id)
        self.repository.save_org_template_version_with_skills(updated, latest_skill_map)
        return self._to_read_with_skills(updated)

    def delete_template(self, template_key: str, context: CurrentUserContext) -> None:
        org_id = self._org_id(context)
        latest = self._get_latest_or_404(org_id, template_key)
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
        if self.repository.is_org_lineage_used_by_live_agent(org_id, template_key):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Template is being used by one or more agents",
            )
        try:
            delivery_ids = self.repository.purge_org_template_lineage_with_event(
                org_id,
                template_key,
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
            existing = self.repository.get_latest_platform_template(template.template_key)
            if existing is not None:
                # Lineage already exists — ownership has passed to the admin
                # authoring flow, so the bootstrap leaves it untouched.
                continue

            self.repository.save_platform_template(template)
            existing = template
            logger.warning("Seeded platform predefined template: %s v1", template.template_key)

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
            if skill is None or skill.organization_id is not None or skill.agent_id is not None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Skill {skill_id} not found",
                )

    def _skills_map(
        self,
        required_skill_ids: list[UUID],
        required_skill_groups: list[TemplateSkillGroup],
        required_skill_versions: dict[UUID, int] | None = None,
    ) -> dict[UUID, tuple[int, str | None]]:
        return self._resolve_skill_map(
            required_skill_ids,
            required_skill_groups,
            None,
            global_only=True,
            requested_versions=required_skill_versions,
        )

    def list_platform_lineages_for_admin(self) -> list[PlatformTemplateAdminSummary]:
        return self.repository.list_platform_lineages_for_admin()

    def get_published_platform_template_for_admin(self, template_key: str) -> TemplateRead:
        template = self.repository.get_latest_platform_template(template_key)
        if template is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {template_key} not found")
        return self._to_read_with_skills(template)

    def list_published_platform_template_versions_for_admin(self, template_key: str) -> list[TemplateRead]:
        versions = self.repository.find_platform_versions(template_key)
        if not versions:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {template_key} not found")
        return [self._to_read_with_skills(version) for version in versions]

    def get_draft(self, template_key: str) -> PlatformTemplateDraftRead:
        draft = self.repository.get_draft(template_key)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for {template_key}")
        skills = self.repository.get_draft_required_skills(draft.id)
        return self.repository.to_draft_read(draft, skills)

    def start_draft_for_existing_lineage(
        self, template_key: str, source_version: int | None = None
    ) -> PlatformTemplateDraftRead:
        """Get-or-create the single in-flight draft for an already-published lineage,
        seeded from a selected published version or, by default, the latest version."""
        existing_draft = self.repository.get_draft(template_key)
        if existing_draft is not None:
            if source_version is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A draft already exists; discard it before restoring another published version",
                )
            skills = self.repository.get_draft_required_skills(existing_draft.id)
            return self.repository.to_draft_read(existing_draft, skills)

        source = (
            self.repository.get_platform_template_by_key_version(template_key, source_version)
            if source_version is not None
            else self.repository.get_latest_platform_template(template_key)
        )
        if source is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Template {template_key} not found")

        draft = PlatformTemplateDraft(
            template_key=source.template_key,
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
        skill_map = self.repository.get_platform_required_skill_map(source.id)
        self.repository.save_draft_with_skills(draft, skill_map)
        return self.get_draft(template_key)

    def create_new_template_draft(self, data: PlatformTemplateDraftCreate) -> PlatformTemplateDraftRead:
        """Starts a draft for a lineage that has never been published."""

        def build(template_key: str) -> PlatformTemplateDraft:
            return PlatformTemplateDraft(
                template_key=template_key,
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

        skills_map = self._skills_map(
            data.required_skill_ids,
            data.required_skill_groups,
            data.required_skill_versions,
        )
        draft = self._allocate_unique_key(build, lambda d: self.repository.save_new_draft_with_skills(d, skills_map))
        return self.get_draft(draft.template_key)

    def update_draft(self, template_key: str, data: PlatformTemplateDraftUpdate) -> PlatformTemplateDraftRead:
        draft = self.repository.get_draft(template_key)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for {template_key}")
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

        old_map = self.repository.get_draft_required_skill_map(draft.id)
        resolved_map = self._resolve_updated_skill_map(
            old_map,
            data.required_skill_ids,
            data.required_skill_groups,
            None,
            global_only=True,
            requested_versions=data.required_skill_versions,
        )
        self.repository.update_draft_with_skills(draft, resolved_map)
        return self.get_draft(template_key)

    def discard_draft(self, template_key: str) -> None:
        draft = self.repository.get_draft(template_key)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for {template_key}")
        self.repository.delete_draft(draft.id)

    def publish_draft(self, template_key: str) -> TemplateRead:
        """Converts a lineage's Draft Template Version into the next immutable
        platform_template row, carries over its required-skill selection, then
        clears the draft slot so a new draft can start."""
        draft = self.repository.get_draft(template_key)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for {template_key}")
        latest = self.repository.get_latest_platform_template(template_key)
        published = PlatformTemplate(
            template_key=draft.template_key,
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
        skill_map = self.repository.get_draft_required_skill_map(draft.id)
        published = self.repository.publish_draft_with_skills(published, draft.id, skill_map)
        skills = self.repository.get_platform_required_skills(published.id)
        return self.repository.to_read(published, skills)

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError

from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.domains.skills.files import DEFAULT_ENTRY_PATH, validate_files
from api.domains.skills.models import (
    Skill,
    SkillCreate,
    SkillDetailRead,
    SkillDraft,
    SkillDraftRead,
    SkillDraftUpdate,
    SkillFileRead,
    SkillFilter,
    SkillSource,
    SkillSummaryRead,
    SkillUpdate,
    SkillVersionDetailRead,
    SkillVersionRead,
)
from api.domains.skills.repository import SkillRepository
from api.domains.templates.slug import slugify
from api.infrastructure.shared.models import PaginatedItems, Pagination


@inject
@singleton
@dataclass
class SkillService:
    repository: SkillRepository
    permission_policy: PermissionPolicy

    def _org_id(self, context: CurrentUserContext) -> UUID:
        return context.require_current_user_organization().organization_id

    @staticmethod
    def _validated_files(files: list, entry_path: str = DEFAULT_ENTRY_PATH) -> list[tuple[str, str]]:
        try:
            return validate_files([(f.path, f.content) for f in files], entry_path=entry_path)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    def _allocate_slug(self, name: str, org_id: UUID) -> str:
        """Derive a slug that is unique within the organization.

        Distinct names can slugify onto the same value ("My Tool" / "my tool"), and
        the slug is the skill's mount directory, so collisions have to be broken
        here rather than surfacing as a database error.
        """
        base = slugify(name) or "skill"
        taken = {s.slug for s in self.repository.find_accessible_for_org(org_id) if s.organization_id == org_id}
        if base not in taken:
            return base
        suffix = 2
        while f"{base}-{suffix}" in taken:
            suffix += 1
        return f"{base}-{suffix}"

    def _allocate_fork_name(self, base: str, org_id: UUID) -> str:
        """A fork keeps the built-in's name when it's free in the organization and
        gains a ``(fork)`` suffix when the org already has a same-named skill, so
        the org-scoped ``(organization_id, name)`` uniqueness holds."""
        taken = {s.name for s in self.repository.find_accessible_for_org(org_id) if s.organization_id == org_id}
        if base not in taken:
            return base
        candidate = f"{base} (fork)"
        suffix = 2
        while candidate in taken:
            candidate = f"{base} (fork {suffix})"
            suffix += 1
        return candidate

    def _to_read(self, skill: Skill, version: int | None = None, has_draft: bool | None = None) -> SkillSummaryRead:
        if version is None:
            latest = self.repository.get_latest_version(skill.id)
            version = latest.version if latest else 1
        if has_draft is None:
            has_draft = self.repository.get_draft(skill.id) is not None
        return SkillSummaryRead.model_validate({**skill.model_dump(), "version": version, "has_draft": has_draft})

    def _get_or_404(self, skill_id: UUID, org_id: UUID) -> Skill:
        skill = self.repository.get_by_id_for_org(skill_id, org_id)
        if skill is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill {skill_id} not found",
            )
        return skill

    def create_skill(self, data: SkillCreate, context: CurrentUserContext) -> SkillSummaryRead:
        org_id = self._org_id(context)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_MANAGE)
        files = self._validated_files(data.files)
        slug = self._allocate_slug(data.name, org_id)
        skill = Skill(
            organization_id=org_id,
            name=data.name,
            slug=slug,
            description=data.description,
            # Custom skills mount under their own directory; only the built-ins
            # share one. tools_pointer stays NULL so the pointer is derived.
            root_dir=slug,
            entry_path=DEFAULT_ENTRY_PATH,
            source=SkillSource.CUSTOM,
            required_providers=data.required_providers,
        )
        self.repository.save(skill)
        version = self.repository.publish_version(skill.id, files, created_by=context.user.id)
        return self._to_read(skill, version.version, has_draft=False)

    def fork_skill(self, skill_id: UUID, context: CurrentUserContext) -> SkillDetailRead:
        """Create an org-scoped custom skill seeded from a built-in's latest version.

        The fork publishes its own v1 immediately (so it is a real, assignable
        lineage from the start) and then opens an in-flight draft seeded from that
        v1, so the author lands directly in the editor. The built-in lineage stays
        read-only and untouched; this is a one-time snapshot with no update tracking.
        """
        org_id = self._org_id(context)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_MANAGE)
        source = self._get_or_404(skill_id, org_id)
        if source.source != SkillSource.AAI_CLI:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only built-in skills can be forked; edit custom skills directly",
            )
        latest = self.repository.get_latest_version(source.id)
        if latest is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"No published version for skill {skill_id}"
            )
        files = [(f.path, f.content) for f in self.repository.get_files(latest.id)]

        name = self._allocate_fork_name(source.name, org_id)
        slug = self._allocate_slug(name, org_id)
        skill = Skill(
            organization_id=org_id,
            name=name,
            slug=slug,
            description=source.description,
            # The fork mounts under its own directory, so it can't collide with
            # the built-in's shared aai-cli root at manifest time. Entry path and
            # provider requirements carry over so the copied content keeps working.
            root_dir=slug,
            entry_path=source.entry_path,
            source=SkillSource.CUSTOM,
            required_providers=source.required_providers,
        )
        self.repository.save(skill)
        version = self.repository.publish_version(skill.id, files, created_by=context.user.id)
        self.repository.save_new_draft(
            skill.id,
            files,
            description=skill.description,
            required_providers=[p.value for p in skill.required_providers],
        )
        read = self._to_read(skill, version.version, has_draft=True)
        return SkillDetailRead.model_validate(
            {
                **read.model_dump(),
                "files": [SkillFileRead(path=path, content=content) for path, content in files],
                "is_assigned_to_agent": False,
            }
        )

    def update_skill(self, skill_id: UUID, data: SkillUpdate, context: CurrentUserContext) -> SkillSummaryRead:
        """Metadata-only: name, description, required providers. Content changes
        go through the draft/publish flow instead."""
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_MANAGE)
        if skill.source == SkillSource.AAI_CLI:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot modify built-in skills",
            )
        updated = data.model_dump(exclude_unset=True)
        # The slug (and therefore the mount directory) is deliberately not
        # recomputed on rename: renaming a skill must not move its files or
        # invalidate paths referenced from inside its own markdown.
        if "name" in updated:
            skill.name = updated["name"]
        if "description" in updated:
            skill.description = updated["description"]
        if "required_providers" in updated:
            skill.required_providers = updated["required_providers"]
        self.repository.save(skill)
        return self._to_read(skill)

    def get_skill_detail(self, skill_id: UUID, context: CurrentUserContext) -> SkillDetailRead:
        """A skill plus the files of its published version, for the editor/viewer."""
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_READ)
        latest = self.repository.get_latest_version(skill.id)
        files = self.repository.get_files(latest.id) if latest else []
        read = self._to_read(skill, latest.version if latest else 1)
        return SkillDetailRead.model_validate(
            {
                **read.model_dump(),
                "files": [SkillFileRead.model_validate(f) for f in files],
                "is_assigned_to_agent": self.repository.is_assigned_to_any_agent(skill.id),
            }
        )

    def list_skill_versions(self, skill_id: UUID, context: CurrentUserContext) -> list[SkillVersionRead]:
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_READ)
        versions = self.repository.list_versions(skill.id)
        pinned = self.repository.get_pinned_versions_for_skill(skill.id)
        return [
            SkillVersionRead.model_validate({**v.model_dump(), "is_pinned_by_agent": v.version in pinned})
            for v in versions
        ]

    def get_skill_version_detail(
        self, skill_id: UUID, version: int, context: CurrentUserContext
    ) -> SkillVersionDetailRead:
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_READ)
        skill_version = self.repository.get_version(skill.id, version)
        if skill_version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Version {version} not found for skill {skill_id}"
            )
        files = self.repository.get_files(skill_version.id)
        pinned = self.repository.get_pinned_versions_for_skill(skill.id)
        return SkillVersionDetailRead.model_validate(
            {
                **skill_version.model_dump(),
                "files": [SkillFileRead.model_validate(f) for f in files],
                "is_pinned_by_agent": version in pinned,
            }
        )

    def _draft_to_read(self, draft: SkillDraft) -> SkillDraftRead:
        files = self.repository.get_draft_files(draft.id)
        return SkillDraftRead.model_validate(
            {**draft.model_dump(), "files": [SkillFileRead.model_validate(f) for f in files]}
        )

    def _require_draftable_skill(self, skill_id: UUID, org_id: UUID, context: CurrentUserContext) -> Skill:
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_MANAGE)
        if skill.source == SkillSource.AAI_CLI:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot modify built-in skills",
            )
        return skill

    def get_skill_draft(self, skill_id: UUID, context: CurrentUserContext) -> SkillDraftRead:
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_MANAGE)
        draft = self.repository.get_draft(skill.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        return self._draft_to_read(draft)

    def start_skill_draft(self, skill_id: UUID, context: CurrentUserContext) -> SkillDraftRead:
        """Get-or-create the single in-flight draft for a skill, seeded from the
        latest published version. Recovering from a bad version is a per-agent
        concern handled by re-pinning the agent's assigned skill version, never a
        lineage-level restore."""
        org_id = self._org_id(context)
        skill = self._require_draftable_skill(skill_id, org_id, context)

        existing = self.repository.get_draft(skill.id)
        if existing is not None:
            return self._draft_to_read(existing)

        source = self.repository.get_latest_version(skill.id)
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"No published version for skill {skill_id}"
            )
        files = [(f.path, f.content) for f in self.repository.get_files(source.id)]
        draft = self.repository.save_new_draft(
            skill.id,
            files,
            description=skill.description,
            required_providers=[p.value for p in skill.required_providers],
        )
        return self._draft_to_read(draft)

    def update_skill_draft(self, skill_id: UUID, data: SkillDraftUpdate, context: CurrentUserContext) -> SkillDraftRead:
        org_id = self._org_id(context)
        skill = self._require_draftable_skill(skill_id, org_id, context)
        draft = self.repository.get_draft(skill.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        files = self._validated_files(data.files, skill.entry_path)
        draft = self.repository.update_draft_files(
            draft.id,
            files,
            description=data.description,
            required_providers=[p.value for p in data.required_providers]
            if data.required_providers is not None
            else None,
        )
        return self._draft_to_read(draft)

    def discard_skill_draft(self, skill_id: UUID, context: CurrentUserContext) -> None:
        org_id = self._org_id(context)
        skill = self._require_draftable_skill(skill_id, org_id, context)
        draft = self.repository.get_draft(skill.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        self.repository.delete_draft(draft.id)

    def publish_skill_draft(self, skill_id: UUID, context: CurrentUserContext) -> SkillSummaryRead:
        org_id = self._org_id(context)
        skill = self._require_draftable_skill(skill_id, org_id, context)
        draft = self.repository.get_draft(skill.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        files = [(f.path, f.content) for f in self.repository.get_draft_files(draft.id)]
        published = self.repository.publish_draft(skill.id, draft.id, files, created_by=context.user.id)
        # Reload the skill to pick up the draft's metadata applied in publish_draft.
        skill = self._get_or_404(skill_id, org_id)
        return self._to_read(skill, published.version, has_draft=False)

    def delete_skill_version(self, skill_id: UUID, version: int, context: CurrentUserContext) -> None:
        """Delete one immutable version snapshot from a skill's history.

        Protections: built-ins are never modified; the last remaining version can't
        be removed (the lineage must keep content); and a version pinned by any
        agent can't be removed, because deleting it would break that agent's
        explicit pin (recover from a bad version by re-pinning, never by deleting
        a pinned snapshot). Historical versions no agent pins are always safe to
        prune.
        """
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_MANAGE)
        if skill.source == SkillSource.AAI_CLI:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot modify built-in skills",
            )
        skill_version = self.repository.get_version(skill.id, version)
        if skill_version is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Version {version} not found for skill {skill_id}"
            )
        versions = self.repository.list_versions(skill.id)
        if len(versions) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete the only version of a skill",
            )
        if self.repository.is_skill_version_pinned(skill.id, version):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete a version that is pinned by an agent",
            )
        try:
            self.repository.delete_version_by_id(skill_version.id)
        except IntegrityError:
            # Safety net for the concurrent delete/pin race: the composite FK
            # on agent_skill(skill_id, pinned_version) blocks the delete if an
            # agent pinned this version between the check above and the delete.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete a version that is pinned by an agent",
            ) from None

    def get_skill(self, skill_id: UUID, context: CurrentUserContext) -> SkillSummaryRead:
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_READ)
        return self._to_read(skill)

    def list_skills(
        self,
        skill_filter: SkillFilter,
        pagination: Pagination,
        context: CurrentUserContext,
    ) -> PaginatedItems[SkillSummaryRead]:
        org_id = self._org_id(context)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_READ)
        skills, total = self.repository.find_all_for_org(org_id, skill_filter, pagination)
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=self._to_reads(skills),
        )

    def list_global_skills_for_platform_admin(self) -> list[SkillSummaryRead]:
        return self._to_reads(self.repository.find_all_global())

    def _to_reads(self, skills: list[Skill]) -> list[SkillSummaryRead]:
        """Batch the version and draft lookups so listing N skills stays at two extra queries."""
        skill_ids = [s.id for s in skills]
        versions = self.repository.get_latest_version_numbers(skill_ids)
        draft_skill_ids = self.repository.get_draft_skill_ids(skill_ids)
        return [
            SkillSummaryRead.model_validate(
                {
                    **skill.model_dump(),
                    "version": versions.get(skill.id, 1),
                    "has_draft": skill.id in draft_skill_ids,
                }
            )
            for skill in skills
        ]

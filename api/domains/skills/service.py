from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

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

    def _to_read(self, skill: Skill, version: int | None = None) -> SkillSummaryRead:
        if version is None:
            latest = self.repository.get_latest_version(skill.id)
            version = latest.version if latest else 1
        return SkillSummaryRead.model_validate({**skill.model_dump(), "version": version})

    def _get_or_404(self, skill_id: UUID, org_id: UUID) -> Skill:
        skill = self.repository.get_by_id(skill_id)
        if skill is None or (skill.organization_id is not None and skill.organization_id != org_id):
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
        return self._to_read(skill, version.version)

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
            {**read.model_dump(), "files": [SkillFileRead.model_validate(f) for f in files]}
        )

    def list_skill_versions(self, skill_id: UUID, context: CurrentUserContext) -> list[SkillVersionRead]:
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_READ)
        return [SkillVersionRead.model_validate(v) for v in self.repository.list_versions(skill.id)]

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
        return SkillVersionDetailRead.model_validate(
            {**skill_version.model_dump(), "files": [SkillFileRead.model_validate(f) for f in files]}
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
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_READ)
        draft = self.repository.get_draft(skill.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        return self._draft_to_read(draft)

    def start_skill_draft(
        self, skill_id: UUID, context: CurrentUserContext, source_version: int | None = None
    ) -> SkillDraftRead:
        """Get-or-create the single in-flight draft for a skill, seeded from a
        selected published version or, by default, the latest version.

        Selecting an older version here is how "rollback" works: it seeds the
        draft with that version's content for review, and publishing turns it
        into the next version rather than mutating history.
        """
        org_id = self._org_id(context)
        skill = self._require_draftable_skill(skill_id, org_id, context)

        existing = self.repository.get_draft(skill.id)
        if existing is not None:
            if source_version is not None:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A draft already exists; discard it before restoring another version",
                )
            return self._draft_to_read(existing)

        source = (
            self.repository.get_version(skill.id, source_version)
            if source_version is not None
            else self.repository.get_latest_version(skill.id)
        )
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"Version {source_version} not found for skill"
            )
        files = [(f.path, f.content) for f in self.repository.get_files(source.id)]
        draft = self.repository.save_new_draft(skill.id, files, source_version=source_version)
        return self._draft_to_read(draft)

    def update_skill_draft(self, skill_id: UUID, data: SkillDraftUpdate, context: CurrentUserContext) -> SkillDraftRead:
        org_id = self._org_id(context)
        skill = self._require_draftable_skill(skill_id, org_id, context)
        draft = self.repository.get_draft(skill.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        files = self._validated_files(data.files, skill.entry_path)
        draft = self.repository.update_draft_files(draft.id, files)
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
        published = self.repository.publish_draft(
            skill.id, draft.id, files, created_by=context.user.id, restored_from_version=draft.source_version
        )
        return self._to_read(skill, published.version)

    def delete_skill(self, skill_id: UUID, context: CurrentUserContext) -> None:
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_MANAGE)
        if skill.source == SkillSource.AAI_CLI:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete built-in skills",
            )
        if self.repository.is_assigned_to_any_agent(skill_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Skill is currently assigned to one or more agents",
            )
        blocking_templates = self.repository.get_latest_template_keys_requiring_skill(skill_id, org_id)
        if blocking_templates:
            template_keys = ", ".join(blocking_templates)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Skill is required by template(s): {template_keys}. "
                    "Remove it from those templates before deleting."
                ),
            )
        self.repository.delete_stale_template_skill_refs(skill_id, org_id)
        self.repository.delete(skill)

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
        """Batch the version lookup so listing N skills stays at one extra query."""
        versions = self.repository.get_latest_version_numbers([s.id for s in skills])
        return [
            SkillSummaryRead.model_validate({**skill.model_dump(), "version": versions.get(skill.id, 1)})
            for skill in skills
        ]

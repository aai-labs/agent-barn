from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlalchemy.exc import IntegrityError

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent
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
    agent_authorization: AgentAuthorization

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
        taken = {s.slug for s in self.repository.find_accessible_for_org(org_id)}
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
        taken = {s.name for s in self.repository.find_org_scoped(org_id)}
        if base not in taken:
            return base
        candidate = f"{base} (fork)"
        suffix = 2
        while candidate in taken:
            candidate = f"{base} (fork {suffix})"
            suffix += 1
        return candidate

    def _save_new_skill(self, skill: Skill) -> None:
        """Persist a new lineage and translate uniqueness races to a conflict."""
        try:
            self.repository.save(skill)
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A skill with this name or mount slug already exists in this organization",
            ) from None

    def _save_existing_skill(self, skill: Skill, detail: str) -> None:
        try:
            self.repository.save(skill)
        except IntegrityError:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail) from None

    def _delete_skill_version(self, skill: Skill, version: int) -> None:
        """Delete an unreferenced, non-final immutable Skill Version."""
        skill_version = self.repository.get_version(skill.id, version)
        if skill_version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Version {version} not found")
        if len(self.repository.list_versions(skill.id)) <= 1:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete the only version of a skill",
            )
        if self.repository.is_skill_version_referenced_anywhere(skill.id, version):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Cannot delete a Skill Version that is still referenced "
                    "(it may be pinned by an agent or required by a Template)"
                ),
            )
        try:
            self.repository.delete_version_by_id(skill_version.id)
        except IntegrityError:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "Cannot delete a Skill Version that is still referenced "
                    "(it may be pinned by an agent or required by a Template)"
                ),
            ) from None

    def _delete_custom_skill_lineage(self, skill: Skill) -> None:
        """Delete a custom lineage and all of its owned snapshots when unused."""
        if skill.source == SkillSource.AAI_CLI:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot delete built-in skills",
            )

        blocker = self.repository.delete_skill_if_unused(skill.id)
        if blocker == "not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill {skill.id} not found")
        if blocker == "agent":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete a Skill that is used by one or more Agents",
            )
        if blocker == "reference":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot delete a Skill referenced by a Template, Override, or fork",
            )

    def _to_read(
        self,
        skill: Skill,
        version: int | None = None,
        has_draft: bool | None = None,
        *,
        include_draft: bool = True,
    ) -> SkillSummaryRead:
        latest = self.repository.get_latest_version(skill.id)
        if version is None:
            version = latest.version if latest else None
        draft = self.repository.get_draft(skill.id) if include_draft else None
        if has_draft is None:
            has_draft = draft is not None
        source_skill_id = latest.source_skill_id if latest else None
        source_skill_version = latest.source_skill_version if latest else None
        update_available = self.repository.has_source_update(skill.id)
        if draft is not None and draft.source_skill_id is not None and draft.source_skill_version is not None:
            source_skill_id = draft.source_skill_id
            source_skill_version = draft.source_skill_version
            pending_source = self.repository.get_skill_update_source(skill.id)
            update_available = pending_source is not None and (
                pending_source.skill_id != draft.source_skill_id or pending_source.version > draft.source_skill_version
            )
        return SkillSummaryRead.model_validate(
            {
                **skill.model_dump(),
                "version": version,
                "has_draft": has_draft,
                "source_skill_id": source_skill_id,
                "source_skill_version": source_skill_version,
                "update_available": update_available,
            }
        )

    def _get_or_404(self, skill_id: UUID, org_id: UUID) -> Skill:
        skill = self.repository.get_by_id_for_org(skill_id, org_id)
        if skill is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill {skill_id} not found",
            )
        return skill

    def _allocate_platform_slug(self, name: str) -> str:
        base = slugify(name) or "skill"
        taken = self.repository.find_all_slugs()
        if base not in taken:
            return base
        suffix = 2
        while f"{base}-{suffix}" in taken:
            suffix += 1
        return f"{base}-{suffix}"

    def _get_platform_or_404(self, skill_id: UUID) -> Skill:
        skill = self.repository.get_by_id_global(skill_id)
        if skill is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill {skill_id} not found")
        return skill

    def create_platform_skill(self, data: SkillCreate, context: CurrentUserContext) -> SkillDetailRead:
        files = self._validated_files(data.files)
        slug = self._allocate_platform_slug(data.name)
        skill = Skill(
            organization_id=None,
            agent_id=None,
            name=data.name,
            slug=slug,
            description=data.description,
            root_dir=slug,
            entry_path=DEFAULT_ENTRY_PATH,
            source=SkillSource.CUSTOM,
            required_providers=data.required_providers,
        )
        self._save_new_skill(skill)
        self.repository.save_new_draft(
            skill.id,
            files,
            description=data.description,
            required_providers=[provider.value for provider in data.required_providers],
        )
        return self._agent_detail(skill, files, has_draft=True)

    def update_platform_skill(self, skill_id: UUID, data: SkillUpdate) -> SkillSummaryRead:
        skill = self._get_platform_or_404(skill_id)
        updated = data.model_dump(exclude_unset=True)
        if "name" in updated and updated["name"] != skill.name:
            existing = self.repository.get_by_name_global(updated["name"])
            if existing is not None and existing.id != skill.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A Platform Skill with this name already exists",
                )
            skill.name = updated["name"]
            self._save_existing_skill(skill, "A Platform Skill with this name already exists")
        return self._to_read(skill)

    def get_platform_skill_detail(self, skill_id: UUID) -> SkillDetailRead:
        skill = self._get_platform_or_404(skill_id)
        latest = self.repository.get_latest_version(skill.id)
        draft = self.repository.get_draft(skill.id)
        files = (
            self.repository.get_files(latest.id)
            if latest
            else (self.repository.get_draft_files(draft.id) if draft else [])
        )
        read = self._to_read(skill, latest.version if latest else None, has_draft=draft is not None)
        return SkillDetailRead.model_validate(
            {
                **read.model_dump(),
                "files": [SkillFileRead.model_validate(file) for file in files],
                "is_assigned_to_agent": self.repository.is_assigned_to_any_agent_globally(skill.id),
            }
        )

    def start_platform_skill_draft(self, skill_id: UUID) -> SkillDraftRead:
        skill = self._get_platform_or_404(skill_id)
        draft = self.repository.get_draft(skill.id)
        if draft is not None:
            return self._draft_to_read(draft)
        latest = self.repository.get_latest_version(skill.id)
        if latest is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill has no published version")
        files = [(file.path, file.content) for file in self.repository.get_files(latest.id)]
        draft = self.repository.save_new_draft(
            skill.id,
            files,
            description=latest.description if latest.description is not None else skill.description,
            required_providers=[provider.value for provider in (latest.required_providers or skill.required_providers)],
            source_skill_id=latest.source_skill_id,
            source_skill_version=latest.source_skill_version,
        )
        return self._draft_to_read(draft)

    def get_platform_skill_draft(self, skill_id: UUID) -> SkillDraftRead:
        self._get_platform_or_404(skill_id)
        draft = self.repository.get_draft(skill_id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        return self._draft_to_read(draft)

    def update_platform_skill_draft(self, skill_id: UUID, data: SkillDraftUpdate) -> SkillDraftRead:
        skill = self._get_platform_or_404(skill_id)
        draft = self.repository.get_draft(skill.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        files = self._validated_files(data.files)
        metadata: dict[str, str | list[str] | None] = {}
        if "description" in data.model_fields_set:
            metadata["description"] = data.description
        if "required_providers" in data.model_fields_set:
            metadata["required_providers"] = (
                [provider.value for provider in data.required_providers]
                if data.required_providers is not None
                else None
            )
        updated = self.repository.update_draft_files(draft.id, files, metadata=metadata)
        return self._draft_to_read(updated)

    def discard_platform_skill_draft(self, skill_id: UUID) -> None:
        self._get_platform_or_404(skill_id)
        draft = self.repository.get_draft(skill_id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        if self.repository.get_latest_version(skill_id) is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot discard the initial draft before the first Skill Version is published",
            )
        self.repository.delete_draft(draft.id)

    def publish_platform_skill_draft(self, skill_id: UUID, context: CurrentUserContext) -> SkillSummaryRead:
        skill = self._get_platform_or_404(skill_id)
        draft = self.repository.get_draft(skill.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        files = [(file.path, file.content) for file in self.repository.get_draft_files(draft.id)]
        published = self.repository.publish_draft(skill.id, draft.id, files, created_by=context.user.id)
        return self._to_read(skill, published.version, has_draft=False)

    def delete_platform_skill_version(self, skill_id: UUID, version: int) -> None:
        skill = self._get_platform_or_404(skill_id)
        if skill.source == SkillSource.AAI_CLI:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot modify built-in skills",
            )
        self._delete_skill_version(skill, version)

    def delete_platform_skill(self, skill_id: UUID) -> None:
        skill = self._get_platform_or_404(skill_id)
        self._delete_custom_skill_lineage(skill)

    def list_platform_skill_versions(self, skill_id: UUID) -> list[SkillVersionRead]:
        self._get_platform_or_404(skill_id)
        versions = self.repository.list_versions(skill_id)
        pinned = self.repository.get_pinned_versions_for_skill_globally(skill_id)
        return [
            SkillVersionRead.model_validate({**version.model_dump(), "is_pinned_by_agent": version.version in pinned})
            for version in versions
        ]

    def get_platform_skill_version(self, skill_id: UUID, version: int) -> SkillVersionDetailRead:
        self._get_platform_or_404(skill_id)
        skill_version = self.repository.get_version(skill_id, version)
        if skill_version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Version {version} not found")
        pinned = version in self.repository.get_pinned_versions_for_skill_globally(skill_id)
        return SkillVersionDetailRead.model_validate(
            {
                **skill_version.model_dump(),
                "files": [SkillFileRead.model_validate(file) for file in self.repository.get_files(skill_version.id)],
                "is_pinned_by_agent": pinned,
            }
        )

    def _allocate_agent_slug(self, name: str, agent: Agent) -> str:
        base = slugify(name) or "skill"
        taken = {skill.slug for skill in self.repository.find_visible_for_agent(agent.id, agent.organization_id)}
        if base not in taken:
            return base
        suffix = 2
        while f"{base}-{suffix}" in taken:
            suffix += 1
        return f"{base}-{suffix}"

    def _agent_detail(
        self,
        skill: Skill,
        files: list[tuple[str, str]],
        *,
        has_draft: bool,
        agent_id: UUID | None = None,
    ) -> SkillDetailRead:
        read = self._to_read(skill, has_draft=has_draft)
        return SkillDetailRead.model_validate(
            {
                **read.model_dump(),
                "files": [SkillFileRead(path=path, content=content) for path, content in files],
                "is_assigned_to_agent": (
                    self.repository.is_assigned_to_agent(skill.id, agent_id) if agent_id is not None else False
                ),
            }
        )

    def _get_visible_agent_skill(
        self,
        agent_id: UUID,
        skill_id: UUID,
        context: CurrentUserContext,
        permission: PermissionKey,
    ) -> tuple[Agent, Skill]:
        agent = self.agent_authorization.require_action(context, agent_id, permission)
        skill = self.repository.get_by_id_for_agent(skill_id, agent.id, agent.organization_id)
        if skill is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill {skill_id} not found")
        return agent, skill

    def _get_agent_owned_skill(
        self,
        agent_id: UUID,
        skill_id: UUID,
        context: CurrentUserContext,
        permission: PermissionKey,
    ) -> tuple[Agent, Skill]:
        agent, skill = self._get_visible_agent_skill(agent_id, skill_id, context, permission)
        if skill.agent_id != agent.id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Skill {skill_id} not found")
        return agent, skill

    def update_agent_skill(
        self,
        agent_id: UUID,
        skill_id: UUID,
        data: SkillUpdate,
        context: CurrentUserContext,
    ) -> SkillSummaryRead:
        agent, skill = self._get_agent_owned_skill(agent_id, skill_id, context, PermissionKey.AGENT_UPDATE)
        updated = data.model_dump(exclude_unset=True)
        if "name" in updated and updated["name"] != skill.name:
            existing = next(
                (
                    visible
                    for visible in self.repository.find_visible_for_agent(agent_id, agent.organization_id)
                    if visible.agent_id == agent_id and visible.name == updated["name"]
                ),
                None,
            )
            if existing is not None and existing.id != skill.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="An Agent Skill with this name already exists",
                )
            skill.name = updated["name"]
            self._save_existing_skill(skill, "An Agent Skill with this name already exists")
        return self._to_read(skill)

    def get_agent_skill_detail(
        self,
        agent_id: UUID,
        skill_id: UUID,
        context: CurrentUserContext,
    ) -> SkillDetailRead:
        agent, skill = self._get_visible_agent_skill(agent_id, skill_id, context, PermissionKey.AGENT_READ)
        latest = self.repository.get_latest_version(skill.id)
        draft = self.repository.get_draft(skill.id) if skill.agent_id == agent.id else None
        files = (
            self.repository.get_files(latest.id)
            if latest
            else (self.repository.get_draft_files(draft.id) if draft else [])
        )
        return self._agent_detail(
            skill,
            [(file.path, file.content) for file in files],
            has_draft=draft is not None,
            agent_id=agent.id,
        )

    def get_agent_skill_draft(
        self,
        agent_id: UUID,
        skill_id: UUID,
        context: CurrentUserContext,
    ) -> SkillDraftRead:
        _, skill = self._get_agent_owned_skill(agent_id, skill_id, context, PermissionKey.AGENT_UPDATE)
        draft = self.repository.get_draft(skill.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        return self._draft_to_read(draft)

    def start_agent_skill_draft(
        self,
        agent_id: UUID,
        skill_id: UUID,
        context: CurrentUserContext,
    ) -> SkillDraftRead:
        _, skill = self._get_agent_owned_skill(agent_id, skill_id, context, PermissionKey.AGENT_UPDATE)
        existing = self.repository.get_draft(skill.id)
        if existing is not None:
            return self._draft_to_read(existing)
        latest = self.repository.get_latest_version(skill.id)
        if latest is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Skill has no published version")
        files = [(file.path, file.content) for file in self.repository.get_files(latest.id)]
        draft = self.repository.save_new_draft(
            skill.id,
            files,
            description=latest.description if latest.description is not None else skill.description,
            required_providers=[provider.value for provider in (latest.required_providers or skill.required_providers)],
            source_skill_id=latest.source_skill_id,
            source_skill_version=latest.source_skill_version,
        )
        return self._draft_to_read(draft)

    def update_agent_skill_draft(
        self,
        agent_id: UUID,
        skill_id: UUID,
        data: SkillDraftUpdate,
        context: CurrentUserContext,
    ) -> SkillDraftRead:
        _, skill = self._get_agent_owned_skill(agent_id, skill_id, context, PermissionKey.AGENT_UPDATE)
        draft = self.repository.get_draft(skill.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        files = self._validated_files(data.files)
        metadata: dict[str, str | list[str] | None] = {}
        if "description" in data.model_fields_set:
            metadata["description"] = data.description
        if "required_providers" in data.model_fields_set:
            metadata["required_providers"] = (
                [provider.value for provider in data.required_providers]
                if data.required_providers is not None
                else None
            )
        return self._draft_to_read(self.repository.update_draft_files(draft.id, files, metadata=metadata))

    def discard_agent_skill_draft(self, agent_id: UUID, skill_id: UUID, context: CurrentUserContext) -> None:
        _, skill = self._get_agent_owned_skill(agent_id, skill_id, context, PermissionKey.AGENT_UPDATE)
        draft = self.repository.get_draft(skill.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        if self.repository.get_latest_version(skill.id) is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot discard the initial draft before the first Skill Version is published",
            )
        self.repository.delete_draft(draft.id)

    def publish_agent_skill_draft(
        self,
        agent_id: UUID,
        skill_id: UUID,
        context: CurrentUserContext,
    ) -> SkillSummaryRead:
        _, skill = self._get_agent_owned_skill(agent_id, skill_id, context, PermissionKey.AGENT_UPDATE)
        draft = self.repository.get_draft(skill.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        files = [(file.path, file.content) for file in self.repository.get_draft_files(draft.id)]
        published = self.repository.publish_draft(skill.id, draft.id, files, created_by=context.user.id)
        return self._to_read(skill, published.version, has_draft=False)

    def apply_agent_skill_source_update(
        self,
        agent_id: UUID,
        skill_id: UUID,
        context: CurrentUserContext,
    ) -> SkillDetailRead:
        agent, skill = self._get_agent_owned_skill(agent_id, skill_id, context, PermissionKey.AGENT_UPDATE)
        source = self.repository.get_skill_update_source(skill.id)
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No newer source Skill Version is available",
            )
        files = [(file.path, file.content) for file in self.repository.get_files(source.id)]
        metadata = {
            "description": source.description,
            "required_providers": [provider.value for provider in source.required_providers],
        }
        draft = self.repository.get_draft(skill.id)
        if draft is not None:
            self.repository.update_draft_files(
                draft.id,
                files,
                metadata=metadata,
                source_skill_id=source.skill_id,
                source_skill_version=source.version,
            )
            return self._agent_detail(skill, files, has_draft=True, agent_id=agent.id).model_copy(
                update={
                    "source_skill_id": source.skill_id,
                    "source_skill_version": source.version,
                    "update_available": False,
                }
            )
        self.repository.publish_version(
            skill.id,
            files,
            description=source.description,
            required_providers=source.required_providers,
            source_skill_id=source.skill_id,
            source_skill_version=source.version,
            created_by=context.user.id,
        )
        skill.description = source.description
        skill.required_providers = source.required_providers
        self.repository.save(skill)
        return self._agent_detail(skill, files, has_draft=False, agent_id=agent.id)

    def delete_agent_skill_version(
        self,
        agent_id: UUID,
        skill_id: UUID,
        version: int,
        context: CurrentUserContext,
    ) -> None:
        _, skill = self._get_agent_owned_skill(agent_id, skill_id, context, PermissionKey.AGENT_UPDATE)
        self._delete_skill_version(skill, version)

    def delete_agent_skill(self, agent_id: UUID, skill_id: UUID, context: CurrentUserContext) -> None:
        _, skill = self._get_agent_owned_skill(agent_id, skill_id, context, PermissionKey.AGENT_UPDATE)
        self._delete_custom_skill_lineage(skill)

    def list_agent_skill_versions(
        self,
        agent_id: UUID,
        skill_id: UUID,
        context: CurrentUserContext,
    ) -> list[SkillVersionRead]:
        agent, skill = self._get_visible_agent_skill(agent_id, skill_id, context, PermissionKey.AGENT_READ)
        pinned = self.repository.get_pinned_versions_for_skill(skill.id, agent.organization_id)
        return [
            SkillVersionRead.model_validate({**version.model_dump(), "is_pinned_by_agent": version.version in pinned})
            for version in self.repository.list_versions(skill.id)
        ]

    def get_agent_skill_version(
        self,
        agent_id: UUID,
        skill_id: UUID,
        version: int,
        context: CurrentUserContext,
    ) -> SkillVersionDetailRead:
        _, skill = self._get_visible_agent_skill(agent_id, skill_id, context, PermissionKey.AGENT_READ)
        skill_version = self.repository.get_version(skill.id, version)
        if skill_version is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Version {version} not found")
        is_pinned = (
            self.repository.is_skill_version_pinned(skill.id, version, skill.organization_id)
            if skill.organization_id is not None
            else False
        )
        return SkillVersionDetailRead.model_validate(
            {
                **skill_version.model_dump(),
                "files": [SkillFileRead.model_validate(file) for file in self.repository.get_files(skill_version.id)],
                "is_pinned_by_agent": is_pinned,
            }
        )

    def create_agent_skill(
        self,
        agent_id: UUID,
        data: SkillCreate,
        context: CurrentUserContext,
    ) -> SkillDetailRead:
        agent = self.agent_authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        files = self._validated_files(data.files)
        slug = self._allocate_agent_slug(data.name, agent)
        skill = Skill(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            name=data.name,
            slug=slug,
            description=data.description,
            root_dir=slug,
            entry_path=DEFAULT_ENTRY_PATH,
            source=SkillSource.CUSTOM,
            required_providers=data.required_providers,
        )
        self._save_new_skill(skill)
        self.repository.save_new_draft(
            skill.id,
            files,
            description=data.description,
            required_providers=[provider.value for provider in data.required_providers],
        )
        return self._agent_detail(skill, files, has_draft=True, agent_id=agent.id)

    def fork_agent_skill(
        self,
        agent_id: UUID,
        source_skill_id: UUID,
        context: CurrentUserContext,
    ) -> SkillDetailRead:
        agent = self.agent_authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        source = self.repository.get_by_id_for_agent(source_skill_id, agent.id, agent.organization_id)
        if source is None or source.agent_id is not None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source Skill not found")
        latest = self.repository.get_latest_version(source.id)
        if latest is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source Skill has no published version")
        files = [(file.path, file.content) for file in self.repository.get_files(latest.id)]
        slug = self._allocate_agent_slug(source.name, agent)
        providers = latest.required_providers or source.required_providers
        skill = Skill(
            organization_id=agent.organization_id,
            agent_id=agent.id,
            name=source.name,
            slug=slug,
            description=latest.description if latest.description is not None else source.description,
            root_dir=slug,
            entry_path=DEFAULT_ENTRY_PATH,
            source=SkillSource.CUSTOM,
            required_providers=providers,
        )
        self._save_new_skill(skill)
        self.repository.save_new_draft(
            skill.id,
            files,
            description=skill.description,
            required_providers=[provider.value for provider in providers],
            source_skill_id=source.id,
            source_skill_version=latest.version,
        )
        return self._agent_detail(skill, files, has_draft=True, agent_id=agent.id)

    def list_agent_skills(
        self,
        agent_id: UUID,
        skill_filter: SkillFilter,
        pagination: Pagination,
        context: CurrentUserContext,
    ) -> PaginatedItems[SkillSummaryRead]:
        agent = self.agent_authorization.require_action(context, agent_id, PermissionKey.AGENT_READ)
        skills, total = self.repository.find_all_for_agent(agent.id, agent.organization_id, skill_filter, pagination)
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=self._to_reads(skills, agent_id=agent.id),
        )

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
        self._save_new_skill(skill)
        self.repository.save_new_draft(
            skill.id,
            files,
            description=data.description,
            required_providers=[p.value for p in data.required_providers],
        )
        return self._to_read(skill, version=None, has_draft=True)

    def fork_skill(self, skill_id: UUID, context: CurrentUserContext) -> SkillDetailRead:
        """Create an independent Organization Skill draft from a visible source version."""
        org_id = self._org_id(context)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_MANAGE)
        source = self._get_or_404(skill_id, org_id)
        latest = self.repository.get_latest_version(source.id)
        if latest is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=f"No published version for skill {skill_id}"
            )
        files = [(f.path, f.content) for f in self.repository.get_files(latest.id)]
        name = self._allocate_fork_name(source.name, org_id)
        slug = self._allocate_slug(name, org_id)
        required_providers = latest.required_providers or source.required_providers
        skill = Skill(
            organization_id=org_id,
            name=name,
            slug=slug,
            description=latest.description if latest.description is not None else source.description,
            root_dir=slug,
            entry_path=DEFAULT_ENTRY_PATH,
            source=SkillSource.CUSTOM,
            required_providers=required_providers,
        )
        self._save_new_skill(skill)
        self.repository.save_new_draft(
            skill.id,
            files,
            description=skill.description,
            required_providers=[p.value if hasattr(p, "value") else p for p in required_providers],
            source_skill_id=source.id,
            source_skill_version=latest.version,
        )
        read = self._to_read(skill, version=None, has_draft=True)
        return SkillDetailRead.model_validate(
            {
                **read.model_dump(),
                "files": [SkillFileRead(path=path, content=content) for path, content in files],
                "is_assigned_to_agent": self.repository.is_assigned_to_any_agent(skill.id, org_id),
            }
        )

    def apply_source_update(self, skill_id: UUID, context: CurrentUserContext) -> SkillDetailRead:
        """Apply the newest direct source snapshot to an Organization fork.

        Without a draft this publishes the copied source immediately. With a
        draft, the source replaces the draft after the caller's confirmation but
        remains unpublished for review.
        """
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_MANAGE)
        if skill.organization_id != org_id or skill.agent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only organization-owned Skills can be updated here",
            )
        source = self.repository.get_skill_update_source(skill.id)
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="No newer source Skill Version is available",
            )
        source_files = [(file.path, file.content) for file in self.repository.get_files(source.id)]
        metadata = {
            "description": source.description,
            "required_providers": [provider.value for provider in source.required_providers],
        }
        draft = self.repository.get_draft(skill.id)
        if draft is not None:
            self.repository.update_draft_files(
                draft.id,
                source_files,
                metadata=metadata,
                source_skill_id=source.skill_id,
                source_skill_version=source.version,
            )
            files = source_files
            latest = self.repository.get_latest_version(skill.id)
            read = self._to_read(skill, latest.version if latest else None, has_draft=True).model_copy(
                update={
                    "source_skill_id": source.skill_id,
                    "source_skill_version": source.version,
                    "update_available": False,
                }
            )
        else:
            published = self.repository.publish_version(
                skill.id,
                source_files,
                description=source.description,
                required_providers=source.required_providers,
                source_skill_id=source.skill_id,
                source_skill_version=source.version,
                created_by=context.user.id,
            )
            skill.description = source.description
            skill.required_providers = source.required_providers
            self.repository.save(skill)
            files = source_files
            read = self._to_read(skill, published.version, has_draft=False)
        return SkillDetailRead.model_validate(
            {
                **read.model_dump(),
                "files": [SkillFileRead(path=path, content=content) for path, content in files],
                "is_assigned_to_agent": self.repository.is_assigned_to_any_agent(skill.id, org_id),
            }
        )

    def update_skill(self, skill_id: UUID, data: SkillUpdate, context: CurrentUserContext) -> SkillSummaryRead:
        """Update an organization-owned Skill's name; content is draft-gated."""
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_MANAGE)
        if skill.organization_id != org_id or skill.agent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only organization-owned Skills can be modified here",
            )
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
        self._save_existing_skill(skill, "An Organization Skill with this name already exists")
        return self._to_read(skill)

    def get_skill_detail(self, skill_id: UUID, context: CurrentUserContext) -> SkillDetailRead:
        """A skill plus the files of its published version, for the editor/viewer."""
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_READ)
        latest = self.repository.get_latest_version(skill.id)
        draft = self.repository.get_draft(skill.id) if skill.organization_id == org_id else None
        files = (
            self.repository.get_files(latest.id)
            if latest
            else (self.repository.get_draft_files(draft.id) if draft else [])
        )
        read = self._to_read(skill, latest.version if latest else None, has_draft=draft is not None)
        return SkillDetailRead.model_validate(
            {
                **read.model_dump(),
                "files": [SkillFileRead.model_validate(f) for f in files],
                "is_assigned_to_agent": self.repository.is_assigned_to_any_agent(skill.id, org_id),
            }
        )

    def list_skill_versions(self, skill_id: UUID, context: CurrentUserContext) -> list[SkillVersionRead]:
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_READ)
        versions = self.repository.list_versions(skill.id)
        pinned = self.repository.get_pinned_versions_for_skill(skill.id, org_id)
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
        pinned = self.repository.get_pinned_versions_for_skill(skill.id, org_id)
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
        if skill.organization_id != org_id or skill.agent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only organization-owned Skills can be modified here",
            )
        if skill.source == SkillSource.AAI_CLI:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot modify built-in skills",
            )
        return skill

    def get_skill_draft(self, skill_id: UUID, context: CurrentUserContext) -> SkillDraftRead:
        org_id = self._org_id(context)
        skill = self._require_draftable_skill(skill_id, org_id, context)
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
            description=source.description if source.description is not None else skill.description,
            required_providers=[
                p.value if hasattr(p, "value") else p for p in (source.required_providers or skill.required_providers)
            ],
            source_skill_id=source.source_skill_id,
            source_skill_version=source.source_skill_version,
        )
        return self._draft_to_read(draft)

    def update_skill_draft(self, skill_id: UUID, data: SkillDraftUpdate, context: CurrentUserContext) -> SkillDraftRead:
        org_id = self._org_id(context)
        skill = self._require_draftable_skill(skill_id, org_id, context)
        draft = self.repository.get_draft(skill.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        files = self._validated_files(data.files, skill.entry_path)
        metadata: dict[str, str | list[str] | None] = {}
        if "description" in data.model_fields_set:
            metadata["description"] = data.description
        if "required_providers" in data.model_fields_set:
            metadata["required_providers"] = (
                [p.value for p in data.required_providers] if data.required_providers is not None else None
            )
        draft = self.repository.update_draft_files(draft.id, files, metadata=metadata)
        return self._draft_to_read(draft)

    def discard_skill_draft(self, skill_id: UUID, context: CurrentUserContext) -> None:
        org_id = self._org_id(context)
        skill = self._require_draftable_skill(skill_id, org_id, context)
        draft = self.repository.get_draft(skill.id)
        if draft is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"No draft for skill {skill_id}")
        if self.repository.get_latest_version(skill.id) is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Cannot discard the initial draft before the first Skill Version is published",
            )
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

        Protections: Platform Skills are never modified; the last remaining
        version cannot be removed; and any version referenced by an Agent,
        Template, draft, or fork source cannot be removed.
        """
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_MANAGE)
        if skill.organization_id != org_id or skill.agent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only organization-owned Skills can be modified here",
            )
        if skill.source == SkillSource.AAI_CLI:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot modify built-in skills",
            )
        self._delete_skill_version(skill, version)

    def delete_skill(self, skill_id: UUID, context: CurrentUserContext) -> None:
        """Delete an unused Organization-owned custom Skill lineage."""
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_MANAGE)
        if skill.organization_id != org_id or skill.agent_id is not None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only organization-owned Skills can be deleted here",
            )
        self._delete_custom_skill_lineage(skill)

    def get_skill(self, skill_id: UUID, context: CurrentUserContext) -> SkillSummaryRead:
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_READ)
        return self._to_read(skill, include_draft=skill.organization_id == org_id)

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
            items=self._to_reads(skills, include_platform_drafts=False),
        )

    def list_global_skills_for_platform_admin(self) -> list[SkillSummaryRead]:
        return self._to_reads(self.repository.find_all_global())

    def _to_reads(
        self,
        skills: list[Skill],
        *,
        include_platform_drafts: bool = True,
        agent_id: UUID | None = None,
    ) -> list[SkillSummaryRead]:
        """Build lineage summaries with their latest source/update state."""
        skill_ids = [s.id for s in skills]
        latest_versions = self.repository.get_latest_versions(skill_ids)
        draft_skill_ids = self.repository.get_draft_skill_ids(skill_ids)
        source_update_skill_ids = self.repository.get_source_update_skill_ids(latest_versions)
        reads: list[SkillSummaryRead] = []
        for skill in skills:
            latest = latest_versions.get(skill.id)
            reads.append(
                SkillSummaryRead.model_validate(
                    {
                        **skill.model_dump(),
                        "version": latest.version if latest else None,
                        "has_draft": (
                            skill.id in draft_skill_ids
                            and (
                                skill.agent_id == agent_id
                                if agent_id is not None
                                else include_platform_drafts or skill.organization_id is not None
                            )
                        ),
                        "source_skill_id": latest.source_skill_id if latest else None,
                        "source_skill_version": latest.source_skill_version if latest else None,
                        "update_available": skill.id in source_update_skill_ids,
                    }
                )
            )
        return reads

from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.auth.models import CurrentUserContext
from api.domains.skills.models import (
    Skill,
    SkillCreate,
    SkillRead,
    SkillSource,
    SkillUpdate,
)
from api.domains.skills.repository import SkillRepository

_MAX_ZIP_BYTES = 50 * 1024 * 1024  # 50 MB


@inject
@singleton
@dataclass
class SkillService:
    repository: SkillRepository

    def _org_id(self, context: CurrentUserContext) -> UUID:
        return context.require_current_user_organization().organization_id

    def _get_or_404(self, skill_id: UUID, org_id: UUID) -> Skill:
        skill = self.repository.get_by_id(skill_id)
        if skill is None or (
                skill.organization_id is not None and skill.organization_id != org_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill {skill_id} not found",
            )
        return skill

    def create_skill(self, data: SkillCreate, context: CurrentUserContext) -> SkillRead:
        org_id = self._org_id(context)
        if len(data.zip_content) > _MAX_ZIP_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Zip content exceeds 50 MB limit",
            )
        skill = Skill(
            organization_id=org_id,
            name=data.name,
            source=SkillSource.CUSTOM,
            required_providers=data.required_providers,
            zip_content=data.zip_content,
        )
        self.repository.save(skill)
        return SkillRead.model_validate(skill)

    def update_skill(
            self, skill_id: UUID, data: SkillUpdate, context: CurrentUserContext
    ) -> SkillRead:
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        if skill.source == SkillSource.AAI_CLI:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot modify built-in skills",
            )
        updated = data.model_dump(exclude_unset=True)
        if "zip_content" in updated and updated["zip_content"] is not None:
            if len(updated["zip_content"]) > _MAX_ZIP_BYTES:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Zip content exceeds 50 MB limit",
                )
            skill.zip_content = updated["zip_content"]
        if "name" in updated:
            skill.name = updated["name"]
        if "required_providers" in updated:
            skill.required_providers = updated["required_providers"]
        self.repository.save(skill)
        return SkillRead.model_validate(skill)

    def delete_skill(self, skill_id: UUID, context: CurrentUserContext) -> None:
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
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
        self.repository.delete(skill)

    def get_skill(self, skill_id: UUID, context: CurrentUserContext) -> SkillRead:
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        return SkillRead.model_validate(skill)

    def list_skills(self, context: CurrentUserContext) -> list[SkillRead]:
        org_id = self._org_id(context)
        skills = self.repository.find_all_for_org(org_id)
        return [SkillRead.model_validate(s) for s in skills]

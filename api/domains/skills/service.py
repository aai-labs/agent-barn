import io
import zipfile
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.domains.skills.models import (
    Skill,
    SkillCreate,
    SkillFilter,
    SkillRead,
    SkillSource,
    SkillUpdate,
)
from api.domains.skills.repository import SkillRepository
from api.infrastructure.shared.models import PaginatedItems, Pagination

_MAX_ZIP_BYTES = 50 * 1024 * 1024  # 50 MB compressed
_MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024  # 200 MB total uncompressed
_MAX_SINGLE_FILE_BYTES = 100 * 1024 * 1024  # 100 MB per entry (actual read)
_MAX_COMPRESSION_RATIO = 100  # uncompressed / compressed
_MAX_ENTRIES = 1000


@inject
@singleton
@dataclass
class SkillService:
    repository: SkillRepository
    permission_policy: PermissionPolicy

    def _org_id(self, context: CurrentUserContext) -> UUID:
        return context.require_current_user_organization().organization_id

    @staticmethod
    def _validate_zip(content: bytes) -> None:
        if len(content) > _MAX_ZIP_BYTES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Zip content exceeds 50 MB limit",
            )
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as zf:
                entries = zf.infolist()

                if len(entries) > _MAX_ENTRIES:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Zip contains too many entries (max {_MAX_ENTRIES})",
                    )

                total_uncompressed = sum(e.file_size for e in entries)
                total_compressed = sum(e.compress_size for e in entries)

                if total_uncompressed > _MAX_UNCOMPRESSED_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Zip uncompressed content exceeds 200 MB limit",
                    )

                if total_compressed > 0 and total_uncompressed / total_compressed > _MAX_COMPRESSION_RATIO:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Zip compression ratio is suspiciously high (possible zip bomb)",
                    )

                total_extracted = 0
                for entry in entries:
                    if entry.flag_bits & 0x1:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Zip entry is encrypted: {entry.filename!r}",
                        )
                    name = entry.filename
                    if name.startswith(("/", "\\")):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Zip entry has an absolute path: {name!r}",
                        )
                    if ".." in name.replace("\\", "/").split("/"):
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Zip entry contains path traversal: {name!r}",
                        )
                    with zf.open(entry) as f:
                        extracted = 0
                        while chunk := f.read(65536):
                            extracted += len(chunk)
                            if extracted > _MAX_SINGLE_FILE_BYTES:
                                raise HTTPException(
                                    status_code=status.HTTP_400_BAD_REQUEST,
                                    detail=f"Entry {entry.filename!r} exceeds per-file size limit",
                                )
                            total_extracted += len(chunk)
                            if total_extracted > _MAX_UNCOMPRESSED_BYTES:
                                raise HTTPException(
                                    status_code=status.HTTP_400_BAD_REQUEST,
                                    detail="Zip uncompressed content exceeds 200 MB limit",
                                )
        except zipfile.BadZipFile:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Uploaded file is not a valid zip archive",
            )

    def _get_or_404(self, skill_id: UUID, org_id: UUID) -> Skill:
        skill = self.repository.get_by_id(skill_id)
        if skill is None or (skill.organization_id is not None and skill.organization_id != org_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Skill {skill_id} not found",
            )
        return skill

    def create_skill(self, data: SkillCreate, context: CurrentUserContext) -> SkillRead:
        org_id = self._org_id(context)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_MANAGE)
        self._validate_zip(data.zip_content)
        skill = Skill(
            organization_id=org_id,
            name=data.name,
            source=SkillSource.CUSTOM,
            required_providers=data.required_providers,
            zip_content=data.zip_content,
            tools_pointer=f'You can use "{data.name}" skill in the ./skills folder',
        )
        self.repository.save(skill)
        return SkillRead.model_validate(skill)

    def update_skill(self, skill_id: UUID, data: SkillUpdate, context: CurrentUserContext) -> SkillRead:
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_MANAGE)
        if skill.source == SkillSource.AAI_CLI:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Cannot modify built-in skills",
            )
        updated = data.model_dump(exclude_unset=True)
        if "zip_content" in updated and updated["zip_content"] is not None:
            self._validate_zip(updated["zip_content"])
            skill.zip_content = updated["zip_content"]
        if "name" in updated:
            skill.name = updated["name"]
            skill.tools_pointer = f'You can use "{skill.name}" skill in the ./skills folder'
        if "required_providers" in updated:
            skill.required_providers = updated["required_providers"]
        self.repository.save(skill)
        return SkillRead.model_validate(skill)

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
        blocking_templates = self.repository.get_latest_template_slugs_requiring_skill(skill_id, org_id)
        if blocking_templates:
            slugs = ", ".join(blocking_templates)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Skill is required by template(s): {slugs}. Remove it from those templates before deleting.",
            )
        self.repository.delete_stale_template_skill_refs(skill_id, org_id)
        self.repository.delete(skill)

    def get_skill(self, skill_id: UUID, context: CurrentUserContext) -> SkillRead:
        org_id = self._org_id(context)
        skill = self._get_or_404(skill_id, org_id)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_READ)
        return SkillRead.model_validate(skill)

    def list_skills(
        self,
        skill_filter: SkillFilter,
        pagination: Pagination,
        context: CurrentUserContext,
    ) -> PaginatedItems[SkillRead]:
        org_id = self._org_id(context)
        self.permission_policy.require_organization(context, org_id, PermissionKey.SKILL_READ)
        skills, total = self.repository.find_all_for_org(org_id, skill_filter, pagination)
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=[SkillRead.model_validate(s) for s in skills],
        )

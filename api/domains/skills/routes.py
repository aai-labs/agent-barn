from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user, require_platform_admin
from api.domains.skills.models import (
    SkillCreate,
    SkillDetailRead,
    SkillFilter,
    SkillSummaryRead,
    SkillUpdate,
    get_skill_filter,
)
from api.domains.skills.service import SkillService
from api.infrastructure.shared.models import PaginatedItems, Pagination

skills_router = APIRouter(prefix="/organizations/{organization_id}/skills", tags=["skills"])
platform_skills_router = APIRouter(prefix="/platform/skills", tags=["platform-skills"])


@platform_skills_router.get("", response_model=list[SkillSummaryRead])
def list_global_skills_for_platform_admin(
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.list_global_skills_for_platform_admin()


@skills_router.post("", response_model=SkillSummaryRead, status_code=status.HTTP_201_CREATED)
def create_skill(
    data: SkillCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.create_skill(data, context)


@skills_router.get("", response_model=PaginatedItems[SkillSummaryRead])
def list_skills(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
    skill_filter: Annotated[SkillFilter, Depends(get_skill_filter)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 15,
):
    return service.list_skills(
        skill_filter=skill_filter,
        pagination=Pagination(page=page, size=page_size),
        context=context,
    )


@skills_router.get("/{skill_id}", response_model=SkillSummaryRead)
def get_skill(
    skill_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.get_skill(skill_id, context)


@skills_router.get("/{skill_id}/files", response_model=SkillDetailRead)
def get_skill_files(
    skill_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    """The skill plus the file contents of its published version."""
    return service.get_skill_detail(skill_id, context)


@skills_router.patch("/{skill_id}", response_model=SkillSummaryRead)
def update_skill(
    skill_id: UUID,
    data: SkillUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.update_skill(skill_id, data, context)


@skills_router.delete("/{skill_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_skill(
    skill_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    service.delete_skill(skill_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

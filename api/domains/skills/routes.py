from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.skills.models import SkillCreate, SkillRead, SkillUpdate
from api.domains.skills.service import SkillService

skills_router = APIRouter(prefix="/skills", tags=["skills"])


@skills_router.post("", response_model=SkillRead, status_code=status.HTTP_201_CREATED)
def create_skill(
    data: SkillCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.create_skill(data, context)


@skills_router.get("", response_model=list[SkillRead])
def list_skills(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.list_skills(context)


@skills_router.get("/{skill_id}", response_model=SkillRead)
def get_skill(
    skill_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.get_skill(skill_id, context)


@skills_router.patch("/{skill_id}", response_model=SkillRead)
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

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user, require_platform_admin
from api.domains.skills.models import (
    SkillCreate,
    SkillDetailRead,
    SkillDraftRead,
    SkillDraftUpdate,
    SkillFilter,
    SkillSummaryRead,
    SkillUpdate,
    SkillVersionDetailRead,
    SkillVersionRead,
    get_skill_filter,
)
from api.domains.skills.service import SkillService
from api.infrastructure.shared.models import PaginatedItems, Pagination

skills_router = APIRouter(prefix="/organizations/{organization_id}/skills", tags=["skills"])
agent_skills_router = APIRouter(
    prefix="/organizations/{organization_id}/agents/{agent_id}/skills",
    tags=["agent-skills"],
)
platform_skills_router = APIRouter(prefix="/platform/skills", tags=["platform-skills"])


@agent_skills_router.get("", response_model=PaginatedItems[SkillSummaryRead])
def list_agent_skills(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
    skill_filter: Annotated[SkillFilter, Depends(get_skill_filter)],
    agent_id: UUID,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 15,
):
    return service.list_agent_skills(
        agent_id=agent_id,
        skill_filter=skill_filter,
        pagination=Pagination(page=page, size=page_size),
        context=context,
    )


@agent_skills_router.post("", response_model=SkillDetailRead, status_code=status.HTTP_201_CREATED)
def create_agent_skill(
    data: SkillCreate,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.create_agent_skill(agent_id, data, context)


@agent_skills_router.post("/{skill_id}/fork", response_model=SkillDetailRead, status_code=status.HTTP_201_CREATED)
def fork_agent_skill(
    skill_id: UUID,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.fork_agent_skill(agent_id, skill_id, context)


@agent_skills_router.patch("/{skill_id}", response_model=SkillSummaryRead)
def update_agent_skill(
    skill_id: UUID,
    data: SkillUpdate,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.update_agent_skill(agent_id, skill_id, data, context)


@agent_skills_router.get("/{skill_id}/files", response_model=SkillDetailRead)
def get_agent_skill_files(
    skill_id: UUID,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.get_agent_skill_detail(agent_id, skill_id, context)


@agent_skills_router.get("/{skill_id}/versions", response_model=list[SkillVersionRead])
def list_agent_skill_versions(
    skill_id: UUID,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.list_agent_skill_versions(agent_id, skill_id, context)


@agent_skills_router.delete("/{skill_id}/versions/{version}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_skill_version(
    skill_id: UUID,
    version: int,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    service.delete_agent_skill_version(agent_id, skill_id, version, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@agent_skills_router.get("/{skill_id}/versions/{version}", response_model=SkillVersionDetailRead)
def get_agent_skill_version(
    skill_id: UUID,
    version: int,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.get_agent_skill_version(agent_id, skill_id, version, context)


@agent_skills_router.get("/{skill_id}/draft", response_model=SkillDraftRead)
def get_agent_skill_draft(
    skill_id: UUID,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.get_agent_skill_draft(agent_id, skill_id, context)


@agent_skills_router.post("/{skill_id}/draft", response_model=SkillDraftRead, status_code=status.HTTP_201_CREATED)
def start_agent_skill_draft(
    skill_id: UUID,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.start_agent_skill_draft(agent_id, skill_id, context)


@agent_skills_router.patch("/{skill_id}/draft", response_model=SkillDraftRead)
def update_agent_skill_draft(
    skill_id: UUID,
    agent_id: UUID,
    data: SkillDraftUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.update_agent_skill_draft(agent_id, skill_id, data, context)


@agent_skills_router.delete("/{skill_id}/draft", status_code=status.HTTP_204_NO_CONTENT)
def discard_agent_skill_draft(
    skill_id: UUID,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    service.discard_agent_skill_draft(agent_id, skill_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@agent_skills_router.post(
    "/{skill_id}/draft/publish",
    response_model=SkillSummaryRead,
    status_code=status.HTTP_201_CREATED,
)
def publish_agent_skill_draft(
    skill_id: UUID,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.publish_agent_skill_draft(agent_id, skill_id, context)


@agent_skills_router.post("/{skill_id}/source-update", response_model=SkillDetailRead)
def apply_agent_skill_source_update(
    skill_id: UUID,
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.apply_agent_skill_source_update(agent_id, skill_id, context)


@platform_skills_router.get("", response_model=list[SkillSummaryRead])
def list_global_skills_for_platform_admin(
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.list_global_skills_for_platform_admin()


@platform_skills_router.post("", response_model=SkillDetailRead, status_code=status.HTTP_201_CREATED)
def create_platform_skill(
    data: SkillCreate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.create_platform_skill(data, context)


@platform_skills_router.patch("/{skill_id}", response_model=SkillSummaryRead)
def update_platform_skill(
    skill_id: UUID,
    data: SkillUpdate,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.update_platform_skill(skill_id, data)


@platform_skills_router.get("/{skill_id}/files", response_model=SkillDetailRead)
def get_platform_skill_files(
    skill_id: UUID,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.get_platform_skill_detail(skill_id)


@platform_skills_router.get("/{skill_id}/versions", response_model=list[SkillVersionRead])
def list_platform_skill_versions(
    skill_id: UUID,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.list_platform_skill_versions(skill_id)


@platform_skills_router.delete("/{skill_id}/versions/{version}", status_code=status.HTTP_204_NO_CONTENT)
def delete_platform_skill_version(
    skill_id: UUID,
    version: int,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    service.delete_platform_skill_version(skill_id, version)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@platform_skills_router.get("/{skill_id}/versions/{version}", response_model=SkillVersionDetailRead)
def get_platform_skill_version(
    skill_id: UUID,
    version: int,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.get_platform_skill_version(skill_id, version)


@platform_skills_router.get("/{skill_id}/draft", response_model=SkillDraftRead)
def get_platform_skill_draft(
    skill_id: UUID,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.get_platform_skill_draft(skill_id)


@platform_skills_router.post("/{skill_id}/draft", response_model=SkillDraftRead, status_code=status.HTTP_201_CREATED)
def start_platform_skill_draft(
    skill_id: UUID,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.start_platform_skill_draft(skill_id)


@platform_skills_router.patch("/{skill_id}/draft", response_model=SkillDraftRead)
def update_platform_skill_draft(
    skill_id: UUID,
    data: SkillDraftUpdate,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.update_platform_skill_draft(skill_id, data)


@platform_skills_router.delete("/{skill_id}/draft", status_code=status.HTTP_204_NO_CONTENT)
def discard_platform_skill_draft(
    skill_id: UUID,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    service.discard_platform_skill_draft(skill_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@platform_skills_router.post(
    "/{skill_id}/draft/publish",
    response_model=SkillSummaryRead,
    status_code=status.HTTP_201_CREATED,
)
def publish_platform_skill_draft(
    skill_id: UUID,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.publish_platform_skill_draft(skill_id, context)


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


@skills_router.post("/{skill_id}/source-update", response_model=SkillDetailRead)
def apply_source_update(
    skill_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.apply_source_update(skill_id, context)


@skills_router.patch("/{skill_id}", response_model=SkillSummaryRead)
def update_skill(
    skill_id: UUID,
    data: SkillUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.update_skill(skill_id, data, context)


@skills_router.post("/{skill_id}/fork", response_model=SkillDetailRead, status_code=status.HTTP_201_CREATED)
def fork_skill(
    skill_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    """Create an org-scoped custom skill seeded from a built-in's latest version,
    with an in-flight draft so the author lands directly in the editor."""
    return service.fork_skill(skill_id, context)


@skills_router.get("/{skill_id}/versions", response_model=list[SkillVersionRead])
def list_skill_versions(
    skill_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.list_skill_versions(skill_id, context)


@skills_router.get("/{skill_id}/versions/{version}", response_model=SkillVersionDetailRead)
def get_skill_version(
    skill_id: UUID,
    version: int,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.get_skill_version_detail(skill_id, version, context)


@skills_router.get("/{skill_id}/draft", response_model=SkillDraftRead)
def get_skill_draft(
    skill_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.get_skill_draft(skill_id, context)


@skills_router.post("/{skill_id}/draft", response_model=SkillDraftRead, status_code=status.HTTP_201_CREATED)
def start_skill_draft(
    skill_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    """Get-or-create the in-flight draft, seeded from the latest published version."""
    return service.start_skill_draft(skill_id, context)


@skills_router.patch("/{skill_id}/draft", response_model=SkillDraftRead)
def update_skill_draft(
    skill_id: UUID,
    data: SkillDraftUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.update_skill_draft(skill_id, data, context)


@skills_router.delete("/{skill_id}/draft", status_code=status.HTTP_204_NO_CONTENT)
def discard_skill_draft(
    skill_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    service.discard_skill_draft(skill_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@skills_router.post("/{skill_id}/draft/publish", response_model=SkillSummaryRead, status_code=status.HTTP_201_CREATED)
def publish_skill_draft(
    skill_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    return service.publish_skill_draft(skill_id, context)


@skills_router.delete("/{skill_id}/versions/{version}", status_code=status.HTTP_204_NO_CONTENT)
def delete_skill_version(
    skill_id: UUID,
    version: int,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SkillService, Injected(SkillService)],
):
    """Delete one immutable version from a skill's history. The currently published
    version is protected while any agent is assigned the skill; the last remaining
    version is never deletable."""
    service.delete_skill_version(skill_id, version, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

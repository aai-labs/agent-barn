from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.playbooks.models import (
    PlaybookExtractionCreate,
    PlaybookExtractionDetailRead,
    PlaybookExtractionFilter,
    PlaybookExtractionRead,
)
from api.domains.playbooks.service import PlaybookExtractionService
from api.infrastructure.shared.models import PaginatedItems, Pagination

agent_playbook_extractions_router = APIRouter(
    prefix="/organizations/{organization_id}/agents/{agent_id}/playbook-extractions", tags=["playbooks"]
)
playbook_extractions_router = APIRouter(
    prefix="/organizations/{organization_id}/playbook-extractions", tags=["playbooks"]
)


@agent_playbook_extractions_router.post("", response_model=PlaybookExtractionRead, status_code=status.HTTP_202_ACCEPTED)
def create_playbook_extraction(
    agent_id: UUID,
    payload: PlaybookExtractionCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[PlaybookExtractionService, Injected(PlaybookExtractionService)],
):
    return service.create(agent_id, payload, context)


@agent_playbook_extractions_router.get("", response_model=PaginatedItems[PlaybookExtractionRead])
def list_agent_playbook_extractions(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[PlaybookExtractionService, Injected(PlaybookExtractionService)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return service.list_for_agent(agent_id, Pagination(page=page, size=page_size), context)


@agent_playbook_extractions_router.get("/{extraction_id}", response_model=PlaybookExtractionDetailRead)
def get_playbook_extraction(
    agent_id: UUID,
    extraction_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[PlaybookExtractionService, Injected(PlaybookExtractionService)],
):
    return service.get(agent_id, extraction_id, context)


@agent_playbook_extractions_router.post("/{extraction_id}/cancel", response_model=PlaybookExtractionRead)
def cancel_playbook_extraction(
    agent_id: UUID,
    extraction_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[PlaybookExtractionService, Injected(PlaybookExtractionService)],
):
    return service.cancel(agent_id, extraction_id, context)


@playbook_extractions_router.get("", response_model=PaginatedItems[PlaybookExtractionRead])
def list_playbook_extractions(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[PlaybookExtractionService, Injected(PlaybookExtractionService)],
    skill_id: Annotated[UUID | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return service.list_for_organization(
        PlaybookExtractionFilter(skill_id=skill_id), Pagination(page=page, size=page_size), context
    )

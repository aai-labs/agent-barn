from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.personas.models import PersonaList, PersonaRead, PersonaVersionRead
from api.domains.personas.service import PersonaService

personas_router = APIRouter(
    prefix="/organizations/{organization_id}/agents/{agent_id}/personas",
    tags=["agent-personas"],
)


@personas_router.get("", response_model=PersonaList)
def list_agent_personas(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[PersonaService, Injected(PersonaService)],
):
    return service.list_personas(agent_id, context)


@personas_router.get("/{key}", response_model=PersonaRead)
def get_agent_persona(
    agent_id: UUID,
    key: str,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[PersonaService, Injected(PersonaService)],
):
    return service.get_persona(agent_id, key, context)


@personas_router.get("/{key}/versions", response_model=list[PersonaVersionRead])
def list_agent_persona_versions(
    agent_id: UUID,
    key: str,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[PersonaService, Injected(PersonaService)],
):
    return service.list_versions(agent_id, key, context)

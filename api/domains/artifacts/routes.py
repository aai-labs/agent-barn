from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi_injector import Injected
from starlette.concurrency import run_in_threadpool

from api.domains.artifacts.models import ArtifactCreate, ArtifactLinkRead, ArtifactRead
from api.domains.artifacts.service import ArtifactService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.infrastructure.shared.models import PaginatedItems

router = APIRouter(prefix="/organizations/{organization_id}/agents/{agent_id}/artifacts", tags=["artifacts"])
Context = Annotated[CurrentUserContext, Depends(get_current_user())]
Service = Annotated[ArtifactService, Injected(ArtifactService)]


async def file_body(request: Request, limit: int) -> bytes:
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > limit:
            raise HTTPException(413, "Artifact exceeds the configured file limit")
        content.extend(chunk)
    return bytes(content)


@router.post("", response_model=ArtifactRead, status_code=201)
def create_artifact(agent_id: UUID, payload: ArtifactCreate, context: Context, service: Service):
    return service.create(agent_id, service.scope(agent_id, context, True), payload, user_id=context.user.id)


@router.put("/{artifact_id}/content", response_model=ArtifactRead)
async def publish_artifact(agent_id: UUID, artifact_id: UUID, request: Request, context: Context, service: Service):
    scope = await run_in_threadpool(service.scope, agent_id, context, True)
    limit = await run_in_threadpool(service.upload_limit, artifact_id, agent_id, scope)
    content = await file_body(request, limit)
    return await run_in_threadpool(service.publish, artifact_id, agent_id, scope, content, human_context=context)


@router.get("", response_model=PaginatedItems[ArtifactRead])
def list_artifacts(
    agent_id: UUID,
    context: Context,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    run_id: UUID | None = None,
    step_id: UUID | None = None,
):
    return service.list_ready(agent_id, service.scope(agent_id, context), page, page_size, run_id, step_id)


@router.get("/{artifact_id}", response_model=ArtifactRead)
def get_artifact(agent_id: UUID, artifact_id: UUID, context: Context, service: Service):
    return service.ready(artifact_id, agent_id, service.scope(agent_id, context))


@router.get("/{artifact_id}/download-link", response_model=ArtifactLinkRead)
def artifact_download_link(
    agent_id: UUID, artifact_id: UUID, context: Context, service: Service, seconds: Annotated[int, Query(ge=1)] = 900
):
    return service.link(artifact_id, agent_id, service.scope(agent_id, context), seconds)


@router.delete("/{artifact_id}", status_code=204)
def delete_artifact(agent_id: UUID, artifact_id: UUID, context: Context, service: Service):
    service.delete(artifact_id, agent_id, context)
    return Response(status_code=204)

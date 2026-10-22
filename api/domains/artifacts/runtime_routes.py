from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.concurrency import run_in_threadpool

from api.domains.artifacts.models import ArtifactCreate
from api.domains.artifacts.routes import Service, file_body

router = APIRouter(prefix="/artifact-runtime/v1", include_in_schema=False)
Credential = Annotated[HTTPAuthorizationCredentials, Depends(HTTPBearer())]
AttemptToken = Annotated[str, Header(alias="X-Workflow-Token")]


@router.post("/artifacts", status_code=201)
def create_artifact(
    payload: ArtifactCreate,
    credential: Credential,
    service: Service,
    attempt_id: UUID | None = None,
    attempt_token: AttemptToken = "",
):
    agent_id, scope = service.runtime_scope(credential.credentials)
    return service.create(agent_id, scope, payload, attempt_id=attempt_id, attempt_token=attempt_token)


@router.put("/artifacts/{artifact_id}/content")
async def publish_artifact(
    artifact_id: UUID, request: Request, credential: Credential, service: Service, attempt_token: AttemptToken = ""
):
    agent_id, scope = await run_in_threadpool(service.runtime_scope, credential.credentials)
    content = await file_body(request, service.config.artifact_max_bytes)
    return await run_in_threadpool(
        service.publish,
        artifact_id,
        agent_id,
        scope,
        content,
        attempt_token=attempt_token,
        runtime_token=credential.credentials,
    )


@router.get("/artifacts")
def list_artifacts(
    credential: Credential,
    service: Service,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
):
    agent_id, scope = service.runtime_scope(credential.credentials)
    return service.list_ready(agent_id, scope, page, page_size)


@router.get("/artifacts/{artifact_id}/download-link")
def download_link(
    artifact_id: UUID, credential: Credential, service: Service, seconds: Annotated[int, Query(ge=1)] = 900
):
    agent_id, scope = service.runtime_scope(credential.credentials)
    return service.link(artifact_id, agent_id, scope, seconds)

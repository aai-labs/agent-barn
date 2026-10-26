import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi_injector import Injected
from pydantic import ValidationError

from api.domains.workflows.repository import WorkflowConflict
from api.domains.workflows.run_models import AttemptFailure, AttemptResult
from api.domains.workflows.run_service import WorkflowRunService
from api.domains.workflows.runtime_service import WorkflowRuntimeService

router = APIRouter(prefix="/workflow-runtime/v1/attempts/{attempt_id}", include_in_schema=False)
Runtime = Annotated[WorkflowRuntimeService, Injected(WorkflowRuntimeService)]
Runs = Annotated[WorkflowRunService, Injected(WorkflowRunService)]
Credential = Annotated[HTTPAuthorizationCredentials, Depends(HTTPBearer())]


async def bounded_body(request: Request) -> dict:
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 2_100_000:
            raise HTTPException(413, "Workflow request exceeds the size limit")
    try:
        body = json.loads(data)
    except (ValueError, UnicodeDecodeError) as exc:
        raise HTTPException(422, "Invalid JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(422, "Workflow request must be an object")
    return body


@router.get("/handoff")
def handoff(attempt_id: UUID, credential: Credential, service: Runtime):
    try:
        return service.handoff(attempt_id, credential.credentials)
    except WorkflowConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/result", status_code=204)
async def result(attempt_id: UUID, credential: Credential, service: Runs, request: Request):
    from starlette.concurrency import run_in_threadpool

    try:
        parsed = AttemptResult.model_validate(await bounded_body(request))
        await run_in_threadpool(service.result, attempt_id, credential.credentials, parsed)
    except ValidationError as exc:
        raise HTTPException(
            422,
            {
                "message": "Invalid workflow result envelope",
                "fields": [{"path": ".".join(map(str, error["loc"])), "type": error["type"]} for error in exc.errors()],
            },
        ) from exc
    except WorkflowConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(status_code=204)


@router.post("/failure", status_code=204)
async def failure(attempt_id: UUID, credential: Credential, service: Runs, request: Request):
    from starlette.concurrency import run_in_threadpool

    try:
        parsed = AttemptFailure.model_validate(await bounded_body(request))
        await run_in_threadpool(service.failure, attempt_id, credential.credentials, parsed)
    except ValidationError as exc:
        raise HTTPException(422, "Invalid workflow failure report") from exc
    except WorkflowConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    return Response(status_code=204)

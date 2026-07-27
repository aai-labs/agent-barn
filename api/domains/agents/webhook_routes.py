from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Request, Response
from fastapi_injector import Injected

from api.domains.agents.service import AgentService

webhook_router = APIRouter(prefix="/webhooks/teams", tags=["webhooks"])


@webhook_router.post("/{agent_id}/messages")
async def teams_webhook(
    agent_id: UUID,
    request: Request,
    service: Annotated[AgentService, Injected(AgentService)],
) -> Response:
    body = await request.body()
    headers = dict(request.headers)
    status_code, content, resp_headers = service.relay_teams_webhook(agent_id, body, headers)
    return Response(
        content=content,
        status_code=status_code,
        media_type=resp_headers.get("content-type", "application/json"),
    )

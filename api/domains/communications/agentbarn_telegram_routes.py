import json
import logging
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from fastapi_injector import Injected

from api.domains.communications.agentbarn_telegram_proxy import AgentBarnTelegramProxy
from api.infrastructure.telegram.client import RedactBotTokens

# The Telegram Bot API surface Agent runtimes on Agent Barn Telegram are pointed at.
agentbarn_telegram_router = APIRouter(prefix="/telegram", tags=["agentbarn-telegram"], include_in_schema=False)

# Each Agent's stand-in token travels in the request path, which the access log prints.
logging.getLogger("uvicorn.access").addFilter(RedactBotTokens())


@agentbarn_telegram_router.api_route("/{connection_id}/bot{token}/{method}", methods=["GET", "POST"])
async def telegram_bot_api(
    connection_id: UUID,
    token: str,
    method: str,
    request: Request,
    proxy: Annotated[AgentBarnTelegramProxy, Injected(AgentBarnTelegramProxy)],
) -> JSONResponse:
    body = await request.body()
    content_type = request.headers.get("content-type")
    params: dict[str, Any] = dict(request.query_params)
    if body and content_type and content_type.startswith("application/json"):
        try:
            parsed = json.loads(body)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            params.update(parsed)
    elif (
        body and content_type and content_type.startswith(("application/x-www-form-urlencoded", "multipart/form-data"))
    ):
        form = await request.form()
        params.update({key: value for key, value in form.multi_items() if isinstance(value, str)})
    if not body and params:
        # Telegram accepts parameters in the query string; forward them as JSON.
        body, content_type = json.dumps(params).encode(), "application/json"
    response = proxy.handle(connection_id, token, method, params=params, body=body, content_type=content_type)
    return JSONResponse(status_code=response.status_code, content=response.body)


@agentbarn_telegram_router.get("/{connection_id}/file/bot{token}/{file_path:path}")
def telegram_file(
    connection_id: UUID,
    token: str,
    file_path: str,
    proxy: Annotated[AgentBarnTelegramProxy, Injected(AgentBarnTelegramProxy)],
) -> Response:
    file = proxy.download(connection_id, token, file_path)
    return Response(status_code=file.status_code, content=file.content, media_type=file.content_type)

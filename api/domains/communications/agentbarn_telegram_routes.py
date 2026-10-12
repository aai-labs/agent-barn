import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from fastapi_injector import Injected

from api.domains.communications.agentbarn_telegram_proxy import (
    AgentBarnTelegramProxy,
    BadBotApiRequest,
    UploadedFile,
    parse_bot_api_request,
)
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
    content_type = request.headers.get("content-type")
    body = await request.body()
    form: list[tuple[str, str | UploadedFile]] | None = None
    if (content_type or "").split(";", 1)[0].strip().lower() == "multipart/form-data":
        form = []
        for key, value in (await request.form()).multi_items():
            if isinstance(value, str):
                form.append((key, value))
            else:
                upload = UploadedFile(key, value.filename or key, await value.read(), value.content_type)
                form.append((key, upload))
    try:
        parsed = parse_bot_api_request(request.query_params.multi_items(), content_type, body, form)
    except BadBotApiRequest as exc:
        return JSONResponse(
            status_code=400, content={"ok": False, "error_code": 400, "description": f"Bad Request: {exc}"}
        )
    # The proxy queries the database and waits on Telegram; off the event loop, one
    # slow call cannot stall other Agents' calls or the shared-bot poller.
    response = await run_in_threadpool(proxy.handle, connection_id, token, method, request=parsed)
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

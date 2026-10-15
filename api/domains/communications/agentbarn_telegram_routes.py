import logging
from collections.abc import AsyncGenerator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, Response
from fastapi_injector import Injected
from starlette.formparsers import MultiPartException, MultiPartParser

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

# Telegram takes uploads of up to 50 MB; the rest is room for the other fields.
_MAX_UPLOAD_BYTES = 51 * 1024 * 1024
# Every other call is a few kilobytes of parameters.
_MAX_BODY_BYTES = 1024 * 1024


class _TooLarge(Exception):
    pass


async def _limited(request: Request, limit: int) -> AsyncGenerator[bytes]:
    """The request body as it arrives, stopping once it exceeds ``limit``, with or without a Content-Length."""
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise _TooLarge
    received = 0
    async for chunk in request.stream():
        received += len(chunk)
        if received > limit:
            raise _TooLarge
        yield chunk


def _bad_request(status_code: int, description: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code, content={"ok": False, "error_code": status_code, "description": description}
    )


@agentbarn_telegram_router.api_route("/{connection_id}/bot{token}/{method}", methods=["GET", "POST"])
async def telegram_bot_api(
    connection_id: UUID,
    token: str,
    method: str,
    request: Request,
    proxy: Annotated[AgentBarnTelegramProxy, Injected(AgentBarnTelegramProxy)],
) -> JSONResponse:
    # The proxy queries the database and waits on Telegram; off the event loop, one
    # slow call cannot stall other Agents' calls or the shared-bot poller.
    caller = await run_in_threadpool(proxy.authenticate, connection_id, token)
    if caller is None:
        # Refused before the body is read, so an unauthenticated caller costs no memory.
        return _bad_request(401, "Unauthorized")
    content_type = request.headers.get("content-type")
    multipart = (content_type or "").split(";", 1)[0].strip().lower() == "multipart/form-data"
    body = b""
    form: list[tuple[str, str | UploadedFile]] | None = None
    try:
        if multipart:
            form = []
            parsed_form = await MultiPartParser(request.headers, _limited(request, _MAX_UPLOAD_BYTES)).parse()
            for key, value in parsed_form.multi_items():
                if isinstance(value, str):
                    form.append((key, value))
                else:
                    upload = UploadedFile(key, value.filename or key, await value.read(), value.content_type)
                    form.append((key, upload))
            await parsed_form.close()
        else:
            body = b"".join([chunk async for chunk in _limited(request, _MAX_BODY_BYTES)])
        parsed = parse_bot_api_request(request.query_params.multi_items(), content_type, body, form)
    except _TooLarge:
        return _bad_request(413, "Request Entity Too Large")
    except MultiPartException as exc:
        return _bad_request(400, f"Bad Request: {exc.message}")
    except BadBotApiRequest as exc:
        return _bad_request(400, f"Bad Request: {exc}")
    response = await run_in_threadpool(proxy.handle, caller, method, request=parsed)
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

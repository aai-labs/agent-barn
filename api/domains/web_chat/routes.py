from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.routes import get_current_user
from api.domains.web_chat.models import (
    MAIN_THREAD_ID,
    WebChatMessageCreate,
    WebChatMessageRead,
    WebChatThreadRead,
)
from api.domains.web_chat.service import WebChatService

web_chat_router = APIRouter(prefix="/organizations/{organization_id}/agents", tags=["web-chat"])


@web_chat_router.get(
    "/{agent_id}/web-chat/threads",
    response_model=list[WebChatThreadRead],
)
def list_web_chat_threads(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[WebChatService, Injected(WebChatService)],
) -> list[WebChatThreadRead]:
    return service.list_threads(agent_id, context)


@web_chat_router.get(
    "/{agent_id}/web-chat/messages",
    response_model=list[WebChatMessageRead],
)
def list_web_chat_messages(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[WebChatService, Injected(WebChatService)],
    thread_id: Annotated[str, Query(min_length=1, max_length=128)] = MAIN_THREAD_ID,
    after_id: Annotated[UUID | None, Query()] = None,
) -> list[WebChatMessageRead]:
    return service.list_messages(agent_id, context, thread_id, after_id=after_id)


@web_chat_router.post(
    "/{agent_id}/web-chat/messages",
    status_code=status.HTTP_202_ACCEPTED,
)
def send_web_chat_message(
    agent_id: UUID,
    data: WebChatMessageCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[WebChatService, Injected(WebChatService)],
) -> None:
    service.send_message(agent_id, data.text, data.thread_id, context)


@web_chat_router.get("/{agent_id}/web-chat/stream")
def stream_web_chat_messages(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[WebChatService, Injected(WebChatService)],
    thread_id: Annotated[str, Query(min_length=1, max_length=128)] = MAIN_THREAD_ID,
) -> StreamingResponse:
    return StreamingResponse(
        service.stream_updates(agent_id, context, thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

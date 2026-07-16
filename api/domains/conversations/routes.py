from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.routes import get_current_user
from api.domains.conversations.models import (
    ConversationChannelRead,
    ConversationThreadsPage,
    ConversationsCursor,
    ConversationsFilter,
)
from api.domains.conversations.service import ConversationService

conversations_router = APIRouter(prefix="/agents", tags=["conversations"])


def get_conversations_filter(
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
) -> ConversationsFilter:
    return ConversationsFilter(from_date=from_date, to_date=to_date)


def get_conversations_cursor(
    before_occurred_at: datetime | None = Query(default=None),
    before_id: UUID | None = Query(default=None),
) -> ConversationsCursor:
    return ConversationsCursor(
        before_occurred_at=before_occurred_at, before_id=before_id
    )


@conversations_router.get(
    "/{agent_id}/conversations/channels",
    response_model=list[ConversationChannelRead],
)
def list_channels(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[ConversationService, Injected(ConversationService)],
) -> list[ConversationChannelRead]:
    org_id = context.require_current_user_organization().organization_id
    # agent.conversations_view is recorded inside the service, where the agent is in hand.
    return service.list_channels(agent_id, org_id, context)


@conversations_router.get(
    "/{agent_id}/conversations/channels/{channel_id}/messages",
    response_model=ConversationThreadsPage,
)
def list_channel_messages(
    agent_id: UUID,
    channel_id: str,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[ConversationService, Injected(ConversationService)],
    filter: Annotated[ConversationsFilter, Depends(get_conversations_filter)],
    cursor: Annotated[ConversationsCursor, Depends(get_conversations_cursor)],
    page_size: int = Query(default=6, ge=1, le=100),
) -> ConversationThreadsPage:
    org_id = context.require_current_user_organization().organization_id
    # agent.conversations_view is recorded inside the service, where the agent is in hand.
    return service.list_threads(
        agent_id=agent_id,
        org_id=org_id,
        channel_id=channel_id,
        filter=filter,
        cursor=cursor,
        page_size=page_size,
        context=context,
    )

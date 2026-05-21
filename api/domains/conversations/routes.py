from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.routes import get_current_user
from api.domains.conversations.models import ConversationsRead
from api.domains.conversations.service import ConversationService

conversations_router = APIRouter(prefix="/agents", tags=["conversations"])


@conversations_router.get("/{agent_id}/conversations", response_model=ConversationsRead)
def get_conversations(
    agent_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[ConversationService, Injected(ConversationService)],
) -> ConversationsRead:
    org_id = context.require_current_user_organization().organization_id
    return service.get_conversations(agent_id, org_id)

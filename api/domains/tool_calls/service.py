from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.tool_calls.models import ToolCallFilter, ToolCallRead
from api.domains.tool_calls.repository import ToolCallRepository
from api.infrastructure.shared.models import PaginatedItems, Pagination


@inject
@singleton
@dataclass
class ToolCallService:
    repository: ToolCallRepository
    agent_authorization: AgentAuthorization

    def list_tool_calls(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        tool_call_filter: ToolCallFilter,
        pagination: Pagination,
    ) -> PaginatedItems[ToolCallRead]:
        agent = self.agent_authorization.require_visible(context, agent_id)
        activity_scope = self.agent_authorization.require_action_for_visible(
            context, agent, PermissionKey.ACTIVITY_READ
        )
        return self.repository.find_by_agent(
            agent_id, tool_call_filter, pagination, activity_scope
        )

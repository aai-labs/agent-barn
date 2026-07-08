from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.tool_calls.models import ToolCallFilter, ToolCallRead
from api.domains.tool_calls.repository import ToolCallRepository
from api.infrastructure.shared.models import PaginatedItems, Pagination


@inject
@singleton
@dataclass
class ToolCallService:
    repository: ToolCallRepository

    def list_tool_calls(
        self,
        agent_id: UUID,
        org_id: UUID,
        tool_call_filter: ToolCallFilter,
        pagination: Pagination,
    ) -> PaginatedItems[ToolCallRead]:
        return self.repository.find_by_agent(agent_id, tool_call_filter, pagination)

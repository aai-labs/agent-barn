from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.tool_calls.models import ToolCallFilter, ToolCallRead
from api.domains.tool_calls.repository import ToolCallRepository
from api.domains.tool_calls.sync_service import ToolCallSyncService
from api.infrastructure.shared.models import PaginatedItems, Pagination


@inject
@singleton
@dataclass
class ToolCallService:
    sync_service: ToolCallSyncService
    repository: ToolCallRepository

    def list_tool_calls(
        self,
        agent_id: UUID,
        org_id: UUID,
        tool_call_filter: ToolCallFilter,
        pagination: Pagination,
    ) -> PaginatedItems[ToolCallRead]:
        self.sync_service.sync_agent(agent_id, org_id)
        return self.repository.find_by_agent(agent_id, tool_call_filter, pagination)

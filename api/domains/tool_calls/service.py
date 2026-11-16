from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.tool_calls.models import HourlyToolActivity, StoredToolCall, ToolCallFilter, ToolCallRead
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
        return self.repository.find_by_agent(agent_id, tool_call_filter, pagination, activity_scope)

    def hourly_tool_activity(self, agent_id: UUID, since: datetime, until: datetime) -> list[HourlyToolActivity]:
        """An Agent's tool calls and errors per UTC hour, for the scheduled anomaly check.

        Background work: no caller and no authorization scope, and no router reaches it.
        """
        return self.repository.hourly_activity(agent_id, since, until)

    def tool_calls_stored_between(
        self,
        agent_id: UUID,
        *,
        after: datetime | None,
        until: datetime,
        argument_keys: tuple[str, ...],
        occurred_since: datetime | None = None,
    ) -> list[StoredToolCall]:
        """An Agent's tool calls stored after a cursor, with only the argument keys asked
        for, for the scheduled anomaly check. Background work, like `hourly_tool_activity`.
        """
        return self.repository.stored_between(
            agent_id, after=after, until=until, argument_keys=argument_keys, occurred_since=occurred_since
        )

    def platform_daily_active_agent_ids(
        self, window_start: datetime, window_end: datetime, **kwargs
    ) -> dict[datetime, set[UUID]]:
        """{iso_date: {agent_id}} for Agents that ran a tool (AF-256).

        No CurrentUserContext and no authorization scope: Platform Privilege is
        enforced at the platform route, and no Active Organization exists to
        scope against. `list_tool_calls` above keeps going through
        AgentAuthorization as usual.
        """
        return self.repository.daily_active_agent_ids_since(window_start, window_end, **kwargs)

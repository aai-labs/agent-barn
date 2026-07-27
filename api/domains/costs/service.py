from api.domains.costs.models import AgentModelBreakdown
import datetime
import hashlib
import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.costs.models import (
    AgentCostRead,
    CostByModelRead,
    CostTimeSeriesPoint,
    OrgCostSummaryRead,
)
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.litellm.client import LiteLLMClient

logger = logging.getLogger(__name__)

# Default look-back window — used when no explicit date range is provided.
_SPEND_LOOKBACK_DAYS = 365


@inject
@singleton
@dataclass
class CostService:
    agent_repository: AgentRepository
    agent_authorization: AgentAuthorization
    permission_policy: PermissionPolicy
    litellm: LiteLLMClient
    config: Config

    def _org_id(self, context: CurrentUserContext) -> UUID:
        return context.require_current_user_organization().organization_id

    def _decrypt_key(self, encrypted: str) -> str:
        return decrypt_token(encrypted, self.config.agent_token_encryption_key)

    def _date_range(self, days: int = _SPEND_LOOKBACK_DAYS) -> tuple[str, str]:
        end = datetime.date.today()
        start = end - datetime.timedelta(days=days)
        return start.isoformat(), end.isoformat()

    def _build_agent_cost_read_from_info(self, agent: Agent, details: dict) -> AgentCostRead:
        spend = float(details.get("spend", 0.0))
        prompt_tokens = int(details.get("total_input_tokens", 0) or 0)
        completion_tokens = int(details.get("total_output_tokens", 0) or 0)
        total_tokens = prompt_tokens + completion_tokens

        # build per-model breakdown
        models_breakdown = []
        for model_name, m in details.get("models", {}).items():
            models_breakdown.append(
                AgentModelBreakdown(
                    model=model_name,
                    total_cost=float(m.get("spend", 0.0)),
                    prompt_tokens=int(m.get("prompt_tokens", 0)),
                    completion_tokens=int(m.get("completion_tokens", 0)),
                )
            )

        if getattr(agent, "deleted_at", None) is not None:
            mapped_status = "deleted"
        else:
            status_map = {"RUNNING": "active", "STOPPED": "stopped", "ERROR": "error"}
            mapped_status = status_map.get(agent.status.value, "unknown") if hasattr(agent, "status") else "unknown"
        return AgentCostRead(
            agent_id=agent.id,
            agent_name=agent.name,
            model=agent.model,
            status=mapped_status,
            total_cost=spend,
            total_tokens=total_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            models_breakdown=models_breakdown,
        )

    def get_org_cost_summary(
        self,
        context: CurrentUserContext,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> OrgCostSummaryRead:
        org_id = self._org_id(context)
        self.permission_policy.require_organization(
            context,
            org_id,
            PermissionKey.COST_READ,
            detail="You don't have permission to view organization costs.",
        )
        if start_date and end_date:
            start_str, end_str = start_date, end_date
        else:
            start_str, end_str = self._date_range()

        agent_costs: list[AgentCostRead] = []
        total_cost = 0.0
        by_model: dict[str, float] = {}
        daily_costs: dict[str, float] = {}

        # --- Cost data for all agents: live and deleted ---
        all_agents = self.agent_repository.find_all_for_org(org_id)
        global_spend = self.litellm.get_global_spend_report(start_str, end_str)

        for agent in all_agents:
            if not agent.litellm_key_encrypted:
                continue

            try:
                key = self._decrypt_key(agent.litellm_key_encrypted)
                key_hash = hashlib.sha256(key.encode()).hexdigest()
                details = global_spend.get(key_hash, {})
            except Exception as exc:
                logger.warning("Failed to fetch spend details for agent %s: %s", agent.id, exc)
                details = {}

            spend = float(details.get("spend", 0.0))

            cost_read = self._build_agent_cost_read_from_info(agent, details)
            agent_costs.append(cost_read)
            total_cost += spend

            # Extract the actual models used from the LiteLLM details dictionary
            models_dict = details.get("models", {})

            if models_dict:
                # If we have a breakdown, distribute the spend to the actual models used
                for actual_model_name, m_data in models_dict.items():
                    m_spend = float(m_data.get("spend", 0.0))
                    short_model = actual_model_name.split("/")[-1]
                    by_model[short_model] = by_model.get(short_model, 0.0) + m_spend
            else:
                # Fallback: if there is spend but no model breakdown data is available yet
                model_key = agent.model or "unknown"
                short_model = model_key.split("/")[-1]
                by_model[short_model] = by_model.get(short_model, 0.0) + spend

            agent_daily = details.get("daily_spend", {})
            for date_str, row_spend in agent_daily.items():
                if len(date_str) == 10:
                    daily_costs[date_str] = daily_costs.get(date_str, 0.0) + row_spend

        time_series = [CostTimeSeriesPoint(date=d, cost=c) for d, c in sorted(daily_costs.items())]
        by_model_list = [CostByModelRead(model=m, total_cost=c) for m, c in by_model.items()]

        return OrgCostSummaryRead(
            totalCost=total_cost,
            agents=agent_costs,
            byModel=by_model_list,
            timeSeries=time_series,
        )

    def get_agent_cost(self, agent_id: UUID, context: CurrentUserContext) -> AgentCostRead:
        try:
            agent = self.agent_authorization.require_action(context, agent_id, PermissionKey.COST_READ)
        except HTTPException as exc:
            if exc.status_code != status.HTTP_404_NOT_FOUND:
                raise
            # Implicit Organization Owner/Admin authority retains historical spend
            # access after soft deletion. Explicit Agent assignments never do.
            cost_scope = self.agent_authorization.require_collection_scope(
                context,
                PermissionKey.COST_READ,
            )
            agent = self.agent_repository.get_deleted_in_scope(agent_id, cost_scope)
            if agent is None:
                raise

        if not agent.litellm_key_encrypted:
            return AgentCostRead(
                agent_id=agent.id,
                agent_name=agent.name,
                model=agent.model,
                status="stopped",
                total_cost=0.0,
                total_tokens=0,
                prompt_tokens=0,
                completion_tokens=0,
            )

        start_str, end_str = self._date_range(days=365)
        key = self._decrypt_key(agent.litellm_key_encrypted)
        try:
            info = self.litellm.get_key_info(key)
        except Exception as exc:
            logger.warning("Failed to fetch key info for agent %s: %s", agent.id, exc)
            info = {}
        return self._build_agent_cost_read_from_info(agent, info)

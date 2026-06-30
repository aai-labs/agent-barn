from api.domains.costs.models import AgentModelBreakdown
import datetime
import logging
from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.models import Agent
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.costs.models import (
    AgentCostRead,
    AgentCostSnapshot,
    CostByModelRead,
    CostTimeSeriesPoint,
    OrgCostSummaryRead,
)
from api.domains.costs.repository import CostRepository
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.litellm.client import LiteLLMClient

logger = logging.getLogger(__name__)

# Default look-back window — used when no explicit date range is provided.
_SPEND_LOOKBACK_DAYS = 365


@inject
@singleton
@dataclass
class CostService:
    repository: CostRepository
    agent_repository: AgentRepository
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

    def _build_agent_cost_read_from_info(
        self, agent: Agent, details: dict
    ) -> AgentCostRead:
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

        status_map = {"RUNNING": "active", "STOPPED": "stopped", "ERROR": "error"}
        mapped_status = (
            status_map.get(agent.status.value, "unknown")
            if hasattr(agent, "status")
            else "unknown"
        )
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
        if start_date and end_date:
            start_str, end_str = start_date, end_date
        else:
            start_str, end_str = self._date_range()

        agent_costs: list[AgentCostRead] = []
        total_cost = 0.0
        by_model: dict[str, float] = {}
        daily_costs: dict[str, float] = {}

        # --- Live data from active agents ---
        active_agents = self.agent_repository.find_all_active_for_org(org_id)
        active_agent_ids: set[UUID] = set()

        import hashlib

        global_spend = self.litellm.get_global_spend_report(start_str, end_str)

        for agent in active_agents:
            active_agent_ids.add(agent.id)
            if not agent.litellm_key_encrypted:
                continue

            try:
                key = self._decrypt_key(agent.litellm_key_encrypted)
                key_hash = hashlib.sha256(key.encode()).hexdigest()
                details = global_spend.get(key_hash, {})
            except Exception as exc:
                logger.warning(
                    "Failed to fetch spend details for agent %s: %s", agent.id, exc
                )
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
                    by_model[actual_model_name] = (
                        by_model.get(actual_model_name, 0.0) + m_spend
                    )
            else:
                # Fallback: if there is spend but no model breakdown data is available yet
                model_key = agent.model or "unknown"
                by_model[model_key] = by_model.get(model_key, 0.0) + spend

            agent_daily = details.get("daily_spend", {})
            for date_str, row_spend in agent_daily.items():
                if len(date_str) == 10:
                    daily_costs[date_str] = daily_costs.get(date_str, 0.0) + row_spend

        # --- Historical snapshots for deleted agents ---
        snapshots = self.repository.find_snapshots_for_org(org_id)
        seen_deleted: set[UUID] = set()
        for snap in snapshots:
            if snap.agent_id in active_agent_ids or snap.agent_id in seen_deleted:
                continue
            seen_deleted.add(snap.agent_id)

            # Reconstruct models breakdown from snapshot
            models_breakdown = [
                AgentModelBreakdown(
                    model=m["model"],
                    total_cost=float(m.get("spend", 0.0)),
                    prompt_tokens=int(m.get("prompt_tokens", 0)),
                    completion_tokens=int(m.get("completion_tokens", 0)),
                )
                for m in snap.get_models_breakdown()
            ]

            agent_costs.append(
                AgentCostRead(
                    agent_id=snap.agent_id,
                    agent_name=snap.agent_name,
                    model=snap.model,
                    status="deleted",
                    total_cost=snap.total_cost,
                    total_tokens=snap.total_tokens,
                    prompt_tokens=snap.prompt_tokens,
                    completion_tokens=snap.completion_tokens,
                    models_breakdown=models_breakdown,
                )
            )
            total_cost += snap.total_cost
            by_model[snap.model] = by_model.get(snap.model, 0.0) + snap.total_cost

        time_series = [
            CostTimeSeriesPoint(date=d, cost=c) for d, c in sorted(daily_costs.items())
        ]
        by_model_list = [
            CostByModelRead(model=m, total_cost=c) for m, c in by_model.items()
        ]

        return OrgCostSummaryRead(
            totalCost=total_cost,
            agents=agent_costs,
            byModel=by_model_list,
            timeSeries=time_series,
        )

    def get_agent_cost(
        self, agent_id: UUID, context: CurrentUserContext
    ) -> AgentCostRead:
        org_id = self._org_id(context)
        agent = self.agent_repository.get_active(agent_id, org_id)
        if not agent:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Agent {agent_id} not found",
            )

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

    def snapshot_agent_cost(self, agent: Agent, org_id: UUID, key: str) -> None:
        """Persist a cost snapshot before the agent is deleted."""
        import hashlib
        import json

        start_str, end_str = self._date_range(days=365)
        try:
            spend = self.litellm.get_key_spend(key)
            logs = self.litellm.get_spend_logs(key, start_str, end_str)
            # Also grab the full spend report for model breakdown
            key_hash = hashlib.sha256(key.encode()).hexdigest()
            global_spend = self.litellm.get_global_spend_report(start_str, end_str)
            details = global_spend.get(key_hash, {})
        except Exception as exc:
            logger.warning("Failed to snapshot cost for agent %s: %s", agent.id, exc)
            spend, logs, details = 0.0, [], {}

        prompt_tokens = sum(int(row.get("prompt_tokens") or 0) for row in logs)
        completion_tokens = sum(int(row.get("completion_tokens") or 0) for row in logs)

        models_breakdown_json = json.dumps(
            [
                {
                    "model": model_name,
                    "spend": float(m.get("spend", 0.0)),
                    "prompt_tokens": int(m.get("prompt_tokens", 0)),
                    "completion_tokens": int(m.get("completion_tokens", 0)),
                }
                for model_name, m in details.get("models", {}).items()
            ]
        )

        snapshot = AgentCostSnapshot(
            agent_id=agent.id,
            agent_name=agent.name,
            organization_id=org_id,
            model=agent.model,
            total_cost=spend,
            total_tokens=prompt_tokens + completion_tokens,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            snapshotted_at=datetime.datetime.now(datetime.timezone.utc),
            models_breakdown_json=models_breakdown_json,
        )
        self.repository.save_snapshot(snapshot)

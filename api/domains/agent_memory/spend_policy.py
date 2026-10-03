"""Gate model-producing memory operations against observed Organization spend."""

import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.costs.repository import CostRepository
from api.domains.organizations.repository import OrganizationRepository

# Existing schedules: runtime snapshot every 5 minutes, cost sync every 15.
MAX_RUNTIME_SNAPSHOT_AGE = timedelta(minutes=10)
MAX_COST_SYNC_AGE = timedelta(minutes=20)
_DURATION = re.compile(r"^([1-9][0-9]*)([smhd])$")
_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


@inject
@singleton
@dataclass
class MemorySpendPolicy:
    organizations: OrganizationRepository
    costs: CostRepository
    config: Config

    def require_available(self, organization_id: UUID) -> None:
        organization = self.organizations.get(organization_id)
        if organization is None:
            raise HTTPException(401, "Invalid Agent Memory credential.")
        limit = organization.llm_budget_usd
        if limit is None:
            return
        if limit == 0:
            raise HTTPException(429, "Organization model spend limit reached.")
        now = datetime.now(UTC)
        observed = organization.llm_spend_observed_at
        renewal = organization.llm_budget_renews_at
        runtime_spend = organization.llm_spend_usd
        synced = self.costs.last_sync_completed_at()
        duration = _DURATION.fullmatch(organization.llm_budget_duration or "")
        if (
            not self.config.memory_cost_key_hashes
            or observed is None
            or renewal is None
            or synced is None
            or runtime_spend is None
            or not math.isfinite(runtime_spend)
            or runtime_spend < 0
            or not math.isfinite(limit)
            or limit < 0
            or not duration
            or not timedelta(0) <= now - _utc(observed) <= MAX_RUNTIME_SNAPSHOT_AGE
            or not timedelta(0) <= now - _utc(synced) <= MAX_COST_SYNC_AGE
            or _utc(renewal) <= now
        ):
            raise HTTPException(503, "Organization memory spend status is unavailable; try again later.")
        try:
            window = timedelta(seconds=int(duration.group(1)) * _SECONDS[duration.group(2)])
            start = _utc(renewal) - window
        except OverflowError, ValueError:
            raise HTTPException(503, "Organization memory spend status is unavailable; try again later.") from None
        # A policy update may leave an old renewal snapshot until the next refresh.
        if start > now:
            raise HTTPException(503, "Organization memory spend status is unavailable; try again later.")
        memory_spend = self.costs.memory_spend(organization_id, start, now)
        if Decimal(str(runtime_spend)) + memory_spend >= Decimal(str(limit)):
            raise HTTPException(429, "Organization model spend limit reached.")

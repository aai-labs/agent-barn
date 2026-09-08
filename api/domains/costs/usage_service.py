"""Attribution of Honcho's memory spend.

Honcho sends every model call to LiteLLM on one service credential and carries no
workspace identity on the request, so LiteLLM reports a single undifferentiated
figure for all memory work. Its telemetry does name the workspace and count
tokens, and a workspace is one Agent, so those shares divide the real total.
"""

import datetime
import hashlib
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.costs.models import HonchoUsageEvent
from api.domains.costs.repository import HonchoUsageRepository
from api.infrastructure.litellm.client import LiteLLMClient

# Honcho emits one CloudEvent per model call. Only these two carry token counts.
_HONCHO_USAGE_EVENT_TYPES = frozenset({"llm.call.completed", "embedding.call.completed"})


@inject
@singleton
@dataclass
class HonchoUsageService:
    """Records Honcho's per-call telemetry, and divides its spend by token share.

    Honcho sends every model call on one service credential with no workspace
    identity, so LiteLLM sees an undifferentiated stream and cannot split it.
    Its telemetry does name the workspace and count tokens, and those token
    shares are what divide LiteLLM's authoritative total for Honcho's key.
    """

    repository: HonchoUsageRepository
    litellm: LiteLLMClient
    config: Config

    def record_cloud_events(self, payload: object) -> int:
        """Store the usage-bearing events in a CloudEvents batch.

        Takes the raw decoded body rather than a typed argument so the meaning of
        a Honcho usage event stays inside this domain. Unknown event types are
        skipped rather than rejected: Honcho emits many kinds on the same stream,
        and a new one must not fail the batch that carries real usage.
        """
        events = payload if isinstance(payload, list) else [payload]
        rows: list[HonchoUsageEvent] = []
        for event in events:
            row = self._to_row(event)
            if row is not None:
                rows.append(row)
        return self.repository.record(rows)

    def _to_row(self, event: object) -> HonchoUsageEvent | None:
        if not isinstance(event, dict):
            return None
        event_type = event.get("type")
        if event_type not in _HONCHO_USAGE_EVENT_TYPES:
            return None
        data = event.get("data")
        if not isinstance(data, dict):
            return None
        workspace_name = data.get("workspace_name")
        event_id = event.get("id")
        # System calls carry no workspace and cannot be attributed to anything, so
        # they are dropped rather than pooled into a bucket nobody owns.
        if not workspace_name or not event_id:
            return None
        return HonchoUsageEvent(
            event_id=str(event_id),
            workspace_name=str(workspace_name),
            event_type=str(event_type),
            model=str(data.get("model") or "unknown"),
            call_purpose=_as_optional_str(data.get("call_purpose")),
            input_tokens=_as_int(data.get("provider_input_tokens")),
            output_tokens=_as_int(data.get("provider_output_tokens")),
            occurred_at=_parse_timestamp(event.get("time") or data.get("timestamp")),
        )

    def memory_cost_by_agent(self, start_date: str, end_date: str) -> dict[UUID, float]:
        """Divide Honcho's LiteLLM spend across Agents by measured token share.

        Honcho holds one credential for the whole fleet, so LiteLLM reports a
        single figure for all memory work. Its telemetry counts tokens per
        workspace, and a workspace is one Agent, so the split is measured rather
        than apportioned by a proxy. The shares always reconcile to the real
        total because the total is the one LiteLLM computed.
        """
        if not self.config.honcho_litellm_key:
            return {}

        totals = self.repository.token_totals_by_workspace(
            _start_of_day(start_date),
            # The caller's end date is a calendar day, not an instant. Parsing it
            # bare gives midnight, which excludes everything that happened during
            # that day — including all of today's usage on any live system.
            _end_of_day(end_date),
        )
        grand_total = sum(total.total_tokens for total in totals)
        if grand_total <= 0:
            return {}

        key_hash = hashlib.sha256(self.config.honcho_litellm_key.encode()).hexdigest()
        spend_report = self.litellm.get_global_spend_report(start_date, end_date)
        honcho_spend = float(spend_report.get(key_hash, {}).get("spend", 0.0))
        if honcho_spend <= 0:
            return {}

        costs: dict[UUID, float] = {}
        for total in totals:
            agent_id = _agent_id_from_workspace(total.workspace_name)
            # Usage from a workspace that is not an Agent's still counts toward the
            # denominator: dropping it would inflate every Agent's share of a bill
            # they did not incur alone.
            if agent_id is None:
                continue
            costs[agent_id] = costs.get(agent_id, 0.0) + honcho_spend * (total.total_tokens / grand_total)
        return costs


def _start_of_day(value: str) -> datetime.datetime:
    return datetime.datetime.fromisoformat(value).replace(tzinfo=datetime.UTC)


def _end_of_day(value: str) -> datetime.datetime:
    parsed = datetime.datetime.fromisoformat(value)
    return (parsed + datetime.timedelta(days=1)).replace(tzinfo=datetime.UTC)


def _agent_id_from_workspace(workspace_name: str) -> UUID | None:
    if not workspace_name.startswith("af-"):
        return None
    try:
        return UUID(workspace_name.removeprefix("af-"))
    except ValueError:
        return None


def _as_optional_str(value: object) -> str | None:
    return str(value) if value else None


def _as_int(value: object) -> int:
    """Coerce a telemetry token count, defaulting to zero.

    Streaming calls emit placeholder counts and a new Honcho release could change
    the field's type; neither should fail a batch that carries real usage.
    """
    if isinstance(value, bool) or value is None:
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return 0
    return 0


def _parse_timestamp(value: object) -> datetime.datetime:
    if isinstance(value, str):
        try:
            parsed = datetime.datetime.fromisoformat(value)
        except ValueError:
            return datetime.datetime.now(datetime.UTC)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=datetime.UTC)
    return datetime.datetime.now(datetime.UTC)

"""Honcho's memory spend.

Honcho sends every model call to LiteLLM on one service credential, so LiteLLM's
figure for that key is the total cost of all memory work — a single pool-level
number. Opted-in Agents share memory pools, and the pool is the unit of cost, so
the total is reported as-is rather than split per Agent. (Per-call telemetry is
still recorded per workspace for analytics, but it no longer drives cost.)
"""

import datetime
import hashlib
from dataclasses import dataclass

from injector import inject, singleton

from api.core.config import Config
from api.domains.costs.models import HonchoUsageEvent
from api.domains.costs.repository import HonchoUsageRepository
from api.infrastructure.honcho.client import pool_id_from_workspace
from api.infrastructure.litellm.client import LiteLLMClient

# Honcho's usage telemetry: one CloudEvent per model/embedding call, carrying the
# workspace and token counts. Only these two types carry usage — Honcho emits
# others (agent.iteration, dialectic.completed, ...) on the same stream, which we
# skip. (The richer ".traced" trace events from PR #1166 go to a separate trace
# exporter, not this usage endpoint; v3.2.0 still matters here because its capture
# fix stops streamed calls from under-reporting output tokens in these events.)
_HONCHO_USAGE_EVENT_TYPES = frozenset({"llm.call.completed", "embedding.call.completed"})


@inject
@singleton
@dataclass
class HonchoUsageService:
    """Records Honcho's per-call telemetry and reports its total spend.

    Honcho sends every model call on one service credential, so LiteLLM's figure
    for that key is the whole memory bill. That total is the pool-level memory
    cost; it is reported as-is rather than apportioned per Agent.
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

    def memory_cost_total(self, start_date: str, end_date: str) -> float:
        """The total memory cost for the window: Honcho's full LiteLLM spend.

        Honcho holds one credential for all memory work, so LiteLLM's figure for
        that key is the total — a single pool-level number. Memory cost is not
        split per Agent: opted-in Agents share pools, and the pool is the unit of
        cost, so there is nothing to apportion.
        """
        if not self.config.honcho_litellm_key:
            return 0.0
        key_hash = hashlib.sha256(self.config.honcho_litellm_key.encode()).hexdigest()
        spend_report = self.litellm.get_global_spend_report(start_date, end_date)
        return float(spend_report.get(key_hash, {}).get("spend", 0.0))

    def cost_by_group(self, start: datetime.datetime, end: datetime.datetime) -> dict[str, float]:
        """Split the memory total across groups (pools), reconciled to that total.

        Honcho bills all memory work on one credential, so LiteLLM's spend for that
        key is the exact total (`memory_cost_total`). Per-call telemetry names the
        workspace, so we apportion that total across groups in proportion to each
        pool workspace's token share. The split is an approximation — raw token
        weight, not per-model price, so an embedding-heavy pool is weighted a little
        high — but it always sums back to the authoritative total. Only pool
        workspaces (`af-pool-<group id>`) count; any legacy per-Agent workspace is
        ignored (the group model has none).

        Returned keys are group ids (as strings); the caller scopes them to an
        Organization and attaches names.
        """
        total = self.memory_cost_total(start.date().isoformat(), end.date().isoformat())
        if total <= 0:
            return {}
        tokens_by_group: dict[str, int] = {}
        for row in self.repository.token_totals_by_workspace(start, end):
            group_id = pool_id_from_workspace(row.workspace_name)
            if group_id is None:
                continue
            tokens_by_group[group_id] = tokens_by_group.get(group_id, 0) + row.input_tokens + row.output_tokens
        grand_total = sum(tokens_by_group.values())
        if grand_total == 0:
            return {}
        return {gid: round(total * tokens / grand_total, 12) for gid, tokens in tokens_by_group.items()}


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

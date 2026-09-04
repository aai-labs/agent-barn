import argparse
import hashlib
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from api.domains.agents.models import Agent
from api.domains.costs.constants import (
    COST_HEAL_BATCH_SIZE,
    COST_HEAL_CONCURRENCY,
    COST_SYNC_MAX_RUNTIME_SECONDS,
    COST_SYNC_PAGE_SIZE,
    COST_SYNC_WATERMARK_OVERLAP_SECONDS,
    LITELLM_SPEND_LOG_DATETIME_FORMAT,
)
from api.domains.costs.models import CostRecord, CostRecordSource
from api.infrastructure.crypto import decrypt_token

logger = logging.getLogger(__name__)

# Where the very first run starts reading. LiteLLM has no spend logs older than the
# proxy itself, so an over-wide window costs one cheap empty page, while too narrow a
# one would silently skip history nobody notices is missing.
BACKFILL_EPOCH = datetime(2024, 1, 1, tzinfo=UTC)

# Fields copied out of a spend-log row. Everything else — metadata, messages,
# requester_ip_address, request_tags, end_user, session_id — is deliberately left
# behind (docs/adr/2026-07-30-platform-oversight-without-organization-access.md).
_SPEND_LOG_ALLOWLIST = (
    "request_id",
    "startTime",
    "endTime",
    "spend",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "model",
    "status",
    "call_type",
    "request_duration_ms",
    "api_key",
)


@dataclass(frozen=True)
class CostSyncResult:
    pages_read: int = 0
    rows_synced: int = 0
    rows_skipped: int = 0
    rows_protected: int = 0
    attributed: int = 0
    unattributed: int = 0
    heal_attempted: int = 0
    heal_succeeded: int = 0
    heal_not_found: int = 0
    heal_failed: int = 0
    truncated: bool = False


@dataclass(frozen=True)
class Attribution:
    agent_id: UUID
    agent_name: str
    organization_id: UUID
    organization_name: str | None


class CostSyncRepository(Protocol):
    def upsert_many(self, records: list[CostRecord]) -> int: ...
    def latest_occurred_at(self) -> datetime | None: ...
    def find_heal_candidates(self, limit: int) -> list[CostRecord]: ...
    def mark_healed(
        self,
        request_id: str,
        *,
        spend: Decimal,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
    ) -> bool: ...
    def count_heal_candidates(self) -> int: ...
    def find_organization_names(self) -> dict[UUID, str]: ...


class CostSyncAgentRepository(Protocol):
    def find_all_with_litellm_keys(self) -> list[Agent]: ...


class CostSyncSpendLogSource(Protocol):
    def get_spend_logs_v2(
        self,
        start_date: str,
        end_date: str,
        page: int = 1,
        page_size: int = 1000,
    ) -> dict: ...


class CostSyncGenerationSource(Protocol):
    def get_generation(self, generation_id: str) -> dict | None: ...


@dataclass
class CostSynchronizer:
    """Keeps our own cost table current, and repairs the spend LiteLLM lost.

    Two phases, in order, both bounded by one shared deadline:

    1. **Sync** — page LiteLLM's spend log from the watermark and upsert what we find.
    2. **Heal** — look up rows that recorded no money for a call that used tokens, and
       write back the cost OpenRouter actually charged.

    Phase 2 depends on phase 1 having run, but neither has to finish. Both resume from
    durable state, so a run cut short by the deadline just continues on the next tick.
    """

    repository: CostSyncRepository
    agent_repository: CostSyncAgentRepository
    spend_logs: CostSyncSpendLogSource
    generations: CostSyncGenerationSource
    encryption_key: str

    def run_once(self) -> CostSyncResult:
        started = time.monotonic()
        result = self._sync(started)
        result = self._heal(result, started)
        self._log_summary(result)
        return result

    # --- Phase 1: sync -----------------------------------------------------

    def _sync(self, started: float) -> CostSyncResult:
        attributions = self._build_attribution_map()
        start_date, end_date = self._window()
        logger.info(
            "Cost sync reading %s -> %s with %s attributable key(s)",
            start_date,
            end_date,
            len(attributions),
        )

        pages = 0
        synced = 0
        skipped = 0
        protected = 0
        attributed = 0
        unattributed = 0
        truncated = False
        page = 1

        while True:
            if self._out_of_time(started):
                truncated = True
                break
            try:
                payload = self.spend_logs.get_spend_logs_v2(start_date, end_date, page, COST_SYNC_PAGE_SIZE)
            except Exception as exc:
                # Stop rather than skip ahead. Pages are ascending, so the watermark
                # already covers everything written so far and the next run picks up
                # exactly here; jumping the failed page would leave a permanent hole.
                logger.warning("Cost sync stopped at page %s: %s", page, exc)
                truncated = True
                break

            rows = payload.get("data") or []
            if not rows:
                break
            pages += 1

            records = []
            for row in rows:
                record = self._to_record(row, attributions)
                if record is None:
                    skipped += 1
                    continue
                if record.agent_id is None:
                    unattributed += 1
                else:
                    attributed += 1
                records.append(record)

            written = self.repository.upsert_many(records)
            synced += written
            # Rows the upsert guard refused: already healed, and LiteLLM is still
            # reporting zero for them. A healthy number here means healing is holding.
            protected += len(records) - written

            total_pages = int(payload.get("total_pages") or 1)
            if page >= total_pages:
                break
            page += 1

        return CostSyncResult(
            pages_read=pages,
            rows_synced=synced,
            rows_skipped=skipped,
            rows_protected=protected,
            attributed=attributed,
            unattributed=unattributed,
            truncated=truncated,
        )

    def _window(self) -> tuple[str, str]:
        """The range to read, as LiteLLM's timestamp strings.

        The watermark is the newest call we already hold, rewound by an hour because
        rows land in the spend log slightly after the call they describe. Re-reading
        that hour is free: the upsert is keyed on request_id.

        An empty table yields the epoch, which *is* the backfill — the first run needs
        no special case because "sync everything" and "sync since the watermark" are
        the same code path.
        """
        watermark = self.repository.latest_occurred_at()
        if watermark is None:
            start = BACKFILL_EPOCH
        else:
            if watermark.tzinfo is None:
                watermark = watermark.replace(tzinfo=UTC)
            start = watermark - timedelta(seconds=COST_SYNC_WATERMARK_OVERLAP_SECONDS)
        end = datetime.now(UTC) + timedelta(minutes=1)
        return (
            start.strftime(LITELLM_SPEND_LOG_DATETIME_FORMAT),
            end.strftime(LITELLM_SPEND_LOG_DATETIME_FORMAT),
        )

    def _build_attribution_map(self) -> dict[str, Attribution]:
        """SHA-256 of each agent's LiteLLM key -> who to bill it to.

        LiteLLM cannot answer this itself: on production's 40,674 rows its own
        `agent_id` is NULL on every one and `organization_id` is an empty string on
        every one. The mapping has to come from our agent table.
        """
        organization_names = self.repository.find_organization_names()
        attributions: dict[str, Attribution] = {}
        undecryptable = 0

        for agent in self.agent_repository.find_all_with_litellm_keys():
            try:
                key = decrypt_token(agent.litellm_key_encrypted, self.encryption_key)
            except Exception:
                # A key encrypted under a rotated secret. Never log the ciphertext or
                # the exception: both can carry key material.
                undecryptable += 1
                continue
            key_hash = hashlib.sha256(key.encode()).hexdigest()
            attributions[key_hash] = Attribution(
                agent_id=agent.id,
                agent_name=agent.name,
                organization_id=agent.organization_id,
                organization_name=organization_names.get(agent.organization_id),
            )

        if undecryptable:
            logger.warning(
                "Cost sync could not decrypt %s agent key(s); their spend will land unattributed",
                undecryptable,
            )
        return attributions

    def _to_record(self, row: dict, attributions: dict[str, Attribution]) -> CostRecord | None:
        """Project one spend-log row through the allowlist. None means unusable."""
        data = {field: row.get(field) for field in _SPEND_LOG_ALLOWLIST}

        request_id = data["request_id"]
        occurred_at = _parse_timestamp(data["startTime"])
        if not request_id or occurred_at is None:
            # Without an id there is nothing to key on, and without a time the row
            # cannot be placed in any window — including the watermark's.
            return None

        key_hash = str(data["api_key"] or "")
        attribution = attributions.get(key_hash)

        return CostRecord(
            request_id=str(request_id),
            litellm_key_hash=key_hash,
            occurred_at=occurred_at,
            ended_at=_parse_timestamp(data["endTime"]),
            # Through str(), not float(): the JSON value is a float, and going
            # straight to Decimal would carry its binary artifacts into a column
            # whose whole point is exactness.
            spend=Decimal(str(data["spend"] or 0)),
            prompt_tokens=int(data["prompt_tokens"] or 0),
            completion_tokens=int(data["completion_tokens"] or 0),
            total_tokens=int(data["total_tokens"] or 0),
            model=str(data["model"] or "unknown"),
            status=str(data["status"] or "unknown"),
            call_type=str(data["call_type"]) if data["call_type"] else None,
            request_duration_ms=int(data["request_duration_ms"]) if data["request_duration_ms"] else None,
            agent_id=attribution.agent_id if attribution else None,
            organization_id=attribution.organization_id if attribution else None,
            agent_name=attribution.agent_name if attribution else None,
            organization_name=attribution.organization_name if attribution else None,
            source=CostRecordSource.LITELLM_LIVE,
        )

    # --- Phase 2: heal -----------------------------------------------------

    def _heal(self, result: CostSyncResult, started: float) -> CostSyncResult:
        if self._out_of_time(started):
            return replace(result, truncated=True)

        candidates = self.repository.find_heal_candidates(COST_HEAL_BATCH_SIZE)
        if not candidates:
            return result

        healed = 0
        not_found = 0
        failed = 0
        attempted = 0

        with ThreadPoolExecutor(max_workers=COST_HEAL_CONCURRENCY) as executor:
            futures = {
                executor.submit(self._heal_one, candidate.request_id, started): candidate
                for candidate in candidates
                if not self._out_of_time(started)
            }
            attempted = len(futures)
            for future in as_completed(futures):
                outcome = future.result()
                if outcome == "healed":
                    healed += 1
                elif outcome == "not_found":
                    not_found += 1
                else:
                    failed += 1

        return replace(
            result,
            heal_attempted=attempted,
            heal_succeeded=healed,
            heal_not_found=not_found,
            heal_failed=failed,
            truncated=result.truncated or attempted < len(candidates),
        )

    def _heal_one(self, request_id: str, started: float) -> str:
        if self._out_of_time(started):
            return "failed"
        try:
            generation = self.generations.get_generation(request_id)
        except Exception as exc:
            logger.warning("Cost healing lookup failed for %s: %s", request_id, exc)
            return "failed"

        if generation is None:
            # OpenRouter has no such generation. Leave the row a candidate: writing a
            # zero would assert the call was free, when all we know is that we could
            # not find out.
            return "not_found"

        total_cost = generation.get("total_cost")
        if total_cost is None:
            return "failed"

        # Tag the row even when the cost is zero. A genuinely free generation is a real
        # answer, and leaving it untagged would have every future run fetch it again.
        self.repository.mark_healed(
            request_id,
            spend=Decimal(str(total_cost)),
            prompt_tokens=_optional_int(generation.get("native_tokens_prompt")),
            completion_tokens=_optional_int(generation.get("native_tokens_completion")),
        )
        return "healed"

    # --- Shared ------------------------------------------------------------

    def _out_of_time(self, started: float) -> bool:
        return time.monotonic() - started >= COST_SYNC_MAX_RUNTIME_SECONDS

    def _log_summary(self, result: CostSyncResult) -> None:
        # The attributed/unattributed ratio is the tell that key decryption is healthy.
        # If AGENT_TOKEN_ENCRYPTION_KEY is ever rotated without re-encrypting, spend
        # keeps recording and quietly stops being attributable — this line is where
        # that shows up.
        logger.info(
            "Cost sync summary: pages=%s synced=%s skipped=%s protected=%s attributed=%s unattributed=%s "
            "heal_attempted=%s heal_succeeded=%s heal_not_found=%s heal_failed=%s "
            "heal_backlog=%s truncated=%s",
            result.pages_read,
            result.rows_synced,
            result.rows_skipped,
            result.rows_protected,
            result.attributed,
            result.unattributed,
            result.heal_attempted,
            result.heal_succeeded,
            result.heal_not_found,
            result.heal_failed,
            self.repository.count_heal_candidates(),
            result.truncated,
        )


def _parse_timestamp(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _optional_int(value: object) -> int | None:
    if not isinstance(value, int | float | str):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def build_synchronizer() -> CostSynchronizer:
    from api.core.utils import create_injector

    injector = create_injector()
    return injector.get(CostSynchronizer)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync LiteLLM spend into cost_record and heal missing costs.")
    parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    build_synchronizer().run_once()


if __name__ == "__main__":
    main()

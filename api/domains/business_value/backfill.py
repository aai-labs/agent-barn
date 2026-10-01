"""Operator-run backfill of Business Actions from stored Tool Calls.

Classifies every completed shell Tool Call from its stored content, never from its
stored status, and makes its stored rows match. Re-running it after a catalogue change
re-maps integration, resource, verb, is_write, and outcome_type on rows whose mapping
changed, and removes rows the catalogue no longer produces, while leaving status alone.
A Tool Call whose classification fails is skipped and keeps its rows. It is never
reachable from a router.
"""

import argparse
import logging
from dataclasses import dataclass
from uuid import UUID

from api.core.utils import create_injector
from api.domains.business_value.classifier import ClassifiedAction, classify
from api.domains.business_value.repository import BusinessActionRepository
from api.domains.tool_calls.models import ToolCall

BACKFILL_BATCH_SIZE = 500

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BackfillResult:
    scanned: int
    recorded: int
    removed: int
    failed: int


def run_backfill(repository: BusinessActionRepository, batch_size: int = BACKFILL_BATCH_SIZE) -> BackfillResult:
    scanned = recorded = removed = failed = 0
    after_id: UUID | None = None
    while batch := repository.find_backfill_batch(after_id, batch_size):
        classified: list[tuple[ToolCall, list[ClassifiedAction]]] = []
        for tool_call in batch:
            try:
                classified.append((tool_call, classify(tool_call)))
            except Exception:
                failed += 1
                logger.exception("Could not classify tool call %s", tool_call.id)
        applied = repository.apply_classified(classified)
        recorded += applied.recorded
        removed += applied.removed
        scanned += len(batch)
        after_id = batch[-1].id
    result = BackfillResult(scanned=scanned, recorded=recorded, removed=removed, failed=failed)
    logger.info(
        "Business action backfill summary: scanned=%s recorded=%s removed=%s failed=%s",
        result.scanned,
        result.recorded,
        result.removed,
        result.failed,
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Backfill Business Actions from stored shell Tool Calls.")
    parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run_backfill(create_injector().get(BusinessActionRepository))


if __name__ == "__main__":
    main()

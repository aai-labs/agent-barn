"""Scheduled snapshots: a restore point of every running Agent, every few hours.

Run on a schedule (the `restore-point-schedule` CronJob), or with `--watch` for local
development. Each run settles the snapshots already in progress, trims what Agents keep
past their limits, then starts snapshots for the Agents that are due, a few at a time.
"""

import argparse
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from injector import inject, singleton

from api.core.config import Config
from api.domains.restore_points.models import ACTIVE_CAPTURE_STATUSES
from api.domains.restore_points.repository import RestorePointRepository
from api.domains.restore_points.service import RestorePointService

logger = logging.getLogger(__name__)

WATCH_INTERVAL_SECONDS = 300


@dataclass
class ScheduledSnapshotResult:
    in_flight: int = 0
    trimmed_agents: int = 0
    started: int = 0
    failed: int = 0


@inject
@singleton
@dataclass
class ScheduledSnapshotRunner:
    config: Config
    repository: RestorePointRepository
    service: RestorePointService

    def run_once(self) -> ScheduledSnapshotResult:
        result = ScheduledSnapshotResult()
        if self.config.restore_point_schedule_interval_minutes == 0:
            logger.info("Scheduled snapshots are off (RESTORE_POINT_SCHEDULE_INTERVAL_MINUTES=0).")
            return result

        result.in_flight = self._settle_in_flight()
        result.trimmed_agents = self._trim(result)

        room = self.config.restore_point_schedule_max_concurrent - result.in_flight
        if room > 0:
            cutoff = datetime.now(UTC) - timedelta(minutes=self.config.restore_point_schedule_interval_minutes)
            # A skipped Agent writes no row, so it stays first in line. Walking past it,
            # rather than giving it a slot, keeps an Agent stuck without a pod from
            # holding back every other one.
            for agent_id in self.repository.find_agent_ids_due_a_snapshot(last_taken_before=cutoff):
                if result.started >= room:
                    break
                try:
                    if self.service.capture_scheduled(agent_id) is not None:
                        result.started += 1
                except Exception:
                    result.failed += 1
                    logger.warning("Could not start a scheduled snapshot of agent %s", agent_id, exc_info=True)

        logger.info(
            "Scheduled snapshot summary: in_flight=%s trimmed_agents=%s started=%s failed=%s",
            result.in_flight,
            result.trimmed_agents,
            result.started,
            result.failed,
        )
        return result

    def _settle_in_flight(self) -> int:
        """Resolve the snapshots in progress, and count those still running.

        The reconciler only reaches rows idle for many minutes, so without this a finished
        snapshot would hold a concurrency slot long after its Job is done.
        """
        for row in self.repository.find_in_flight_scheduled():
            try:
                self.service.reconcile_row(row)
            except Exception:
                logger.warning("Could not reconcile scheduled snapshot %s", row.id, exc_info=True)
        return sum(1 for row in self.repository.find_in_flight_scheduled() if row.status in ACTIVE_CAPTURE_STATUSES)

    def _trim(self, result: ScheduledSnapshotResult) -> int:
        """Apply retention to Agents over a limit, including those whose limit a managed update
        held back when their backup became ready."""
        agent_ids = self.repository.find_agent_ids_over_retention(
            scheduled_cap=self.config.restore_point_scheduled_max_per_agent,
            manual_cap=self.config.restore_point_max_per_agent,
        )
        trimmed = 0
        for agent_id in agent_ids:
            try:
                trimmed += self.service.enforce_retention(agent_id) > 0
            except Exception:
                result.failed += 1
                logger.warning("Could not apply restore point retention for agent %s", agent_id, exc_info=True)
        return trimmed


def build_runner() -> ScheduledSnapshotRunner:
    from api.core.utils import create_injector

    injector = create_injector()
    return injector.get(ScheduledSnapshotRunner)


def main() -> None:
    parser = argparse.ArgumentParser(description="Take scheduled snapshots of running Agents.")
    parser.add_argument(
        "--watch", action="store_true", help="Run immediately and every 5 minutes for local development."
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    while True:
        started = time.monotonic()
        try:
            build_runner().run_once()
        except Exception:
            if not args.watch:
                raise
            logger.exception("Scheduled snapshots failed; retrying on the next interval.")
        if not args.watch:
            return
        time.sleep(max(0, WATCH_INTERVAL_SECONDS - (time.monotonic() - started)))


if __name__ == "__main__":
    main()

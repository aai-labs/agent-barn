"""Delete ended cron sessions from Hermes' state.db once they pass the retention.

Every scheduled run opens a session, so an Agent with frequent crons adds hundreds a
day, and sessions.auto_prune (30 days, at gateway start only) let one Agent's state.db
fill its 1 GiB volume. Results stay in cron/output; only run transcripts go. Archived
sessions are pruned too (the `hermes sessions prune` CLI skips them); pinned ones are kept.

Hermes runs cron per profile, so each Bot keeps its cron sessions in its own
profiles/<bot-id>/state.db on the same volume; every one of them is pruned here.

Deleting is one transaction per prune_sessions call, and its WAL grows to about half of
what it deletes: one call clearing weeks of backlog can need more free space than a full
volume has. Walking the cutoff forward a day at a time keeps each transaction to one day.
No VACUUM: it rewrites the database through the WAL; freed pages are reused instead.

Usage: session-prune.py [--every SECONDS]. Without --every it prunes once and exits; with
it, it waits SECONDS before each prune, because start.sh has already pruned at boot.
"""

import argparse
import logging
import time
from pathlib import Path

from hermes_constants import get_hermes_home  # ty: ignore[unresolved-import]
from hermes_state import SessionDB  # ty: ignore[unresolved-import]

CRON_RETENTION_DAYS = 7
_SOURCE = "cron"
_DAY = 86400.0

logger = logging.getLogger("agentbarn.session-prune")


def hermes_homes(root: Path) -> list[Path]:
    """The Parent Agent's home, then each Bot profile that has a state.db."""
    return [root, *sorted(path.parent for path in (root / "profiles").glob("*/state.db"))]


def prune_once(db: SessionDB, sessions_dir: Path) -> int:
    candidates = db.list_prune_candidates(older_than_days=CRON_RETENTION_DAYS, source=_SOURCE)
    if not candidates:
        return 0
    # Candidates come oldest activity first: start at the oldest's age and step down to the retention.
    age = max(CRON_RETENTION_DAYS, int((time.time() - candidates[0]["last_active"]) / _DAY))
    pruned = 0
    while age >= CRON_RETENTION_DAYS:
        pruned += db.prune_sessions(older_than_days=age, source=_SOURCE, sessions_dir=sessions_dir)
        age -= 1
    return pruned


def _prune_home(home: Path) -> None:
    db = SessionDB(home / "state.db")
    try:
        pruned = prune_once(db, home / "sessions")
    finally:
        db.close()
    if pruned:
        logger.info("pruned %d cron session(s) older than %d days in %s", pruned, CRON_RETENTION_DAYS, home)


def _run() -> None:
    for home in hermes_homes(get_hermes_home()):
        try:
            _prune_home(home)
        except Exception:
            # One failing profile must not stop the others, the boot, or the daily loop.
            logger.exception("cron session prune failed in %s", home)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--every", type=float, default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="[session-prune] %(message)s")
    while True:
        if args.every is not None:
            time.sleep(args.every)
        try:
            _run()
        except Exception:
            # Maintenance must never stop the Agent from booting or keep the loop from retrying.
            logger.exception("cron session prune failed")
        if args.every is None:
            return


if __name__ == "__main__":
    main()

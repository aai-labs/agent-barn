"""Ends subscription periods that have run out and applies holds whose choosing time is up.

Run by the `tier-sweep` CronJob, and locally by the compose service of the same name with
`--watch`. Called as `python -c "from api.domains.subscriptions.sweep import main; main()"`,
not `python -m`, for the reason the cost sync gives.
"""

import argparse
import logging
import time

from api.domains.subscriptions.service import SubscriptionService

logger = logging.getLogger(__name__)

WATCH_INTERVAL_SECONDS = 300


def main() -> None:
    parser = argparse.ArgumentParser(description="End subscription periods and apply due Tier Holds.")
    parser.add_argument("--watch", action="store_true", help="Run now and every five minutes, for local development.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    from api.core.utils import create_injector

    service = create_injector().get(SubscriptionService)
    while True:
        started = time.monotonic()
        try:
            service.sweep()
        except Exception:
            if not args.watch:
                raise
            logger.exception("Tier sweep failed; retrying on the next interval.")
        if not args.watch:
            return
        time.sleep(max(0, WATCH_INTERVAL_SECONDS - (time.monotonic() - started)))

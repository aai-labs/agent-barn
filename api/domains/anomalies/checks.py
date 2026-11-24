"""Checks the Agents of Organizations that turned anomaly detection on.

Run by the `anomaly-checks` CronJob a few minutes after each cost sync, and locally by
the Compose service of the same name with `--watch`. Called as
`python -c "from api.domains.anomalies.checks import main; main()"`, not `python -m`,
for the reason the cost sync gives.
"""

import argparse
import logging
import time

from api.core.utils import create_injector
from api.domains.anomalies.service import AnomalyCheckService

logger = logging.getLogger(__name__)

WATCH_INTERVAL_SECONDS = 900


def main() -> None:
    parser = argparse.ArgumentParser(description="Check opted-in Agents for unusual activity.")
    parser.add_argument("--watch", action="store_true", help="Run now and every 15 minutes, for local development.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    service = create_injector().get(AnomalyCheckService)
    while True:
        started = time.monotonic()
        try:
            summary = service.run_checks()
            logger.info(
                "Checked %d agents in %d organizations, %d failed",
                summary.agents,
                summary.organizations,
                summary.failures,
            )
            # An Agent that failed is logged by the check and retried by the next run.
            # Failing the Job would only make Kubernetes restart it and check every
            # other Agent again.
        except Exception:
            if not args.watch:
                raise
            logger.exception("Anomaly check failed; retrying on the next interval.")
        if not args.watch:
            return
        time.sleep(max(0, WATCH_INTERVAL_SECONDS - (time.monotonic() - started)))

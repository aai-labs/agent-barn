"""Bounded operator-only cleanup, optionally repeated for the local Compose stack."""

import argparse
import logging
import signal
from threading import Event

from api.core.utils import create_injector
from api.domains.artifacts.service import ArtifactService

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=int, default=0, help="Repeat every N seconds; zero runs one bounded pass")
    args = parser.parse_args()
    if args.interval and args.interval < 10:
        parser.error("interval must be zero or at least 10 seconds")
    stopped = Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    service = create_injector().get(ArtifactService)
    while not stopped.is_set():
        try:
            print(f"Purged {service.purge()} artifacts", flush=True)
        except Exception as exc:
            if not args.interval:
                raise
            logger.warning("Artifact cleanup pass failed (%s); will retry", type(exc).__name__)
        if not args.interval or stopped.wait(args.interval):
            break


if __name__ == "__main__":
    main()

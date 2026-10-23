import logging
import signal
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from api.core.utils import create_injector
from api.domains.file_sync.engine import FileSyncEngine

logger = logging.getLogger(__name__)

PASS_INTERVAL_SECONDS = 30
HEARTBEAT_PATH = Path("/tmp/sync-engine-heartbeat")


class _Engine(Protocol):
    def run_pass(self, now: datetime) -> None: ...


def run(engine: _Engine, *, stop: threading.Event, interval_seconds: float, heartbeat: Path) -> None:
    while not stop.is_set():
        try:
            engine.run_pass(datetime.now(UTC))
        except Exception:
            logger.exception("File sync pass failed")
        else:
            heartbeat.touch()
        stop.wait(interval_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    engine = create_injector().get(FileSyncEngine)
    logger.info("Sync Engine started, one pass every %ss", PASS_INTERVAL_SECONDS)
    run(engine, stop=stop, interval_seconds=PASS_INTERVAL_SECONDS, heartbeat=HEARTBEAT_PATH)
    logger.info("Sync Engine stopped")


if __name__ == "__main__":
    main()

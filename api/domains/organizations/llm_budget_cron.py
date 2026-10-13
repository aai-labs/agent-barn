import argparse
import logging
import time
from collections.abc import Callable

from api.domains.organizations.llm_budget_service import OrganizationLlmBudgetService

logger = logging.getLogger(__name__)


def build_service() -> OrganizationLlmBudgetService:
    from api.core.utils import create_injector

    return create_injector().get(OrganizationLlmBudgetService)


def run(description: str, operation: Callable[[OrganizationLlmBudgetService], object]) -> None:
    """Shared entry point for the budget CronJobs.

    They keep separate modules because the chart names each one directly, but the
    bodies were identical apart from the description and the method called.
    """
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--watch", action="store_true", help="Run immediately and every five minutes locally.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    while True:
        started = time.monotonic()
        try:
            operation(build_service())
        except Exception:
            if not args.watch:
                raise
            logger.exception("Local budget refresh failed; retrying on the next interval.")
        if not args.watch:
            return
        time.sleep(max(0, 300 - (time.monotonic() - started)))

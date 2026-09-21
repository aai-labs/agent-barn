import argparse
import logging
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
    argparse.ArgumentParser(description=description).parse_args()
    logging.basicConfig(level=logging.INFO)
    operation(build_service())

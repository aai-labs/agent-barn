import argparse
import logging
from collections.abc import Callable
from typing import Any

from api.domains.organizations.llm_budget_service import OrganizationLlmBudgetService

logger = logging.getLogger(__name__)


def build_service(service_type: type = OrganizationLlmBudgetService) -> Any:
    from api.core.utils import create_injector

    return create_injector().get(service_type)


def run(
    description: str,
    operation: Callable[[Any], object],
    service_type: type = OrganizationLlmBudgetService,
) -> None:
    """Shared entry point for the budget CronJobs.

    They keep separate modules because the chart names each one directly, but the
    bodies were identical apart from the description, the service and the method
    called.
    """
    argparse.ArgumentParser(description=description).parse_args()
    logging.basicConfig(level=logging.INFO)
    operation(build_service(service_type))

import argparse
import logging
from collections.abc import Callable
from typing import Any

# Registered for the Agent rows these jobs save: `agent.memory_group_id` references
# `memory_group`, and a CronJob is its own process that would otherwise never import
# it (the API does, through its routes), so an Agent save fails to resolve the key.
import api.domains.memory_groups.models  # noqa: F401
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

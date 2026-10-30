"""Bounded operator pass for missed wakeups, lost attempts and text retention."""

import logging

from api.core.utils import create_injector
from api.domains.workflows.controller import WorkflowController
from api.domains.workflows.run_repository import WorkflowRunRepository

logger = logging.getLogger(__name__)


def main() -> None:
    injector = create_injector()
    repository = injector.get(WorkflowRunRepository)
    controller = injector.get(WorkflowController)
    for run_id in repository.active_ids():
        try:
            controller.wake(run_id)
        except Exception:
            logger.warning("Workflow reconciliation failed for run %s", run_id)
    repository.expire_content()


if __name__ == "__main__":
    main()

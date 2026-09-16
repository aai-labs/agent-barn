import argparse
import logging

from api.domains.organizations.service import OrganizationService

logger = logging.getLogger(__name__)


def build_service() -> OrganizationService:
    from api.core.utils import create_injector

    injector = create_injector()
    return injector.get(OrganizationService)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh Organization LLM spend snapshots and notify on threshold crossings.",
    )
    parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    build_service().check_llm_budget_thresholds()


if __name__ == "__main__":
    main()

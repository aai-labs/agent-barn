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
        description="Push each Organization's stored LLM budget onto its LiteLLM team.",
    )
    parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    build_service().reconcile_llm_budgets()


if __name__ == "__main__":
    main()

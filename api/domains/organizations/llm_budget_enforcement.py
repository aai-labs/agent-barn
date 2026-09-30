from api.domains.organizations.llm_budget_cron import run
from api.domains.organizations.memory_budget import OrganizationMemoryBudgetService


def main() -> None:
    run(
        "Count each Organization's memory spend against its LLM budget.",
        lambda service: service.enforce_memory_budgets(),
        OrganizationMemoryBudgetService,
    )


if __name__ == "__main__":
    main()

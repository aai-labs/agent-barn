from api.domains.organizations.llm_budget_cron import run


def main() -> None:
    run(
        "Push each Organization's stored LLM budget onto its LiteLLM team.",
        lambda service: service.reconcile_llm_budgets(),
    )


if __name__ == "__main__":
    main()

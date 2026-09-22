from api.domains.organizations.llm_budget_cron import run


def main() -> None:
    run(
        "Refresh Organization LLM spend snapshots and notify on threshold crossings.",
        lambda service: service.check_llm_budget_thresholds(),
    )


if __name__ == "__main__":
    main()

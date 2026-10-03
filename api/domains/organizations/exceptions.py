class OrganizationCreationLimitReached(Exception):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"Organization creation limit of {limit} reached")


class LlmBudgetAboveCeiling(Exception):
    """An Organization's own spend limit above the platform's ceiling in force."""

    def __init__(self, ceiling_usd: float) -> None:
        self.ceiling_usd = ceiling_usd
        super().__init__(f"Spend limit above the ceiling of {ceiling_usd}")

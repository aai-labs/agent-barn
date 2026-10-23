class OrganizationCreationLimitReached(Exception):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"Organization creation limit of {limit} reached")


class LlmBudgetAboveCeiling(Exception):
    """An Organization's own spend limit above the platform's ceiling in force."""

    def __init__(self, ceiling_usd: float) -> None:
        self.ceiling_usd = ceiling_usd
        super().__init__(f"Spend limit above the ceiling of {ceiling_usd}")


class OrganizationNotOnCredit(Exception):
    """Credit granted to an Organization whose limit renews rather than being spent down."""

    def __init__(self, organization_id: object) -> None:
        self.organization_id = organization_id
        super().__init__(f"Organization {organization_id} does not run on credit")

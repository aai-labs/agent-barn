class OrganizationCreationLimitReached(Exception):
    def __init__(self, limit: int) -> None:
        self.limit = limit
        super().__init__(f"Organization creation limit of {limit} reached")

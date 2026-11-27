class TrialSignupCreditRequired(ValueError):
    """Self-signup cannot be enabled without a positive trial credit."""


class TrialSignupTierRequired(ValueError):
    """Self-signup cannot be enabled without a signup Tier."""

    def __init__(self) -> None:
        super().__init__(
            "Offer Free with Agent Barn Telegram configured, or a purchasable paid tier, before enabling self-signup."
        )

import logging

YELLOW = "\033[93m"
RESET = "\033[0m"


def log_email_delivery_disabled_warning(logger: logging.Logger) -> None:
    logger.warning(
        f"\n\n"
        f"{YELLOW}"
        "⚠️ EMAIL DELIVERY DISABLED\n"
        "Email delivery is disabled because EMAIL_SERVER_CREDENTIAL or EMAIL_SMTP_SERVER is not set."
        f"{RESET}"
        f"\n\n"
    )

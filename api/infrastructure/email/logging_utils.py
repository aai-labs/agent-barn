import logging

YELLOW = "\033[93m"
RESET = "\033[0m"


def log_email_delivery_disabled_warning(logger: logging.Logger) -> None:
    logger.warning(
        f"\n\n"
        f"{YELLOW}"
        "⚠️ EMAIL DELIVERY DISABLED\n"
        "Email delivery is disabled because CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN "
        "or SENDER_EMAIL is not set."
        f"{RESET}"
        f"\n\n"
    )

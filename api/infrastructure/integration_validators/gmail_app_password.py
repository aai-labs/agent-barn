from api.domains.agents.models import GmailAppPasswordContent
from api.infrastructure.google import gmail_imap
from api.infrastructure.integration_validators.result import IntegrationValidationResult


def validate_gmail_app_password(content: GmailAppPasswordContent) -> IntegrationValidationResult:
    """Sign in to Gmail once, so a wrong or revoked app password fails on save."""
    try:
        gmail_imap.check_sign_in(content.email, content.app_password)
    except gmail_imap.MailSignInFailed:
        return IntegrationValidationResult(
            valid=False,
            error="Gmail rejected this address and app password. Check both, or create a new app password.",
        )
    except gmail_imap.MailUnavailable:
        return IntegrationValidationResult(valid=False, error="Could not reach Gmail. Try again in a moment.")
    return IntegrationValidationResult(valid=True, identity=content.email)

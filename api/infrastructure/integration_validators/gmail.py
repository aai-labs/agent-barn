from api.domains.agents.models import GmailContent
from api.infrastructure.integration_validators.google_grant import validate_google_grant
from api.infrastructure.integration_validators.result import IntegrationValidationResult


def validate_gmail(content: GmailContent) -> IntegrationValidationResult:
    """Exchange the stored refresh token and report identity plus any lost scopes."""
    return validate_google_grant(
        client_id=content.client_id,
        client_secret=content.client_secret,
        refresh_token=content.refresh_token,
        scopes=content.scopes,
        email=content.email,
    )

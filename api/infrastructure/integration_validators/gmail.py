import httpx

from api.domains.agents.models import GmailContent
from api.infrastructure.integration_validators.result import IntegrationValidationResult

_TIMEOUT = 10
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_PROFILE_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/profile"
_REQUIRED_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


def validate_gmail(content: GmailContent) -> IntegrationValidationResult:
    if not content.client_id or not content.client_secret:
        return IntegrationValidationResult(
            valid=False, error="Google OAuth is not configured on this server."
        )

    try:
        resp = httpx.post(
            _TOKEN_ENDPOINT,
            data={
                "client_id": content.client_id,
                "client_secret": content.client_secret,
                "refresh_token": content.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return IntegrationValidationResult(
            valid=False, error=f"Could not reach Google: {exc}"
        )

    if resp.status_code != 200:
        try:
            error_code = resp.json().get("error")
        except ValueError:
            error_code = None
        if error_code == "invalid_grant":
            return IntegrationValidationResult(
                valid=False,
                error=(
                    "Refresh token is invalid, expired, or revoked. "
                    "Reconnect via Authenticate with Google."
                ),
            )
        return IntegrationValidationResult(
            valid=False, error=f"Google returned unexpected status {resp.status_code}"
        )

    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return IntegrationValidationResult(
            valid=False, error="Google did not return an access token"
        )

    missing: list[str] = []
    granted_scope = token_data.get("scope", "")
    if granted_scope and _REQUIRED_SCOPE not in granted_scope.split():
        missing.append("gmail.readonly (read-only Gmail access)")

    return IntegrationValidationResult(
        valid=True, identity=_fetch_identity(access_token), missing_scopes=missing
    )


def _fetch_identity(access_token: str) -> str | None:
    try:
        resp = httpx.get(
            _PROFILE_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT,
        )
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    return resp.json().get("emailAddress")

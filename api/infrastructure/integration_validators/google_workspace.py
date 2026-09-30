import httpx

from api.domains.agents.models import GoogleWorkspaceContent
from api.infrastructure.integration_validators.result import IntegrationValidationResult

_TIMEOUT = 10
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


def validate_google_workspace(content: GoogleWorkspaceContent) -> IntegrationValidationResult:
    """Exchange the stored refresh token and report identity plus any lost scopes.

    Unlike the single-service Google validators, the expected scopes are read from the
    credential itself (what Google granted at consent time) rather than from a scope map
    here — so this can never drift from the route's derivation, and it catches the case
    where a user later trims the grant at myaccount.google.com.
    """
    if not content.client_id or not content.client_secret:
        return IntegrationValidationResult(valid=False, error="Google OAuth is not configured on this server.")

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
        return IntegrationValidationResult(valid=False, error=f"Could not reach Google: {exc}")

    if resp.status_code != 200:
        try:
            error_code = resp.json().get("error")
        except ValueError:
            error_code = None
        if error_code == "invalid_grant":
            return IntegrationValidationResult(
                valid=False,
                error=(
                    "Refresh token is invalid, expired, or revoked. Reconnect via Authenticate with Google. "
                    "If the Google OAuth app is still in Testing status, its refresh tokens expire after 7 days."
                ),
            )
        return IntegrationValidationResult(valid=False, error=f"Google returned unexpected status {resp.status_code}")

    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        return IntegrationValidationResult(valid=False, error="Google did not return an access token")

    missing: list[str] = []
    granted_scope = token_data.get("scope", "")
    if granted_scope and content.scopes:
        granted = set(granted_scope.split())
        missing = sorted(scope for scope in content.scopes if scope not in granted)

    identity = _fetch_identity(access_token)
    if identity and content.email and identity.casefold() != content.email.casefold():
        return IntegrationValidationResult(
            valid=False,
            identity=identity,
            missing_scopes=missing,
            error=(f"This credential now authenticates as {identity}, not {content.email}. Reconnect to update it."),
        )

    return IntegrationValidationResult(valid=True, identity=identity or content.email, missing_scopes=missing)


def _fetch_identity(access_token: str) -> str | None:
    """Account email via OpenID userinfo — available for any service mix, since the
    consent flow always requests the identity scopes."""
    try:
        resp = httpx.get(
            _USERINFO_ENDPOINT,
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=_TIMEOUT,
        )
    except Exception:
        return None
    if resp.status_code != 200:
        return None
    return resp.json().get("email")

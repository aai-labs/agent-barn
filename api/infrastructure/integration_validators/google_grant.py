"""Live check of a stored Google OAuth grant, shared by every Google-backed provider.

A provider's validator passes in the fields its credential stores. The expected scopes
come from the credential itself (what Google granted at consent time), so the check
cannot drift from the scopes the sign-in route requested, and it catches a grant the
user later trimmed at myaccount.google.com.
"""

import httpx

from api.infrastructure.integration_validators.result import IntegrationValidationResult

_TIMEOUT = 10
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"


def validate_google_grant(
    *,
    client_id: str,
    client_secret: str,
    refresh_token: str,
    scopes: list[str],
    email: str,
) -> IntegrationValidationResult:
    """Exchange the refresh token and report identity plus any scopes lost since consent."""
    if not client_id or not client_secret:
        return IntegrationValidationResult(valid=False, error="Google OAuth is not configured on this server.")

    try:
        resp = httpx.post(
            _TOKEN_ENDPOINT,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
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
    if granted_scope and scopes:
        granted = set(granted_scope.split())
        missing = sorted(scope for scope in scopes if scope not in granted)

    identity = _fetch_identity(access_token)
    if identity and email and identity.casefold() != email.casefold():
        return IntegrationValidationResult(
            valid=False,
            identity=identity,
            missing_scopes=missing,
            error=(f"This credential now authenticates as {identity}, not {email}. Reconnect to update it."),
        )

    return IntegrationValidationResult(valid=True, identity=identity or email, missing_scopes=missing)


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

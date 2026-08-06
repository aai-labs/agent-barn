import httpx

from api.domains.agents.models import SlackContent
from api.infrastructure.integration_validators.result import IntegrationValidationResult

_TIMEOUT = 10
_AUTH_TEST_URL = "https://slack.com/api/auth.test"

# Slack signals auth failures as HTTP 200 with {"ok": false, "error": "<code>"} rather
# than a 4xx status — map the codes we can give a clearer message for.
_ERROR_MESSAGES = {
    "invalid_auth": "Bot token is invalid or revoked",
    "not_authed": "No token was provided",
    "account_inactive": "Token is for a deactivated user or workspace",
    "token_revoked": "Bot token has been revoked",
    "token_expired": "Bot token has expired",
}


def validate_slack(content: SlackContent) -> IntegrationValidationResult:
    try:
        resp = httpx.post(
            _AUTH_TEST_URL,
            headers={"Authorization": f"Bearer {content.token}"},
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return IntegrationValidationResult(valid=False, error=f"Could not reach Slack: {exc}")

    if resp.status_code != 200:
        return IntegrationValidationResult(valid=False, error=f"Slack returned unexpected status {resp.status_code}")

    data = resp.json()
    if not data.get("ok"):
        error = data.get("error", "unknown_error")
        return IntegrationValidationResult(
            valid=False,
            error=_ERROR_MESSAGES.get(error, f"Slack returned error '{error}'"),
        )

    team = data.get("team", "")
    user = data.get("user", "")
    identity = f"{user} @ {team}" if user and team else (team or user or None)
    return IntegrationValidationResult(valid=True, identity=identity)

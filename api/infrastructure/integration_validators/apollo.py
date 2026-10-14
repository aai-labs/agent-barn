import httpx

from api.domains.agents.models import ApolloContent
from api.infrastructure.integration_validators.result import IntegrationValidationResult

_TIMEOUT = 10
# Apollo's documented key check. It answers 200 for any key and reports the key's
# validity in ``is_logged_in``, so the status code alone proves nothing. It proves only
# that the key is valid: a key reaches the endpoints chosen when it was created, and no
# endpoint distinguishes a master key from a key granted broad access.
_HEALTH_URL = "https://api.apollo.io/v1/auth/health"


def validate_apollo(content: ApolloContent) -> IntegrationValidationResult:
    try:
        resp = httpx.get(_HEALTH_URL, headers={"x-api-key": content.api_token}, timeout=_TIMEOUT)
    except Exception as exc:
        return IntegrationValidationResult(valid=False, error=f"Could not reach Apollo: {exc}")

    if resp.status_code == 401:
        return IntegrationValidationResult(valid=False, error="Invalid API key")
    if resp.status_code != 200:
        return IntegrationValidationResult(valid=False, error=f"Apollo returned unexpected status {resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        body = None
    if not isinstance(body, dict) or body.get("is_logged_in") is not True:
        return IntegrationValidationResult(valid=False, error="Invalid API key")
    return IntegrationValidationResult(valid=True)

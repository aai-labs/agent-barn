import httpx

from api.domains.agents.models import MerkysContent
from api.infrastructure.integration_validators.result import IntegrationValidationResult

_TIMEOUT = 10
# Cheapest authenticated call a user API key can make. `/api/limits` needs no auth, and
# `/api/auth/memberships` accepts only a JWT, so neither proves the key works. An empty
# list is a normal 200: it says nothing about what the key's owner may read.
_CHECK_PATH = "/api/conversation/?limit=1"


def validate_merkys(content: MerkysContent) -> IntegrationValidationResult:
    try:
        resp = httpx.get(
            f"{content.base_url}{_CHECK_PATH}",
            headers={"X-API-Key": content.api_key},
            timeout=_TIMEOUT,
            follow_redirects=False,
        )
    except Exception as exc:
        return IntegrationValidationResult(valid=False, error=f"Could not reach Merkys: {exc}")

    if resp.status_code == 401:
        return IntegrationValidationResult(valid=False, error="Invalid API key")
    if resp.status_code != 200:
        return IntegrationValidationResult(valid=False, error=f"Merkys returned unexpected status {resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        body = None
    # A reverse proxy or the wrong host can answer 200 with HTML; a Merkys list reply is JSON
    # with an `items` list.
    if not isinstance(body, dict) or not isinstance(body.get("items"), list):
        return IntegrationValidationResult(valid=False, error="The URL did not respond like a Merkys API")
    return IntegrationValidationResult(valid=True)

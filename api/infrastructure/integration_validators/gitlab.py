import logging

import httpx

from api.domains.agents.models import GitlabContent
from api.infrastructure.integration_validators.result import IntegrationValidationResult
from api.infrastructure.public_http import NonPublicDestination, pin_to_public_address

logger = logging.getLogger(__name__)

_TIMEOUT = 10


def validate_gitlab(content: GitlabContent) -> IntegrationValidationResult:
    # The URL is user-supplied and this runs on the API server, so it goes through the same
    # public-address pin as the gateway, and redirects are refused rather than followed.
    try:
        pinned = pin_to_public_address(f"{content.base_url}/api/v4/user")
    except NonPublicDestination as exc:
        logger.warning("GitLab validation refused %s: %s", content.base_url, exc)
        return IntegrationValidationResult(valid=False, error="GitLab must be reachable at a public https address.")

    try:
        with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
            resp = client.request(
                "GET",
                pinned.url,
                headers={**pinned.headers, "Authorization": f"Bearer {content.token}"},
                extensions=pinned.extensions,
            )
    except Exception as exc:
        logger.warning("GitLab validation could not reach %s: %s", content.base_url, exc)
        return IntegrationValidationResult(valid=False, error="Could not reach GitLab. Check the URL.")

    if resp.status_code == 401:
        return IntegrationValidationResult(valid=False, error="Invalid token")
    if resp.status_code == 403:
        return IntegrationValidationResult(valid=False, error="The token needs the read_api or api scope")
    if resp.status_code != 200:
        return IntegrationValidationResult(valid=False, error=f"GitLab returned unexpected status {resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        body = None
    # A reverse proxy or the wrong host can answer 200 with HTML.
    if not isinstance(body, dict) or "username" not in body:
        return IntegrationValidationResult(valid=False, error="The URL did not respond like a GitLab API")
    name = body.get("name", "")
    return IntegrationValidationResult(valid=True, identity=f"{name} (@{body['username']})")

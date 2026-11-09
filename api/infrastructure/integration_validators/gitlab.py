import logging

import httpx

from api.domains.agents.models import GitlabContent
from api.infrastructure.integration_validators.result import IntegrationValidationResult
from api.infrastructure.public_http import NonPublicDestination, pin_to_public_address

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_NOT_GITLAB = "The URL did not respond like a GitLab API"


def _get(content: GitlabContent, path: str) -> httpx.Response:
    # The URL is user-supplied and this runs on the API server, so it goes through the same
    # public-address pin as the gateway, and redirects are refused rather than followed.
    pinned = pin_to_public_address(f"{content.base_url}/api/v4{path}")
    with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
        return client.request(
            "GET",
            pinned.url,
            headers={**pinned.headers, "Authorization": f"Bearer {content.token}"},
            extensions=pinned.extensions,
        )


def validate_gitlab(content: GitlabContent) -> IntegrationValidationResult:
    try:
        resp = _get(content, "/user")
        # /user accepts read_user, which can't reach a project.
        scope_check = _get(content, "/projects?membership=true&per_page=1") if resp.status_code == 200 else None
    except NonPublicDestination as exc:
        logger.warning("GitLab validation refused %s: %s", content.base_url, exc)
        return IntegrationValidationResult(valid=False, error="GitLab must be reachable at a public https address.")
    except Exception as exc:
        logger.warning("GitLab validation could not reach %s: %s", content.base_url, exc)
        return IntegrationValidationResult(valid=False, error="Could not reach GitLab. Check the URL.")

    if resp.status_code == 401:
        return IntegrationValidationResult(valid=False, error="Invalid token")
    if resp.status_code == 403:
        return IntegrationValidationResult(valid=False, error="The token needs the read_api or api scope")
    # A host that isn't GitLab, or a URL pointing at the wrong path, usually has no /api/v4/user.
    if resp.status_code == 404:
        return IntegrationValidationResult(valid=False, error=_NOT_GITLAB)
    if resp.status_code != 200:
        return IntegrationValidationResult(valid=False, error=f"GitLab returned unexpected status {resp.status_code}")
    try:
        body = resp.json()
    except ValueError:
        body = None
    # A reverse proxy or the wrong host can answer 200 with HTML.
    if not isinstance(body, dict) or "username" not in body:
        return IntegrationValidationResult(valid=False, error=_NOT_GITLAB)
    if scope_check is not None and scope_check.status_code == 403:
        return IntegrationValidationResult(valid=False, error="The token needs the read_api or api scope")
    if scope_check is not None and scope_check.status_code != 200:
        status_code = scope_check.status_code
        return IntegrationValidationResult(valid=False, error=f"GitLab returned unexpected status {status_code}")
    name = body.get("name", "")
    return IntegrationValidationResult(valid=True, identity=f"{name} (@{body['username']})")

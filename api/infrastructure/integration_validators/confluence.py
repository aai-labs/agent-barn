import httpx

from api.domains.agents.models import ConfluenceContent
from api.infrastructure.integration_validators.atlassian_utils import (
    get_atlassian_cloud_id,
)
from api.infrastructure.integration_validators.result import IntegrationValidationResult

_TIMEOUT = 10


def validate_confluence(content: ConfluenceContent) -> IntegrationValidationResult:
    base = content.site_url.rstrip("/")

    # Scoped API tokens are still Basic Auth — they just must be sent to the
    # api.atlassian.com gateway (keyed by cloud ID) instead of the site directly.
    # They also only work against the v2 REST API: the legacy v1 endpoint we use
    # for identity (/wiki/rest/api/user/current) isn't in Atlassian's scoped-token
    # allowlist and 401s even with valid credentials, so scoped tokens fall back to
    # a v2 endpoint and report space count instead of a display name.
    if content.use_scoped_token:
        cloud_id, cloud_err = get_atlassian_cloud_id(base)
        if not cloud_id:
            return IntegrationValidationResult(valid=False, error=cloud_err or "Could not resolve Atlassian Cloud ID.")
        gateway_base = f"https://api.atlassian.com/ex/confluence/{cloud_id}"
        endpoint = f"{gateway_base}/wiki/api/v2/spaces"
    else:
        endpoint = f"{base}/wiki/rest/api/user/current"

    try:
        resp = httpx.get(endpoint, auth=(content.email, content.api_token), timeout=_TIMEOUT)
    except Exception as exc:
        return IntegrationValidationResult(valid=False, error=f"Could not reach Confluence: {exc}")

    if resp.status_code == 401:
        return IntegrationValidationResult(valid=False, error="Invalid email or API token")
    if resp.status_code == 403:
        return IntegrationValidationResult(valid=False, error="Account does not have Confluence product access")
    if resp.status_code != 200:
        return IntegrationValidationResult(
            valid=False,
            error=f"Confluence returned unexpected status {resp.status_code}",
        )

    if content.use_scoped_token:
        # /v2/spaces returns paginated results — any 200 means the token is valid.
        # v2 has no "current user" endpoint, so we can't surface a display name.
        data = resp.json()
        count = len(data.get("results", [])) if isinstance(data, dict) else "?"
        site_label = base.replace("https://", "").replace("http://", "")
        return IntegrationValidationResult(
            valid=True,
            identity=f"Service account ({site_label}) · {count} space(s) accessible",
        )

    data = resp.json()
    if data.get("type") == "anonymous":
        return IntegrationValidationResult(valid=False, error="Authentication was not accepted")
    display_name = data.get("displayName", "")
    email = data.get("email", content.email or "")
    identity = f"{display_name} ({email})" if email else display_name
    return IntegrationValidationResult(valid=True, identity=identity)

import httpx

from api.domains.agents.models import ConfluenceContent
from api.infrastructure.integration_validators.result import IntegrationValidationResult

_TIMEOUT = 10


def validate_confluence(content: ConfluenceContent) -> IntegrationValidationResult:
    base = content.site_url.rstrip("/")
    auth = (content.email, content.api_token)
    try:
        resp = httpx.get(
            f"{base}/wiki/rest/api/user/current",
            auth=auth,
            timeout=_TIMEOUT,
        )
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

    data = resp.json()
    if data.get("type") == "anonymous":
        return IntegrationValidationResult(valid=False, error="Authentication was not accepted")

    display_name = data.get("displayName", "")
    email = data.get("email", content.email)
    identity = f"{display_name} ({email})" if email else display_name

    return IntegrationValidationResult(valid=True, identity=identity)

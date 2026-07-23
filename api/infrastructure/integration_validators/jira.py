import httpx

from api.domains.agents.models import JiraContent
from api.infrastructure.integration_validators.result import IntegrationValidationResult

_TIMEOUT = 10


def validate_jira(content: JiraContent) -> IntegrationValidationResult:
    base = content.site_url.rstrip("/")
    auth = (content.email, content.api_token)
    try:
        resp = httpx.get(
            f"{base}/rest/api/3/myself",
            auth=auth,
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return IntegrationValidationResult(valid=False, error=f"Could not reach Jira: {exc}")

    if resp.status_code == 401:
        return IntegrationValidationResult(valid=False, error="Invalid email or API token")
    if resp.status_code == 403:
        return IntegrationValidationResult(valid=False, error="Account does not have Jira product access")
    if resp.status_code != 200:
        return IntegrationValidationResult(valid=False, error=f"Jira returned unexpected status {resp.status_code}")

    data = resp.json()
    if not data.get("active"):
        return IntegrationValidationResult(valid=False, error="Jira account is inactive")

    display_name = data.get("displayName", "")
    email = data.get("emailAddress", "")
    identity = f"{display_name} ({email})" if email else display_name

    return IntegrationValidationResult(valid=True, identity=identity)

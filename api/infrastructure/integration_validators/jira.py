import httpx

from api.domains.agents.models import JiraContent
from api.infrastructure.integration_validators.atlassian_utils import (
    get_atlassian_cloud_id,
)
from api.infrastructure.integration_validators.result import IntegrationValidationResult

_TIMEOUT = 10


def validate_jira(content: JiraContent) -> IntegrationValidationResult:
    base = content.site_url.rstrip("/")

    # If scoped token is selected, we MUST route through the api.atlassian.com gateway.
    # Direct site URL does not accept OAuth scoped tokens on Atlassian Cloud.
    if content.use_scoped_token:
        cloud_id, cloud_err = get_atlassian_cloud_id(base)
        if not cloud_id:
            return IntegrationValidationResult(
                valid=False, error=cloud_err or "Could not resolve Atlassian Cloud ID."
            )
        gateway_base = f"https://api.atlassian.com/ex/jira/{cloud_id}"
        auth = None
        headers = {"Authorization": f"Bearer {content.api_token}"}
        endpoint = f"{gateway_base}/rest/api/3/project"
        is_bearer = True
    else:
        auth = (content.email, content.api_token)
        headers = None
        endpoint = f"{base}/rest/api/3/myself"
        is_bearer = False

    try:
        resp = httpx.get(endpoint, auth=auth, headers=headers, timeout=_TIMEOUT)
    except Exception as exc:
        return IntegrationValidationResult(
            valid=False, error=f"Could not reach Jira: {exc}"
        )

    if resp.status_code == 401:
        return IntegrationValidationResult(
            valid=False,
            error="Invalid API token" if is_bearer else "Invalid email or API token",
        )
    if resp.status_code == 403:
        return IntegrationValidationResult(
            valid=False, error="Account does not have Jira product access"
        )
    if resp.status_code != 200:
        return IntegrationValidationResult(
            valid=False, error=f"Jira returned unexpected status {resp.status_code}"
        )

    if is_bearer:
        # /project returns a list — any 200 means the token is valid and working
        projects = resp.json()
        count = len(projects) if isinstance(projects, list) else "?"
        site_label = base.replace("https://", "").replace("http://", "")
        return IntegrationValidationResult(
            valid=True,
            identity=f"Service account ({site_label}) · {count} project(s) accessible",
        )

    data = resp.json()
    if not data.get("active"):
        return IntegrationValidationResult(
            valid=False, error="Jira account is inactive"
        )
    display_name = data.get("displayName", "")
    email = data.get("emailAddress", content.email or "")
    identity = f"{display_name} ({email})" if email else display_name
    return IntegrationValidationResult(valid=True, identity=identity)

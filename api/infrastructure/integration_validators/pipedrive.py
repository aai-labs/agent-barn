import httpx

from api.domains.agents.models import PipedriveContent
from api.infrastructure.integration_validators.result import IntegrationValidationResult

_TIMEOUT = 10


def validate_pipedrive(content: PipedriveContent) -> IntegrationValidationResult:
    base = f"https://{content.domain}.pipedrive.com" if content.domain else "https://api.pipedrive.com"
    try:
        resp = httpx.get(f"{base}/v1/users/me", headers={"x-api-token": content.api_token}, timeout=_TIMEOUT)
    except Exception as exc:
        return IntegrationValidationResult(valid=False, error=f"Could not reach Pipedrive: {exc}")

    if resp.status_code == 401:
        return IntegrationValidationResult(valid=False, error="Invalid API token")
    if resp.status_code != 200:
        return IntegrationValidationResult(
            valid=False, error=f"Pipedrive returned unexpected status {resp.status_code}"
        )

    data = resp.json().get("data") or {}
    identity = data.get("email") or data.get("name") or ""
    return IntegrationValidationResult(valid=True, identity=identity)

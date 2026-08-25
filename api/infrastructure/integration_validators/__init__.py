from typing import Any

from api.domains.agents.models import SecretProvider
from api.infrastructure.integration_validators.bitbucket import validate_bitbucket
from api.infrastructure.integration_validators.confluence import validate_confluence
from api.infrastructure.integration_validators.github import validate_github
from api.infrastructure.integration_validators.google_workspace import validate_google_workspace
from api.infrastructure.integration_validators.jira import validate_jira
from api.infrastructure.integration_validators.pipedrive import validate_pipedrive
from api.infrastructure.integration_validators.result import IntegrationValidationResult
from api.infrastructure.integration_validators.slack import validate_slack

PROVIDER_VALIDATORS: dict[SecretProvider, Any] = {
    SecretProvider.GITHUB: validate_github,
    SecretProvider.JIRA: validate_jira,
    SecretProvider.CONFLUENCE: validate_confluence,
    SecretProvider.BITBUCKET: validate_bitbucket,
    SecretProvider.GOOGLE_WORKSPACE: validate_google_workspace,
    SecretProvider.SLACK: validate_slack,
    SecretProvider.PIPEDRIVE: validate_pipedrive,
}


def format_validation_result(result: IntegrationValidationResult) -> dict:
    if result.valid and result.missing_scopes:
        validation_status = "warning"
    elif result.valid:
        validation_status = "valid"
    else:
        validation_status = "invalid"
    return {
        "validation_status": validation_status,
        "validation_identity": result.identity,
        "validation_error": result.error,
        "missing_scopes": result.missing_scopes,
    }


__all__ = [
    "PROVIDER_VALIDATORS",
    "IntegrationValidationResult",
    "format_validation_result",
    "validate_bitbucket",
    "validate_confluence",
    "validate_github",
    "validate_google_workspace",
    "validate_jira",
    "validate_pipedrive",
    "validate_slack",
]

import httpx

from api.domains.agents.models import BitbucketContent
from api.infrastructure.integration_validators.result import IntegrationValidationResult

_TIMEOUT = 10
_USER_URL = "https://api.bitbucket.org/2.0/user"


def validate_bitbucket(content: BitbucketContent) -> IntegrationValidationResult:
    try:
        bearer_resp = httpx.get(
            _USER_URL,
            headers={"Authorization": f"Bearer {content.api_token}"},
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return IntegrationValidationResult(
            valid=False, error=f"Could not reach Bitbucket: {exc}"
        )

    # Bearer returning 401 can mean several things:
    # - App password / personal API token → needs Basic auth (email:token)
    # - HTTP access token (workspace/repo scoped) → needs Bearer on a resource endpoint
    # Try Basic auth first; if that also fails, fall back to the scoped token path.
    if bearer_resp.status_code == 401:
        try:
            basic_resp = httpx.get(
                _USER_URL,
                auth=(content.email, content.api_token),
                timeout=_TIMEOUT,
            )
        except Exception as exc:
            return IntegrationValidationResult(
                valid=False, error=f"Could not reach Bitbucket: {exc}"
            )
        if basic_resp.status_code != 401:
            return _handle_user_response(basic_resp, content)
        # Basic auth also failed — treat as a workspace/repo HTTP access token.
        return _validate_scoped_token(content)

    return _handle_user_response(bearer_resp, content)


def _handle_user_response(
    resp: httpx.Response, content: BitbucketContent
) -> IntegrationValidationResult:
    if resp.status_code == 401:
        return IntegrationValidationResult(
            valid=False, error="Invalid API token or credentials"
        )
    if resp.status_code == 403:
        # The token is authenticated but /user requires read:user:bitbucket scope.
        # A scoped API token without that scope still has valid repo/PR access.
        # Use the granted scopes from the 403 body to determine what's missing.
        return _handle_user_scope_denied(resp, content)
    if resp.status_code != 200:
        return IntegrationValidationResult(
            valid=False,
            error=f"Bitbucket returned unexpected status {resp.status_code}",
        )

    data = resp.json()
    display_name = data.get("display_name", "")
    nickname = data.get("nickname", "")
    identity = f"{display_name} (@{nickname})" if nickname else display_name

    missing = _check_repo_read_scope(content, bearer=True)
    return IntegrationValidationResult(
        valid=True, identity=identity, missing_scopes=missing
    )


def _handle_user_scope_denied(
    resp: httpx.Response, content: BitbucketContent
) -> IntegrationValidationResult:
    """Token is valid but missing read:user — check granted scopes for repo/PR access."""
    detail = resp.json().get("error", {}).get("detail", {})
    granted = set(detail.get("granted", []))

    missing: list[str] = []
    if (
        "read:repository:bitbucket" not in granted
        and "write:repository:bitbucket" not in granted
    ):
        missing.append("Repositories (read) scope missing")
    if (
        "read:pullrequest:bitbucket" not in granted
        and "write:pullrequest:bitbucket" not in granted
    ):
        missing.append(
            "Pull requests: Read + Write — needed to read PRs and post review comments"
        )

    identity = f"workspace: {content.workspace}" if content.workspace else content.email
    return IntegrationValidationResult(
        valid=True, identity=identity, missing_scopes=missing
    )


def _validate_scoped_token(content: BitbucketContent) -> IntegrationValidationResult:
    """Validate a workspace/repository access token by probing workspace endpoints."""
    if not content.workspace:
        return IntegrationValidationResult(
            valid=False,
            error="Workspace access token requires a workspace to be configured",
        )

    headers = {"Authorization": f"Bearer {content.api_token}"}
    try:
        resp = httpx.get(
            f"https://api.bitbucket.org/2.0/repositories/{content.workspace}",
            headers=headers,
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return IntegrationValidationResult(
            valid=False, error=f"Could not reach Bitbucket: {exc}"
        )

    if resp.status_code == 401:
        return IntegrationValidationResult(
            valid=False, error="Invalid or expired access token"
        )
    if resp.status_code == 403 and content.repo:
        # Repository-scoped tokens can't list the workspace — probe the specific
        # repo instead before concluding the scope is missing.
        return _validate_repo_scoped_token(content, headers)
    if resp.status_code == 403:
        return IntegrationValidationResult(
            valid=False,
            error="Access token is missing the Repositories (read) scope",
        )
    if resp.status_code not in (200, 404):
        return IntegrationValidationResult(
            valid=False,
            error=f"Bitbucket returned unexpected status {resp.status_code}",
        )

    identity = f"workspace: {content.workspace}"
    missing = _check_pr_scope(content, headers)
    return IntegrationValidationResult(
        valid=True, identity=identity, missing_scopes=missing
    )


def _validate_repo_scoped_token(
    content: BitbucketContent, headers: dict[str, str]
) -> IntegrationValidationResult:
    """Probe the specific repo for tokens scoped below workspace level."""
    try:
        resp = httpx.get(
            f"https://api.bitbucket.org/2.0/repositories/{content.workspace}/{content.repo}",
            headers=headers,
            timeout=_TIMEOUT,
        )
    except Exception as exc:
        return IntegrationValidationResult(
            valid=False, error=f"Could not reach Bitbucket: {exc}"
        )

    if resp.status_code == 401:
        return IntegrationValidationResult(
            valid=False, error="Invalid or expired access token"
        )
    if resp.status_code == 403:
        return IntegrationValidationResult(
            valid=False,
            error="Access token is missing the Repositories (read) scope",
        )
    if resp.status_code not in (200, 404):
        return IntegrationValidationResult(
            valid=False,
            error=f"Bitbucket returned unexpected status {resp.status_code}",
        )

    identity = f"{content.workspace}/{content.repo}"
    missing = _check_pr_scope(content, headers)
    return IntegrationValidationResult(
        valid=True, identity=identity, missing_scopes=missing
    )


def _check_repo_read_scope(
    content: BitbucketContent, *, bearer: bool = True
) -> list[str]:
    if not content.workspace:
        return []
    headers = {"Authorization": f"Bearer {content.api_token}"} if bearer else {}
    try:
        resp = httpx.get(
            f"https://api.bitbucket.org/2.0/repositories/{content.workspace}",
            headers=headers,
            timeout=_TIMEOUT,
        )
        if resp.status_code == 403:
            return ["Repositories (read) scope missing"]
    except Exception:
        pass
    return []


def _check_pr_scope(content: BitbucketContent, headers: dict[str, str]) -> list[str]:
    if not content.workspace or not content.repo:
        return []
    try:
        resp = httpx.get(
            f"https://api.bitbucket.org/2.0/repositories/{content.workspace}/{content.repo}/pullrequests",
            headers=headers,
            timeout=_TIMEOUT,
        )
        if resp.status_code == 403:
            return [
                "Pull requests: Read + Write — needed to read PRs and post review comments"
            ]
    except Exception:
        pass
    return []

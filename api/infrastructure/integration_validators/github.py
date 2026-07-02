import httpx

from api.domains.agents.models import GithubContent
from api.infrastructure.integration_validators.result import IntegrationValidationResult

_TIMEOUT = 10


def validate_github(content: GithubContent) -> IntegrationValidationResult:
    headers = {
        "Authorization": f"Bearer {content.token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    try:
        resp = httpx.get(
            "https://api.github.com/user", headers=headers, timeout=_TIMEOUT
        )
    except Exception as exc:
        return IntegrationValidationResult(
            valid=False, error=f"Could not reach GitHub: {exc}"
        )

    if resp.status_code == 401:
        return IntegrationValidationResult(
            valid=False, error="Token is invalid or expired"
        )
    if resp.status_code != 200:
        return IntegrationValidationResult(
            valid=False, error=f"GitHub returned unexpected status {resp.status_code}"
        )

    identity = resp.json().get("login", "")
    scopes_header = resp.headers.get("X-OAuth-Scopes", "")

    missing: list[str] = []

    if scopes_header:
        # Classic PAT — inspect declared scopes.
        scopes = {s.strip() for s in scopes_header.split(",") if s.strip()}
        if "repo" not in scopes and "public_repo" not in scopes:
            missing.append("repo (or public_repo for public-only repositories)")
        if "read:user" not in scopes and "user" not in scopes:
            missing.append("read:user")
        if "read:org" not in scopes and "admin:org" not in scopes:
            missing.append("read:org (recommended for organisation repositories)")
    else:
        # Fine-grained PAT — probe the configured repo directly.
        missing = _check_fine_grained_repo_access(content, headers)

    return IntegrationValidationResult(
        valid=True, identity=identity, missing_scopes=missing
    )


def _check_fine_grained_repo_access(
    content: GithubContent, headers: dict[str, str]
) -> list[str]:
    if not content.owner or not content.repo:
        return []
    missing: list[str] = []

    # Check repository contents access.
    try:
        resp = httpx.get(
            f"https://api.github.com/repos/{content.owner}/{content.repo}",
            headers=headers,
            timeout=_TIMEOUT,
        )
        if resp.status_code == 403:
            accepted = resp.headers.get("X-Accepted-GitHub-Permissions", "")
            detail = "contents=read" if not accepted else accepted
            missing.append(f"Repository access — needs: {detail}")
        elif resp.status_code == 404:
            missing.append(
                "Repository contents read access (or repository does not exist)"
            )
    except Exception:
        pass

    # Check pull request read access.
    try:
        pr_resp = httpx.get(
            f"https://api.github.com/repos/{content.owner}/{content.repo}/pulls",
            headers=headers,
            timeout=_TIMEOUT,
        )
        if pr_resp.status_code == 403:
            missing.append(
                "Pull requests: Read + Write — needed to list PRs and post review comments"
            )
    except Exception:
        pass

    return missing

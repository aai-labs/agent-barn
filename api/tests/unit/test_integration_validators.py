"""
TDD: failing tests for api/infrastructure/integration_validators/*.
Run these first — they should all fail until the implementation exists.
"""

from unittest.mock import patch

import httpx

from api.domains.agents.models import (
    BitbucketContent,
    ConfluenceContent,
    GithubContent,
    GoogleWorkspaceContent,
    JiraContent,
    PipedriveContent,
    SlackContent,
)
from api.infrastructure.integration_validators.bitbucket import validate_bitbucket
from api.infrastructure.integration_validators.confluence import validate_confluence
from api.infrastructure.integration_validators.github import validate_github
from api.infrastructure.integration_validators.google_workspace import validate_google_workspace
from api.infrastructure.integration_validators.jira import validate_jira
from api.infrastructure.integration_validators.pipedrive import validate_pipedrive
from api.infrastructure.integration_validators.result import IntegrationValidationResult
from api.infrastructure.integration_validators.slack import validate_slack

# ── fixtures ──────────────────────────────────────────────────────────────────

_REQUEST = httpx.Request("GET", "https://example.com")


def _resp(body: dict | list, *, status: int = 200, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers or {}, request=_REQUEST)


def _connect_error() -> httpx.ConnectError:
    return httpx.ConnectError("connection refused", request=_REQUEST)


_GH = GithubContent(token="ghp_test", owner="acme", repos=["backend"], org="acme-org")
_JIRA = JiraContent(site_url="https://acme.atlassian.net", email="alice@acme.com", api_token="jira-tok")
_JIRA_SCOPED = JiraContent(
    site_url="https://acme.atlassian.net",
    email="svc-account@acme.com",
    api_token="scoped-tok",
    use_scoped_token=True,
)
_CONFLUENCE = ConfluenceContent(site_url="https://acme.atlassian.net", email="alice@acme.com", api_token="conf-tok")
_CONFLUENCE_SCOPED = ConfluenceContent(
    site_url="https://acme.atlassian.net",
    email="svc-account@acme.com",
    api_token="scoped-tok",
    use_scoped_token=True,
)
_BB = BitbucketContent(workspace="acme", repos=["backend"], email="alice@acme.com", api_token="bb-tok")
_SLACK = SlackContent(token="xoxb-test-token")
_PD = PipedriveContent(api_token="pd-tok")
_PD_WITH_DOMAIN = PipedriveContent(api_token="pd-tok", domain="aai-labs")

# ── IntegrationValidationResult ───────────────────────────────────────────────


def test_result_valid_defaults():
    r = IntegrationValidationResult(valid=True)
    assert r.valid is True
    assert r.identity is None
    assert r.missing_scopes == []
    assert r.error is None


def test_result_invalid_with_error():
    r = IntegrationValidationResult(valid=False, error="bad token")
    assert r.valid is False
    assert r.error == "bad token"


def test_result_warning_has_missing_scopes():
    r = IntegrationValidationResult(valid=True, missing_scopes=["read:org"])
    assert r.missing_scopes == ["read:org"]


# ── GitHub ────────────────────────────────────────────────────────────────────

_GH_MOD = "api.infrastructure.integration_validators.github.httpx.get"


def test_github_classic_pat_all_scopes_present():
    user_resp = _resp({"login": "alice"}, headers={"X-OAuth-Scopes": "repo, read:user, read:org"})
    with patch(_GH_MOD, return_value=user_resp):
        result = validate_github(_GH)

    assert result.valid is True
    assert result.identity == "alice"
    assert result.missing_scopes == []
    assert result.error is None


def test_github_classic_pat_missing_repo_scope():
    user_resp = _resp({"login": "alice"}, headers={"X-OAuth-Scopes": "read:user, read:org"})
    with patch(_GH_MOD, return_value=user_resp):
        result = validate_github(_GH)

    assert result.valid is True
    assert any("repo" in s.lower() for s in result.missing_scopes)


def test_github_classic_pat_missing_read_user_scope():
    user_resp = _resp({"login": "alice"}, headers={"X-OAuth-Scopes": "repo, read:org"})
    with patch(_GH_MOD, return_value=user_resp):
        result = validate_github(_GH)

    assert result.valid is True
    assert any("read:user" in s for s in result.missing_scopes)


def test_github_classic_pat_missing_read_org_scope():
    user_resp = _resp({"login": "alice"}, headers={"X-OAuth-Scopes": "repo, read:user"})
    with patch(_GH_MOD, return_value=user_resp):
        result = validate_github(_GH)

    assert result.valid is True
    assert any("read:org" in s for s in result.missing_scopes)


def test_github_classic_pat_broad_user_scope_covers_read_user():
    """'user' scope is a superset of read:user — should not warn."""
    user_resp = _resp({"login": "alice"}, headers={"X-OAuth-Scopes": "repo, user, read:org"})
    with patch(_GH_MOD, return_value=user_resp):
        result = validate_github(_GH)

    assert result.valid is True
    assert not any("read:user" in s for s in result.missing_scopes)


def test_github_fine_grained_pat_repo_accessible():
    """Fine-grained PATs have no X-OAuth-Scopes header; test the repo and pulls endpoints."""
    user_resp = _resp({"login": "alice"})  # no X-OAuth-Scopes header
    repo_resp = _resp({"full_name": "acme/backend"})
    pulls_resp = _resp([])

    with patch(_GH_MOD, side_effect=[user_resp, repo_resp, pulls_resp]):
        result = validate_github(_GH)

    assert result.valid is True
    assert result.missing_scopes == []


def test_github_fine_grained_pat_repo_access_denied():
    user_resp = _resp({"login": "alice"})
    repo_resp = _resp(
        {"message": "forbidden"},
        status=403,
        headers={"X-Accepted-GitHub-Permissions": "contents=read"},
    )
    pulls_resp = _resp([])

    with patch(_GH_MOD, side_effect=[user_resp, repo_resp, pulls_resp]):
        result = validate_github(_GH)

    assert result.valid is True
    assert len(result.missing_scopes) > 0
    assert any("contents=read" in s for s in result.missing_scopes)


def test_github_fine_grained_pat_pr_access_denied():
    user_resp = _resp({"login": "alice"})
    repo_resp = _resp({"full_name": "acme/backend"})
    pulls_resp = _resp({"message": "forbidden"}, status=403)

    with patch(_GH_MOD, side_effect=[user_resp, repo_resp, pulls_resp]):
        result = validate_github(_GH)

    assert result.valid is True
    assert any("Pull requests" in s for s in result.missing_scopes)


def test_github_invalid_token_401():
    with patch(_GH_MOD, return_value=_resp({}, status=401)):
        result = validate_github(_GH)

    assert result.valid is False
    assert result.error is not None
    assert "invalid" in result.error.lower() or "expired" in result.error.lower()


def test_github_unexpected_status_returns_error():
    with patch(_GH_MOD, return_value=_resp({}, status=500)):
        result = validate_github(_GH)

    assert result.valid is False
    assert "500" in (result.error or "")


def test_github_network_error_returns_error():
    with patch(_GH_MOD, side_effect=_connect_error()):
        result = validate_github(_GH)

    assert result.valid is False
    assert result.error is not None
    assert "github" in result.error.lower()


def test_github_fine_grained_empty_repos_skips_repo_probe():
    """Fine-grained PAT with an owner but no repos configured — skip the repo probe."""
    no_repos = GithubContent(token="ghp_fine", owner="acme", repos=[], org="acme")
    user_resp = _resp({"login": "alice"})  # no X-OAuth-Scopes

    with patch(_GH_MOD, side_effect=[user_resp]) as mock_get:
        result = validate_github(no_repos)

    assert result.valid is True
    assert result.missing_scopes == []
    assert mock_get.call_count == 1  # only /user, no /repos probe


def test_github_fine_grained_multiple_repos_aggregates_missing_scopes():
    """Two configured repos: one denied (403), one missing (404) — both surface, valid stays True."""
    multi_repo = GithubContent(token="ghp_fine", owner="acme", repos=["backend", "frontend"], org="acme")
    user_resp = _resp({"login": "alice"})
    repo1_resp = _resp(
        {"message": "forbidden"},
        status=403,
        headers={"X-Accepted-GitHub-Permissions": "contents=read"},
    )
    pulls1_resp = _resp([])
    repo2_resp = _resp({"message": "not found"}, status=404)
    pulls2_resp = _resp([])

    with patch(
        _GH_MOD,
        side_effect=[user_resp, repo1_resp, pulls1_resp, repo2_resp, pulls2_resp],
    ):
        result = validate_github(multi_repo)

    assert result.valid is True
    assert any("backend" in s for s in result.missing_scopes)
    assert any("frontend" in s for s in result.missing_scopes)


# ── Jira ──────────────────────────────────────────────────────────────────────

_JIRA_MOD = "api.infrastructure.integration_validators.jira.httpx.get"


def test_jira_valid_credentials_returns_identity():
    body = {
        "displayName": "Alice",
        "emailAddress": "alice@acme.com",
        "active": True,
        "accountType": "atlassian",
    }
    with patch(_JIRA_MOD, return_value=_resp(body)):
        result = validate_jira(_JIRA)

    assert result.valid is True
    assert "Alice" in (result.identity or "")
    assert "alice@acme.com" in (result.identity or "")
    assert result.error is None


def test_jira_invalid_credentials_401():
    with patch(_JIRA_MOD, return_value=_resp({}, status=401)):
        result = validate_jira(_JIRA)

    assert result.valid is False
    assert result.error is not None
    assert "invalid" in result.error.lower() or "token" in result.error.lower()


def test_jira_no_product_access_403():
    with patch(_JIRA_MOD, return_value=_resp({}, status=403)):
        result = validate_jira(_JIRA)

    assert result.valid is False
    assert result.error is not None
    assert "access" in result.error.lower() or "jira" in result.error.lower()


def test_jira_inactive_account_returns_error():
    body = {"displayName": "Alice", "emailAddress": "alice@acme.com", "active": False}
    with patch(_JIRA_MOD, return_value=_resp(body)):
        result = validate_jira(_JIRA)

    assert result.valid is False
    assert result.error is not None
    assert "inactive" in result.error.lower()


def test_jira_unexpected_status_returns_error():
    with patch(_JIRA_MOD, return_value=_resp({}, status=502)):
        result = validate_jira(_JIRA)

    assert result.valid is False
    assert "502" in (result.error or "")


def test_jira_network_error_returns_error():
    with patch(_JIRA_MOD, side_effect=_connect_error()):
        result = validate_jira(_JIRA)

    assert result.valid is False
    assert result.error is not None
    assert "jira" in result.error.lower()


_JIRA_CLOUD_ID_MOD = "api.infrastructure.integration_validators.jira.get_atlassian_cloud_id"


def test_jira_scoped_token_valid_returns_identity():
    """Scoped token: cloud_id resolved, Basic Auth call via gateway succeeds — valid."""
    body = {
        "displayName": "Service Bot",
        "emailAddress": "svc-account@acme.com",
        "active": True,
    }
    with (
        patch(_JIRA_CLOUD_ID_MOD, return_value=("cloud-abc", None)),
        patch(_JIRA_MOD, return_value=_resp(body)),
    ):
        result = validate_jira(_JIRA_SCOPED)

    assert result.valid is True
    assert "Service Bot" in (result.identity or "")
    assert "svc-account@acme.com" in (result.identity or "")
    assert result.error is None


def test_jira_scoped_token_cloud_id_fetch_fails_hard_fails():
    """Scoped token: cloud_id resolution fails — validation must hard fail immediately."""
    with patch(_JIRA_CLOUD_ID_MOD, return_value=(None, "Network error fetching cloud ID")):
        result = validate_jira(_JIRA_SCOPED)

    assert result.valid is False
    assert result.error is not None


def test_jira_scoped_token_401_returns_error():
    """Scoped token: cloud_id OK but gateway call returns 401 — invalid token."""
    with (
        patch(_JIRA_CLOUD_ID_MOD, return_value=("cloud-abc", None)),
        patch(_JIRA_MOD, return_value=_resp({}, status=401)),
    ):
        result = validate_jira(_JIRA_SCOPED)

    assert result.valid is False
    assert "invalid" in (result.error or "").lower() or "token" in (result.error or "").lower()


# ── Confluence ────────────────────────────────────────────────────────────────

_CONF_MOD = "api.infrastructure.integration_validators.confluence.httpx.get"


def test_confluence_valid_credentials_returns_identity():
    body = {"type": "known", "displayName": "Alice", "email": "alice@acme.com"}
    with patch(_CONF_MOD, return_value=_resp(body)):
        result = validate_confluence(_CONFLUENCE)

    assert result.valid is True
    assert "Alice" in (result.identity or "")
    assert "alice@acme.com" in (result.identity or "")
    assert result.error is None


def test_confluence_anonymous_type_means_auth_rejected():
    body = {"type": "anonymous"}
    with patch(_CONF_MOD, return_value=_resp(body)):
        result = validate_confluence(_CONFLUENCE)

    assert result.valid is False
    assert result.error is not None
    assert "auth" in result.error.lower() or "anonymous" in result.error.lower()


def test_confluence_invalid_credentials_401():
    with patch(_CONF_MOD, return_value=_resp({}, status=401)):
        result = validate_confluence(_CONFLUENCE)

    assert result.valid is False
    assert result.error is not None


def test_confluence_no_product_access_403():
    with patch(_CONF_MOD, return_value=_resp({}, status=403)):
        result = validate_confluence(_CONFLUENCE)

    assert result.valid is False
    assert result.error is not None
    assert "confluence" in result.error.lower() or "access" in result.error.lower()


def test_confluence_unexpected_status_returns_error():
    with patch(_CONF_MOD, return_value=_resp({}, status=503)):
        result = validate_confluence(_CONFLUENCE)

    assert result.valid is False
    assert "503" in (result.error or "")


def test_confluence_network_error_returns_error():
    with patch(_CONF_MOD, side_effect=_connect_error()):
        result = validate_confluence(_CONFLUENCE)

    assert result.valid is False
    assert result.error is not None
    assert "confluence" in result.error.lower()


_CONF_CLOUD_ID_MOD = "api.infrastructure.integration_validators.confluence.get_atlassian_cloud_id"


def test_confluence_scoped_token_valid_returns_identity():
    """Scoped token: cloud_id resolved, Basic Auth call to the v2 gateway succeeds — valid with space count."""
    spaces = {"results": [{"key": "TEAM"}, {"key": "DOCS"}, {"key": "ENG"}]}
    with (
        patch(_CONF_CLOUD_ID_MOD, return_value=("cloud-abc", None)),
        patch(_CONF_MOD, return_value=_resp(spaces)),
    ):
        result = validate_confluence(_CONFLUENCE_SCOPED)

    assert result.valid is True
    assert "acme.atlassian.net" in (result.identity or "")
    assert "3" in (result.identity or "")
    assert result.error is None


def test_confluence_scoped_token_cloud_id_fetch_fails_hard_fails():
    """Scoped token: cloud_id resolution fails — validation must hard fail immediately."""
    with patch(_CONF_CLOUD_ID_MOD, return_value=(None, "Network error fetching cloud ID")):
        result = validate_confluence(_CONFLUENCE_SCOPED)

    assert result.valid is False
    assert result.error is not None


def test_confluence_scoped_token_401_returns_error():
    """Scoped token: cloud_id OK but gateway call returns 401 — invalid token."""
    with (
        patch(_CONF_CLOUD_ID_MOD, return_value=("cloud-abc", None)),
        patch(_CONF_MOD, return_value=_resp({}, status=401)),
    ):
        result = validate_confluence(_CONFLUENCE_SCOPED)

    assert result.valid is False
    assert "invalid" in (result.error or "").lower() or "token" in (result.error or "").lower()


# ── Bitbucket ─────────────────────────────────────────────────────────────────

_BB_MOD = "api.infrastructure.integration_validators.bitbucket.httpx.get"

_BB_USER_BODY = {
    "type": "user",
    "display_name": "Alice",
    "nickname": "alice",
    "account_id": "abc123",
    "uuid": "{uuid}",
}


def test_bitbucket_valid_bearer_token_returns_identity():
    user_resp = _resp(_BB_USER_BODY)
    repo_resp = _resp({"values": []})  # workspace repos accessible

    with patch(_BB_MOD, side_effect=[user_resp, repo_resp]):
        result = validate_bitbucket(_BB)

    assert result.valid is True
    assert "Alice" in (result.identity or "")
    assert result.missing_scopes == []
    assert result.error is None


def test_bitbucket_falls_back_to_basic_auth_when_bearer_fails():
    """If Bearer auth returns 401, retry with Basic auth (email:api_token)."""
    bearer_fail = _resp({}, status=401)
    basic_ok = _resp(_BB_USER_BODY)
    repo_resp = _resp({"values": []})

    with patch(_BB_MOD, side_effect=[bearer_fail, basic_ok, repo_resp]) as mock_get:
        result = validate_bitbucket(_BB)

    assert result.valid is True
    # Second call must use Basic auth — verify the call was made differently
    calls = mock_get.call_args_list
    assert len(calls) >= 2


def test_bitbucket_missing_repo_read_scope_warns():
    """Workspace repo list returns 403 → missing_scopes includes repository read."""
    user_resp = _resp(_BB_USER_BODY)
    repo_403 = _resp({"type": "error"}, status=403)

    with patch(_BB_MOD, side_effect=[user_resp, repo_403]):
        result = validate_bitbucket(_BB)

    assert result.valid is True
    assert len(result.missing_scopes) > 0
    assert any("repositor" in s.lower() for s in result.missing_scopes)


def test_bitbucket_invalid_token_both_auth_methods_fail():
    with patch(_BB_MOD, return_value=_resp({}, status=401)):
        result = validate_bitbucket(_BB)

    assert result.valid is False
    assert result.error is not None
    assert "invalid" in result.error.lower() or "token" in result.error.lower()


def test_bitbucket_403_on_user_with_repo_scopes_is_valid():
    """Token missing read:user but has repo scopes — treat as valid with no missing scopes."""
    body = {
        "type": "error",
        "error": {
            "message": "Your credentials lack one or more required privilege scopes.",
            "detail": {
                "required": ["read:user:bitbucket"],
                "granted": [
                    "read:repository:bitbucket",
                    "read:pullrequest:bitbucket",
                    "write:pullrequest:bitbucket",
                ],
            },
        },
    }
    with patch(_BB_MOD, return_value=_resp(body, status=403)):
        result = validate_bitbucket(_BB)

    assert result.valid is True
    assert result.missing_scopes == []


def test_bitbucket_403_on_user_missing_repo_scope():
    """Token missing read:user AND repo scopes — report missing repo scope."""
    body = {
        "type": "error",
        "error": {
            "message": "Your credentials lack one or more required privilege scopes.",
            "detail": {"required": ["read:user:bitbucket"], "granted": []},
        },
    }
    with patch(_BB_MOD, return_value=_resp(body, status=403)):
        result = validate_bitbucket(_BB)

    assert result.valid is True
    assert any("repositor" in s.lower() for s in result.missing_scopes)


def test_bitbucket_network_error_returns_error():
    with patch(_BB_MOD, side_effect=_connect_error()):
        result = validate_bitbucket(_BB)

    assert result.valid is False
    assert result.error is not None
    assert "bitbucket" in result.error.lower()


def test_bitbucket_identity_includes_nickname():
    user_resp = _resp({**_BB_USER_BODY, "nickname": "al"})
    repo_resp = _resp({"values": []})

    with patch(_BB_MOD, side_effect=[user_resp, repo_resp]):
        result = validate_bitbucket(_BB)

    assert result.valid is True
    assert "al" in (result.identity or "")


def test_bitbucket_no_workspace_skips_repo_check():
    """If workspace is empty, skip the repo read scope probe."""
    no_workspace = BitbucketContent(workspace="", repos=["be"], email="a@b.com", api_token="t")
    user_resp = _resp(_BB_USER_BODY)

    with patch(_BB_MOD, side_effect=[user_resp]) as mock_get:
        result = validate_bitbucket(no_workspace)

    assert result.valid is True
    assert result.missing_scopes == []
    assert mock_get.call_count == 1  # only /user, no /repositories probe


_BB_SCOPED_401 = {
    "type": "error",
    "error": {"message": "Token is invalid, expired, or not supported for this endpoint."},
}


_BASIC_401 = _resp({}, status=401)


def test_bitbucket_scoped_token_valid():
    """Workspace HTTP access token: Bearer fails, Basic fails, Bearer on /repositories works."""
    bearer_fail = _resp(_BB_SCOPED_401, status=401)
    repos_ok = _resp({"values": []})
    pr_ok = _resp({"values": []})

    with patch(_BB_MOD, side_effect=[bearer_fail, _BASIC_401, repos_ok, pr_ok]):
        result = validate_bitbucket(_BB)

    assert result.valid is True
    assert result.missing_scopes == []


def test_bitbucket_scoped_token_missing_repo_scope():
    """Scoped token with no read scope: workspace listing AND specific repo both denied."""
    bearer_fail = _resp(_BB_SCOPED_401, status=401)
    workspace_403 = _resp({"type": "error"}, status=403)
    repo_403 = _resp({"type": "error"}, status=403)

    with patch(_BB_MOD, side_effect=[bearer_fail, _BASIC_401, workspace_403, repo_403]):
        result = validate_bitbucket(_BB)

    assert result.valid is False
    assert result.error is not None
    assert "repositor" in result.error.lower()


def test_bitbucket_scoped_token_missing_pr_scope():
    """Workspace access token: repos OK but pull requests scope missing."""
    bearer_fail = _resp(_BB_SCOPED_401, status=401)
    repos_ok = _resp({"values": []})
    pr_403 = _resp({"type": "error"}, status=403)

    with patch(_BB_MOD, side_effect=[bearer_fail, _BASIC_401, repos_ok, pr_403]):
        result = validate_bitbucket(_BB)

    assert result.valid is True
    assert any("pull request" in s.lower() for s in result.missing_scopes)


def test_bitbucket_repo_scoped_token_valid():
    """Repository-scoped token: workspace listing returns 403, specific repo probe succeeds."""
    bearer_fail = _resp(_BB_SCOPED_401, status=401)
    workspace_403 = _resp({"type": "error"}, status=403)
    repo_ok = _resp({"full_name": "acme/backend"})
    pr_ok = _resp({"values": []})

    with patch(_BB_MOD, side_effect=[bearer_fail, _BASIC_401, workspace_403, repo_ok, pr_ok]):
        result = validate_bitbucket(_BB)

    assert result.valid is True
    assert result.missing_scopes == []


def test_bitbucket_scoped_token_no_workspace_returns_error():
    """Scoped token with no workspace configured cannot be validated."""
    no_workspace = BitbucketContent(workspace="", repos=["be"], email="a@b.com", api_token="t")
    bearer_fail = _resp(_BB_SCOPED_401, status=401)

    with patch(_BB_MOD, side_effect=[bearer_fail]):
        result = validate_bitbucket(no_workspace)

    assert result.valid is False
    assert result.error is not None


def test_bitbucket_scoped_token_no_repos_skips_repo_probe():
    """Scoped token, workspace listing denied, zero repos configured — nothing left to
    fall back to, so treat as missing the read scope rather than probing anything."""
    no_repos = BitbucketContent(workspace="acme", repos=[], email="a@b.com", api_token="t")
    bearer_fail = _resp(_BB_SCOPED_401, status=401)
    workspace_403 = _resp({"type": "error"}, status=403)

    with patch(_BB_MOD, side_effect=[bearer_fail, _BASIC_401, workspace_403]):
        result = validate_bitbucket(no_repos)

    assert result.valid is False
    assert result.error is not None


def test_bitbucket_scoped_token_multiple_repos_partial_failure_still_valid():
    """One of two configured repos succeeds — token is valid; the failing repo shows
    up as a missing scope instead of failing validation outright."""
    multi_repo = BitbucketContent(workspace="acme", repos=["backend", "frontend"], email="a@b.com", api_token="t")
    bearer_fail = _resp(_BB_SCOPED_401, status=401)
    workspace_403 = _resp({"type": "error"}, status=403)
    repo1_ok = _resp({"full_name": "acme/backend"})
    repo2_403 = _resp({"type": "error"}, status=403)
    pr1_ok = _resp({"values": []})

    with patch(
        _BB_MOD,
        side_effect=[
            bearer_fail,
            _BASIC_401,
            workspace_403,
            repo1_ok,
            repo2_403,
            pr1_ok,
        ],
    ):
        result = validate_bitbucket(multi_repo)

    assert result.valid is True
    assert any("frontend" in s for s in result.missing_scopes)


def test_bitbucket_scoped_token_all_repos_fail_returns_invalid():
    """All configured repos fail the probe — no proof of access at all, so invalid."""
    multi_repo = BitbucketContent(workspace="acme", repos=["backend", "frontend"], email="a@b.com", api_token="t")
    bearer_fail = _resp(_BB_SCOPED_401, status=401)
    workspace_403 = _resp({"type": "error"}, status=403)
    repo1_403 = _resp({"type": "error"}, status=403)
    repo2_403 = _resp({"type": "error"}, status=403)

    with patch(
        _BB_MOD,
        side_effect=[bearer_fail, _BASIC_401, workspace_403, repo1_403, repo2_403],
    ):
        result = validate_bitbucket(multi_repo)

    assert result.valid is False
    assert result.error is not None


def test_github_fine_grained_no_owner_skips_repo_probe():
    """Fine-grained PAT with no owner/repo configured — skip the repo probe."""
    no_repo = GithubContent(token="ghp_fine", owner="", repos=[], org="")
    user_resp = _resp({"login": "alice"})  # no X-OAuth-Scopes

    with patch(_GH_MOD, side_effect=[user_resp]) as mock_get:
        result = validate_github(no_repo)

    assert result.valid is True
    assert result.missing_scopes == []
    assert mock_get.call_count == 1  # only /user, no /repos probe


def test_confluence_identity_falls_back_to_content_email_when_absent():
    """Confluence may omit 'email' from the response body; fall back to the stored email."""
    body = {"type": "known", "displayName": "Alice"}  # no email field
    with patch(_CONF_MOD, return_value=_resp(body)):
        result = validate_confluence(_CONFLUENCE)

    assert result.valid is True
    assert _CONFLUENCE.email in (result.identity or "")


# ── Slack ─────────────────────────────────────────────────────────────────────

_SLACK_MOD = "api.infrastructure.integration_validators.slack.httpx.post"


def test_slack_valid_token_returns_identity():
    ok_body = {"ok": True, "team": "AAI Labs", "user": "test-bot", "team_id": "T1", "user_id": "U1"}
    with patch(_SLACK_MOD, return_value=_resp(ok_body)):
        result = validate_slack(_SLACK)

    assert result.valid is True
    assert result.identity == "test-bot @ AAI Labs"
    assert result.error is None


def test_slack_invalid_auth_returns_error():
    with patch(_SLACK_MOD, return_value=_resp({"ok": False, "error": "invalid_auth"})):
        result = validate_slack(_SLACK)

    assert result.valid is False
    assert "invalid" in (result.error or "").lower()


def test_slack_missing_scope_returns_error():
    with patch(_SLACK_MOD, return_value=_resp({"ok": False, "error": "missing_scope"})):
        result = validate_slack(_SLACK)

    assert result.valid is False
    assert "missing_scope" in (result.error or "")


def test_slack_unexpected_status_returns_error():
    with patch(_SLACK_MOD, return_value=_resp({}, status=500)):
        result = validate_slack(_SLACK)

    assert result.valid is False
    assert "500" in (result.error or "")


def test_slack_network_error_returns_error():
    with patch(_SLACK_MOD, side_effect=_connect_error()):
        result = validate_slack(_SLACK)

    assert result.valid is False
    assert result.error is not None
    assert "slack" in result.error.lower()
    assert result.identity is None


# ── Pipedrive ─────────────────────────────────────────────────────────────────

_PD_MOD = "api.infrastructure.integration_validators.pipedrive.httpx.get"


def test_pipedrive_valid_token_returns_identity():
    with patch(_PD_MOD, return_value=_resp({"success": True, "data": {"email": "alice@acme.com"}})) as mock_get:
        result = validate_pipedrive(_PD)

    assert result.valid is True
    assert result.identity == "alice@acme.com"
    mock_get.assert_called_once_with(
        "https://api.pipedrive.com/v1/users/me",
        headers={"x-api-token": "pd-tok"},
        timeout=10,
    )


def test_pipedrive_with_domain_hits_tenant_hostname():
    with patch(_PD_MOD, return_value=_resp({"success": True, "data": {"email": "alice@acme.com"}})) as mock_get:
        result = validate_pipedrive(_PD_WITH_DOMAIN)

    assert result.valid is True
    mock_get.assert_called_once_with(
        "https://aai-labs.pipedrive.com/v1/users/me",
        headers={"x-api-token": "pd-tok"},
        timeout=10,
    )


def test_pipedrive_invalid_token_401():
    with patch(_PD_MOD, return_value=_resp({"success": False, "error": "invalid api_token"}, status=401)):
        result = validate_pipedrive(_PD)

    assert result.valid is False
    assert result.error is not None
    assert "invalid" in result.error.lower()


def test_pipedrive_unexpected_status_returns_error():
    with patch(_PD_MOD, return_value=_resp({}, status=500)):
        result = validate_pipedrive(_PD)

    assert result.valid is False
    assert "500" in (result.error or "")


def test_pipedrive_network_error_returns_error():
    with patch(_PD_MOD, side_effect=_connect_error()):
        result = validate_pipedrive(_PD)

    assert result.valid is False
    assert result.error is not None
    assert "pipedrive" in result.error.lower()


# ── Google Workspace (gog) ────────────────────────────────────────────────────

_GWS_TOKEN_MOD = "api.infrastructure.integration_validators.google_workspace.httpx.post"
_GWS_USERINFO_MOD = "api.infrastructure.integration_validators.google_workspace.httpx.get"

_GWS_SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar",
]
_GWS = GoogleWorkspaceContent(
    email="alice@example.com",
    services=["gmail", "calendar"],
    scopes=_GWS_SCOPES,
    refresh_token="rt-123",
    client_id="client-id",
    client_secret="client-secret",
)


def _gws_token_ok(scope: str | None = None) -> dict:
    return {
        "access_token": "at-123",
        "scope": " ".join(_GWS_SCOPES) if scope is None else scope,
        "token_type": "Bearer",
    }


def test_google_workspace_valid_refresh_token_returns_identity():
    with (
        patch(_GWS_TOKEN_MOD, return_value=_resp(_gws_token_ok())),
        patch(_GWS_USERINFO_MOD, return_value=_resp({"email": "alice@example.com"})),
    ):
        result = validate_google_workspace(_GWS)

    assert result.valid is True
    assert result.identity == "alice@example.com"
    assert result.missing_scopes == []
    assert result.error is None


def test_google_workspace_missing_client_credentials_returns_error():
    no_client = GoogleWorkspaceContent(
        email="alice@example.com",
        services=["gmail"],
        refresh_token="rt-123",
    )
    with patch(_GWS_TOKEN_MOD) as mock_post:
        result = validate_google_workspace(no_client)

    assert result.valid is False
    assert "configured" in (result.error or "").lower()
    mock_post.assert_not_called()


def test_google_workspace_invalid_grant_mentions_reconnect_and_testing_status():
    """Testing-status OAuth apps expire refresh tokens weekly — the likeliest cause."""
    with patch(_GWS_TOKEN_MOD, return_value=_resp({"error": "invalid_grant"}, status=400)):
        result = validate_google_workspace(_GWS)

    assert result.valid is False
    assert "reconnect" in (result.error or "").lower()
    assert "testing" in (result.error or "").lower()


def test_google_workspace_reports_scopes_revoked_after_consent():
    # The user trimmed the grant at myaccount.google.com; gog will fail on calendar.
    narrowed = _gws_token_ok(scope="https://www.googleapis.com/auth/gmail.readonly")
    with (
        patch(_GWS_TOKEN_MOD, return_value=_resp(narrowed)),
        patch(_GWS_USERINFO_MOD, return_value=_resp({"email": "alice@example.com"})),
    ):
        result = validate_google_workspace(_GWS)

    assert result.valid is True  # warning, not a hard failure
    assert result.missing_scopes == ["https://www.googleapis.com/auth/calendar"]


def test_google_workspace_flags_identity_drift():
    # A refresh token that now resolves to a different account would silently act as
    # the wrong user, and gog's stored token is keyed by the recorded email.
    with (
        patch(_GWS_TOKEN_MOD, return_value=_resp(_gws_token_ok())),
        patch(_GWS_USERINFO_MOD, return_value=_resp({"email": "bob@example.com"})),
    ):
        result = validate_google_workspace(_GWS)

    assert result.valid is False
    assert result.identity == "bob@example.com"
    assert "bob@example.com" in (result.error or "")


def test_google_workspace_identity_comparison_ignores_case():
    with (
        patch(_GWS_TOKEN_MOD, return_value=_resp(_gws_token_ok())),
        patch(_GWS_USERINFO_MOD, return_value=_resp({"email": "Alice@Example.com"})),
    ):
        result = validate_google_workspace(_GWS)

    assert result.valid is True


def test_google_workspace_falls_back_to_stored_email_when_userinfo_fails():
    with (
        patch(_GWS_TOKEN_MOD, return_value=_resp(_gws_token_ok())),
        patch(_GWS_USERINFO_MOD, side_effect=_connect_error()),
    ):
        result = validate_google_workspace(_GWS)

    assert result.valid is True
    assert result.identity == "alice@example.com"


def test_google_workspace_network_error_returns_error():
    with patch(_GWS_TOKEN_MOD, side_effect=_connect_error()):
        result = validate_google_workspace(_GWS)

    assert result.valid is False
    assert "google" in (result.error or "").lower()


def test_google_workspace_unexpected_status_returns_error():
    with patch(_GWS_TOKEN_MOD, return_value=_resp({}, status=500)):
        result = validate_google_workspace(_GWS)

    assert result.valid is False
    assert "500" in (result.error or "")

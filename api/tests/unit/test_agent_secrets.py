import json

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from api.domains.agents.models import (
    PROVIDER_DISPLAY_NAMES,
    AgentCreate,
    BitbucketContent,
    FirecrawlContent,
    GithubContent,
    GoogleWorkspaceContent,
    JiraContent,
    PipedriveContent,
    SecretProvider,
    SlackContent,
    ZohoMailContent,
    decrypt_content,
    encrypt_content,
    validate_content,
)
from api.infrastructure.crypto import encrypt_token

_KEY = Fernet.generate_key().decode()

_BASE_CREATE = {
    "name": "Agent",
    "slack_bot_token": "xoxb-x",
    "slack_app_token": "xapp-x",
    "template_key": "test-template",
}

_JIRA = {
    "site_url": "https://x.atlassian.net",
    "email": "a@b.com",
    "api_token": "secret-token",
}

_GITHUB_BASE = {"token": "ghp_x", "owner": "acme", "org": "acme"}

_BITBUCKET_BASE = {"workspace": "acme", "email": "a@b.com", "api_token": "secret-token"}


def test_validate_content_parses_known_provider():
    content = validate_content(SecretProvider.JIRA, _JIRA)
    assert isinstance(content, JiraContent)
    assert content.api_token == "secret-token"


def test_validate_content_rejects_missing_required_field():
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.JIRA, {"site_url": "https://x", "email": "a@b"})


def test_validate_content_rejects_unknown_field():
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.GITHUB, {"token": "t", "nope": "x"})


def test_encrypt_decrypt_round_trip():
    original = validate_content(SecretProvider.JIRA, _JIRA)
    blob = encrypt_content(original, _KEY)
    assert "secret-token" not in blob  # whole payload is ciphertext, not plaintext
    assert decrypt_content(SecretProvider.JIRA, blob, _KEY) == original


def test_zoho_mail_content_validates_oauth_fields():
    content = validate_content(
        SecretProvider.ZOHO_MAIL,
        {
            "email": "u@z.com",
            "account_id": "56218000000008002",
            "client_id": "1000.CLIENTID",
            "client_secret": "z_secret",
            "refresh_token": "z_refresh",
        },
    )
    assert isinstance(content, ZohoMailContent)
    assert content.email == "u@z.com"
    assert content.account_id == "56218000000008002"
    assert content.client_id == "1000.CLIENTID"


def test_display_names_cover_every_provider():
    assert set(PROVIDER_DISPLAY_NAMES) == set(SecretProvider)


def _create_with_secrets(secrets: list[dict]) -> AgentCreate:
    return AgentCreate.model_validate({**_BASE_CREATE, "secrets": secrets})


def test_agent_create_accepts_valid_secret():
    model = _create_with_secrets([{"provider": "jira", "content": _JIRA}])
    assert model.secrets[0].provider == SecretProvider.JIRA


def test_agent_create_rejects_duplicate_providers():
    with pytest.raises(ValidationError):
        _create_with_secrets(
            [
                {"provider": "jira", "content": _JIRA},
                {"provider": "jira", "content": _JIRA},
            ]
        )


def test_agent_create_rejects_invalid_secret_content():
    with pytest.raises(ValidationError):
        _create_with_secrets([{"provider": "jira", "content": {"site_url": "x"}}])


# --- optional/multi repos (AF-162) ---


def test_github_content_defaults_repos_to_empty_list():
    content = validate_content(SecretProvider.GITHUB, _GITHUB_BASE)
    assert isinstance(content, GithubContent)
    assert content.repos == []


def test_github_content_accepts_multiple_repos():
    content = validate_content(SecretProvider.GITHUB, {**_GITHUB_BASE, "repos": ["repo-a", "repo-b"]})
    assert isinstance(content, GithubContent)
    assert content.repos == ["repo-a", "repo-b"]


def test_github_content_legacy_repo_field_upgrades_to_repos_list():
    content = validate_content(SecretProvider.GITHUB, {**_GITHUB_BASE, "repo": "legacy-repo"})
    assert isinstance(content, GithubContent)
    assert content.repos == ["legacy-repo"]


def test_github_content_legacy_empty_repo_upgrades_to_empty_list():
    content = validate_content(SecretProvider.GITHUB, {**_GITHUB_BASE, "repo": ""})
    assert isinstance(content, GithubContent)
    assert content.repos == []


def test_bitbucket_content_defaults_repos_to_empty_list():
    content = validate_content(SecretProvider.BITBUCKET, _BITBUCKET_BASE)
    assert isinstance(content, BitbucketContent)
    assert content.repos == []


def test_bitbucket_content_accepts_multiple_repos():
    content = validate_content(SecretProvider.BITBUCKET, {**_BITBUCKET_BASE, "repos": ["repo-a", "repo-b"]})
    assert isinstance(content, BitbucketContent)
    assert content.repos == ["repo-a", "repo-b"]


def test_bitbucket_content_legacy_repo_field_upgrades_to_repos_list():
    content = validate_content(SecretProvider.BITBUCKET, {**_BITBUCKET_BASE, "repo": "legacy-repo"})
    assert isinstance(content, BitbucketContent)
    assert content.repos == ["legacy-repo"]


def test_decrypt_content_upgrades_legacy_github_blob():
    """Old encrypted blobs shaped {"repo": "x"} must decrypt transparently into repos: [x]."""
    legacy_blob = encrypt_token(
        json.dumps({"token": "t", "owner": "acme", "repo": "legacy-repo", "org": "acme"}),
        _KEY,
    )
    content = decrypt_content(SecretProvider.GITHUB, legacy_blob, _KEY)
    assert isinstance(content, GithubContent)
    assert content.repos == ["legacy-repo"]


def test_decrypt_content_upgrades_legacy_bitbucket_blob():
    legacy_blob = encrypt_token(
        json.dumps(
            {
                "workspace": "acme",
                "repo": "legacy-repo",
                "email": "a@b.com",
                "api_token": "secret-token",
            }
        ),
        _KEY,
    )
    content = decrypt_content(SecretProvider.BITBUCKET, legacy_blob, _KEY)
    assert isinstance(content, BitbucketContent)
    assert content.repos == ["legacy-repo"]


# --- Firecrawl (AF-152) ---


def test_firecrawl_content_validates_api_key():
    content = validate_content(SecretProvider.FIRECRAWL, {"api_key": "fc-abc123"})
    assert isinstance(content, FirecrawlContent)
    assert content.api_key == "fc-abc123"
    assert content.base_url == ""


def test_firecrawl_content_validates_api_key_with_base_url():
    content = validate_content(
        SecretProvider.FIRECRAWL,
        {"api_key": "fc-abc123", "base_url": "https://api.firecrawl.dev"},
    )
    assert isinstance(content, FirecrawlContent)
    assert content.api_key == "fc-abc123"
    assert content.base_url == "https://api.firecrawl.dev"


def test_firecrawl_content_rejects_missing_api_key():
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.FIRECRAWL, {})


def test_firecrawl_content_rejects_extra_fields():
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.FIRECRAWL, {"api_key": "fc-x", "extra": "nope"})


def test_firecrawl_encrypt_decrypt_round_trip():
    original = validate_content(SecretProvider.FIRECRAWL, {"api_key": "fc-secret"})
    blob = encrypt_content(original, _KEY)
    assert "fc-secret" not in blob
    assert decrypt_content(SecretProvider.FIRECRAWL, blob, _KEY) == original


def test_firecrawl_encrypt_decrypt_round_trip_with_base_url():
    original = validate_content(
        SecretProvider.FIRECRAWL,
        {"api_key": "fc-secret", "base_url": "https://api.firecrawl.dev"},
    )
    blob = encrypt_content(original, _KEY)
    decrypted = decrypt_content(SecretProvider.FIRECRAWL, blob, _KEY)
    assert decrypted == original
    assert isinstance(decrypted, FirecrawlContent)
    assert decrypted.base_url == "https://api.firecrawl.dev"


# --- Pipedrive (AF-245) ---

_PIPEDRIVE_BASE = {"api_token": "test-token"}


def test_pipedrive_content_validates_without_domain():
    content = validate_content(SecretProvider.PIPEDRIVE, _PIPEDRIVE_BASE)
    assert isinstance(content, PipedriveContent)
    assert content.api_token == "test-token"
    assert content.domain == ""


def test_pipedrive_content_validates_with_domain():
    content = validate_content(SecretProvider.PIPEDRIVE, {**_PIPEDRIVE_BASE, "domain": "aai-labs"})
    assert isinstance(content, PipedriveContent)
    assert content.api_token == "test-token"
    assert content.domain == "aai-labs"


def test_pipedrive_content_rejects_missing_api_token():
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.PIPEDRIVE, {})


def test_pipedrive_content_rejects_extra_fields():
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.PIPEDRIVE, {**_PIPEDRIVE_BASE, "extra": "nope"})


def test_pipedrive_encrypt_decrypt_round_trip():
    original = validate_content(SecretProvider.PIPEDRIVE, _PIPEDRIVE_BASE)
    blob = encrypt_content(original, _KEY)
    assert "test-token" not in blob
    assert decrypt_content(SecretProvider.PIPEDRIVE, blob, _KEY) == original


def test_pipedrive_encrypt_decrypt_round_trip_with_domain():
    original = validate_content(SecretProvider.PIPEDRIVE, {**_PIPEDRIVE_BASE, "domain": "aai-labs"})
    blob = encrypt_content(original, _KEY)
    decrypted = decrypt_content(SecretProvider.PIPEDRIVE, blob, _KEY)
    assert decrypted == original
    assert isinstance(decrypted, PipedriveContent)
    assert decrypted.domain == "aai-labs"


def test_retired_google_providers_are_gone():
    """The per-service Google providers were removed outright, rows and all (their
    secrets are deleted by migration). Nothing may resurrect them as a provider value:
    one google_workspace credential covers Gmail, Calendar, Drive and Sheets."""
    for retired in ("gmail", "google_calendar", "google_sheets"):
        with pytest.raises(ValueError):
            SecretProvider(retired)


# --- Slack (AF-209) ---

_SLACK_BASE = {"token": "xoxb-test-token"}


def test_slack_content_validates_token():
    content = validate_content(SecretProvider.SLACK, _SLACK_BASE)
    assert isinstance(content, SlackContent)
    assert content.token == "xoxb-test-token"


def test_slack_content_rejects_missing_token():
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.SLACK, {})


def test_slack_content_rejects_extra_fields():
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.SLACK, {**_SLACK_BASE, "extra": "nope"})


def test_slack_encrypt_decrypt_round_trip():
    original = validate_content(SecretProvider.SLACK, _SLACK_BASE)
    blob = encrypt_content(original, _KEY)
    assert "xoxb-test-token" not in blob
    assert decrypt_content(SecretProvider.SLACK, blob, _KEY) == original


# --- google_workspace ---

_GOOGLE_WORKSPACE_BASE = {
    "email": "user@example.com",
    "services": ["gmail", "calendar"],
    "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
    "refresh_token": "rt-123",
}


def test_google_workspace_parses_and_defaults():
    content = validate_content(SecretProvider.GOOGLE_WORKSPACE, _GOOGLE_WORKSPACE_BASE)
    assert isinstance(content, GoogleWorkspaceContent)
    assert content.services == ["gmail", "calendar"]
    # Full access and a server-backfilled client are the defaults.
    assert content.read_only is False
    assert content.client_id == ""
    assert content.client_secret == ""


def test_google_workspace_rejects_unknown_service():
    with pytest.raises(ValidationError):
        validate_content(
            SecretProvider.GOOGLE_WORKSPACE,
            {**_GOOGLE_WORKSPACE_BASE, "services": ["gmail", "youtube"]},
        )


def test_google_workspace_rejects_empty_services():
    # A credential covering nothing would consent to nothing and confuse the agent.
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.GOOGLE_WORKSPACE, {**_GOOGLE_WORKSPACE_BASE, "services": []})


def test_google_workspace_deduplicates_services_preserving_order():
    content = validate_content(
        SecretProvider.GOOGLE_WORKSPACE,
        {**_GOOGLE_WORKSPACE_BASE, "services": ["sheets", "gmail", "sheets"]},
    )
    assert isinstance(content, GoogleWorkspaceContent)
    assert content.services == ["sheets", "gmail"]


def test_google_workspace_requires_refresh_token():
    payload = {k: v for k, v in _GOOGLE_WORKSPACE_BASE.items() if k != "refresh_token"}
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.GOOGLE_WORKSPACE, payload)


def test_google_workspace_rejects_unknown_field():
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.GOOGLE_WORKSPACE, {**_GOOGLE_WORKSPACE_BASE, "client_json": "{}"})


def test_google_workspace_encrypt_decrypt_round_trip():
    original = validate_content(SecretProvider.GOOGLE_WORKSPACE, _GOOGLE_WORKSPACE_BASE)
    blob = encrypt_content(original, _KEY)
    assert "rt-123" not in blob
    assert decrypt_content(SecretProvider.GOOGLE_WORKSPACE, blob, _KEY) == original

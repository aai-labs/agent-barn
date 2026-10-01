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
    SharePointContent,
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


_SHAREPOINT = {
    "connection_id": "0199c2a4-7b1e-7c3d-9f00-1234567890ab",
    "tenant_id": "b6f28f4f-97fe-41e6-903a-ff6cc7633ae3",
    "client_id": "5ff671c1-57c7-44ef-a7b5-8fe4f81227f9",
    "email": "alice@contoso.com",
    "scopes": ["Sites.ReadWrite.All"],
    "refresh_token": "rt-from-sign-in",
    "sign_in_id": "0199c2a4-7b1e-7c3d-9f00-000000000001",
}


def test_sharepoint_content_round_trips():
    content = validate_content(SecretProvider.SHAREPOINT, _SHAREPOINT)
    assert isinstance(content, SharePointContent)
    assert content.connection_id == "0199c2a4-7b1e-7c3d-9f00-1234567890ab"
    assert content.client_id == "5ff671c1-57c7-44ef-a7b5-8fe4f81227f9"
    assert content.refresh_token == "rt-from-sign-in"
    assert content.read_only is False


def test_sharepoint_content_survives_encryption():
    # encrypt_content JSON-serialises model_dump(), so every field must be JSON-native.
    original = validate_content(SecretProvider.SHAREPOINT, _SHAREPOINT)
    blob = encrypt_content(original, _KEY)
    assert decrypt_content(SecretProvider.SHAREPOINT, blob, _KEY) == original


def test_sharepoint_content_never_holds_the_teams_app_secret():
    # The sign-in is a public client (PKCE); the Teams app's secret has no business here,
    # where it would reach the agent's pod and let it act as its bot.
    for field in ("client_secret", "app_password", "access_token"):
        with pytest.raises(ValidationError):
            validate_content(SecretProvider.SHAREPOINT, {**_SHAREPOINT, field: "x"})


@pytest.mark.parametrize("field", ["connection_id", "sign_in_id"])
def test_sharepoint_content_requires_valid_uuids(field):
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.SHAREPOINT, {**_SHAREPOINT, field: "not-a-uuid"})


@pytest.mark.parametrize("field", ["connection_id", "tenant_id", "client_id", "email", "refresh_token", "sign_in_id"])
def test_sharepoint_content_requires_its_fields(field):
    payload = {k: v for k, v in _SHAREPOINT.items() if k != field}
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.SHAREPOINT, payload)


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


@pytest.mark.parametrize(
    "domain",
    [
        # Each would otherwise move the host out of *.pipedrive.com, sending the API
        # server's validation request (and the token) wherever the caller points it.
        "evil.example#",
        "10.0.0.5/x?",
        "user@evil.example/",
        "evil.example:443/",
        "aai labs",
        "-aai-labs",
        "a" * 64,
    ],
)
def test_pipedrive_content_rejects_domain_that_is_not_a_subdomain_label(domain):
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.PIPEDRIVE, {**_PIPEDRIVE_BASE, "domain": domain})


@pytest.mark.parametrize(
    "domain",
    ["AAI-Labs", " aai-labs ", "aai-labs.pipedrive.com", "https://aai-labs.pipedrive.com/"],
)
def test_pipedrive_content_normalizes_domain_to_its_subdomain_label(domain):
    content = validate_content(SecretProvider.PIPEDRIVE, {**_PIPEDRIVE_BASE, "domain": domain})
    assert isinstance(content, PipedriveContent)
    assert content.domain == "aai-labs"


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
    "scopes": [
        "https://www.googleapis.com/auth/gmail.modify",
        "https://www.googleapis.com/auth/gmail.settings.basic",
        "https://www.googleapis.com/auth/gmail.settings.sharing",
        "https://www.googleapis.com/auth/calendar",
        "https://www.googleapis.com/auth/drive",
        "https://www.googleapis.com/auth/spreadsheets",
    ],
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


def test_google_workspace_rejects_scopes_missing_selected_service():
    with pytest.raises(ValidationError, match="scopes do not cover"):
        validate_content(
            SecretProvider.GOOGLE_WORKSPACE,
            {
                **_GOOGLE_WORKSPACE_BASE,
                "services": ["gmail", "calendar"],
                "scopes": ["https://www.googleapis.com/auth/gmail.modify"],
            },
        )


def test_google_workspace_rejects_blank_email():
    with pytest.raises(ValidationError):
        validate_content(SecretProvider.GOOGLE_WORKSPACE, {**_GOOGLE_WORKSPACE_BASE, "email": ""})


def test_google_workspace_rejects_scopes_for_wrong_access_level():
    with pytest.raises(ValidationError, match="gmail.readonly"):
        validate_content(
            SecretProvider.GOOGLE_WORKSPACE,
            {
                **_GOOGLE_WORKSPACE_BASE,
                "services": ["gmail"],
                "read_only": True,
                "scopes": [
                    "https://www.googleapis.com/auth/gmail.modify",
                    "https://www.googleapis.com/auth/gmail.settings.basic",
                    "https://www.googleapis.com/auth/gmail.settings.sharing",
                ],
            },
        )
    with pytest.raises(ValidationError, match="gmail.modify"):
        validate_content(
            SecretProvider.GOOGLE_WORKSPACE,
            {
                **_GOOGLE_WORKSPACE_BASE,
                "services": ["gmail"],
                "read_only": False,
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
            },
        )


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

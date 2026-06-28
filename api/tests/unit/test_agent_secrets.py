import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from api.domains.agents.models import (
    PROVIDER_DISPLAY_NAMES,
    AgentCreate,
    JiraContent,
    SecretProvider,
    ZohoMailContent,
    decrypt_content,
    encrypt_content,
    validate_content,
)

_KEY = Fernet.generate_key().decode()

_BASE_CREATE = {
    "name": "Agent",
    "slack_bot_token": "xoxb-x",
    "slack_app_token": "xapp-x",
    "template_slug": "test-template",
}

_JIRA = {
    "site_url": "https://x.atlassian.net",
    "email": "a@b.com",
    "api_token": "secret-token",
}


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

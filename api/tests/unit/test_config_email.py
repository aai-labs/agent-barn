import pytest
from hamcrest import assert_that, equal_to

from api.core.config import Config

DELIVERY_FIELDS = ("cloudflare_account_id", "cloudflare_api_token", "sender_email")
AGENT_EMAIL_FIELDS = ("agent_email_domain", "agent_email_mailbox", "email_inbound_secret")


def _config(**overrides: str) -> Config:
    enabled = Config(
        db_connection_url="postgresql://user:pass@localhost:5432/db",
        secret_signing_key="signing-key",
        platform_admin_credentials="admin@example.com:StrongPass123",
        cloudflare_account_id="acct-123",
        cloudflare_api_token="tok-abc",
        sender_email="noreply@mail.agentbarn.dev",
        agent_email_domain="agents.agentbarn.dev",
        agent_email_mailbox="agent",
        email_inbound_secret="inbound-secret",
    )
    return enabled.model_copy(update=overrides)


def test_agent_email_is_enabled_when_delivery_domain_and_inbound_secret_are_set():
    assert_that(_config().is_agent_email_enabled, equal_to(True))


@pytest.mark.parametrize("missing", AGENT_EMAIL_FIELDS)
def test_agent_email_is_disabled_when_an_agent_email_value_is_missing(missing):
    assert_that(_config(**{missing: ""}).is_agent_email_enabled, equal_to(False))


@pytest.mark.parametrize("missing", DELIVERY_FIELDS)
def test_agent_email_is_disabled_when_transactional_delivery_is_disabled(missing):
    config = _config(**{missing: ""})

    assert_that(config.is_email_delivery_enabled, equal_to(False))
    assert_that(config.is_agent_email_enabled, equal_to(False))


@pytest.mark.parametrize("field", AGENT_EMAIL_FIELDS)
def test_whitespace_only_agent_email_values_do_not_enable_agent_email(field):
    assert_that(_config(**{field: "   "}).is_agent_email_enabled, equal_to(False))


def test_transactional_delivery_stays_enabled_without_agent_email_configuration():
    config = _config(agent_email_domain="", email_inbound_secret="")

    assert_that(config.is_email_delivery_enabled, equal_to(True))
    assert_that(config.is_agent_email_enabled, equal_to(False))

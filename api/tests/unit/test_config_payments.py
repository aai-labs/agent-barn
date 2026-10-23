"""The deployment's Stripe keys (AF-381). Whether payments are on is a platform setting;
the deployment only says whether it has what payments need, and refuses to boot with a
webhook secret but no secret key, which would fail every refund."""

import pytest
from hamcrest import assert_that, equal_to

from api.core.config import Config


def _config(*, secret_key: str = "", webhook_secret: str = "") -> Config:
    return Config(
        db_connection_url="postgresql://user:pass@localhost:5432/db",
        secret_signing_key="signing-key",
        platform_admin_credentials="admin@example.com:StrongPass123",
        organization_default_llm_budget_usd=100,
        agent_default_llm_budget_usd=25,
        stripe_secret_key=secret_key,
        stripe_webhook_secret=webhook_secret,
    )


def test_a_deployment_with_both_stripe_keys_can_take_payments():
    assert_that(_config(secret_key="sk_test_x", webhook_secret="whsec_x").payments_configured, equal_to(True))


@pytest.mark.parametrize("secret_key", ["", "sk_test_x", "  "])
def test_a_deployment_without_a_webhook_secret_boots_but_cannot_take_payments(secret_key):
    assert_that(_config(secret_key=secret_key).payments_configured, equal_to(False))


def test_a_webhook_secret_without_the_secret_key_refuses_to_boot():
    """The webhook reads refunds from Stripe, payments on or off: without the key every
    refund would fail until Stripe gave up on it."""
    with pytest.raises(ValueError, match="STRIPE_SECRET_KEY"):
        _config(webhook_secret="whsec_x")

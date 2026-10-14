"""Payments need both Stripe secrets (AF-381): a deployment that turns payments on without
them refuses to boot, rather than failing every purchase and every Stripe event."""

import pytest
from hamcrest import assert_that, equal_to

from api.core.config import Config


def _config(*, payments_enabled: bool, secret_key: str = "", webhook_secret: str = "") -> Config:
    return Config(
        db_connection_url="postgresql://user:pass@localhost:5432/db",
        secret_signing_key="signing-key",
        platform_admin_credentials="admin@example.com:StrongPass123",
        organization_default_llm_budget_usd=100,
        agent_default_llm_budget_usd=25,
        payments_enabled=payments_enabled,
        stripe_secret_key=secret_key,
        stripe_webhook_secret=webhook_secret,
    )


def test_payments_on_with_both_secrets_boots():
    config = _config(payments_enabled=True, secret_key="sk_test_x", webhook_secret="whsec_x")

    assert_that(config.payments_enabled, equal_to(True))


@pytest.mark.parametrize(
    "secret_key,webhook_secret,missing",
    [("", "whsec_x", "STRIPE_SECRET_KEY"), ("sk_test_x", "", "STRIPE_WEBHOOK_SECRET")],
)
def test_payments_on_without_a_stripe_secret_refuses_to_boot(secret_key, webhook_secret, missing):
    with pytest.raises(ValueError, match=missing):
        _config(payments_enabled=True, secret_key=secret_key, webhook_secret=webhook_secret)


def test_payments_off_needs_no_secrets():
    assert_that(_config(payments_enabled=False).payments_enabled, equal_to(False))


def test_a_webhook_secret_without_the_secret_key_refuses_to_boot():
    """The webhook reads refunds from Stripe, payments on or off: without the key every
    refund would fail until Stripe gave up on it."""
    with pytest.raises(ValueError, match="STRIPE_SECRET_KEY"):
        _config(payments_enabled=False, webhook_secret="whsec_x")

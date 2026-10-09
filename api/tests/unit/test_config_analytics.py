import pytest
from hamcrest import assert_that, equal_to

from api.core.config import Config


def _config(**overrides) -> Config:
    return Config(
        db_connection_url="postgresql://user:pass@localhost:5432/db",
        secret_signing_key="signing-key",
        platform_admin_credentials="admin@example.com:StrongPass123",
        **overrides,
    )


@pytest.fixture(autouse=True)
def _no_analytics_env(monkeypatch):
    for key in ("ANALYTICS_ENABLED", "ANALYTICS_INCLUDE_USER_DETAILS", "INSTALLATION_NAME", "WEB_APP_URL"):
        monkeypatch.delenv(key, raising=False)


def test_analytics_is_on_by_default():
    config = _config()

    assert_that((config.is_analytics_enabled, config.analytics_include_user_details), equal_to((True, False)))


def test_analytics_can_be_explicitly_disabled():
    assert_that(_config(analytics_enabled=False).is_analytics_enabled, equal_to(False))


@pytest.mark.parametrize("token", ["", "   "])
def test_analytics_stays_off_without_a_project_token(token):
    config = _config(analytics_enabled=True, analytics_posthog_project_token=token)

    assert_that(config.is_analytics_enabled, equal_to(False))


@pytest.mark.parametrize("key", ["ANALYTICS_ENABLED", "ANALYTICS_INCLUDE_USER_DETAILS"])
def test_a_blank_switch_falls_back_to_off(monkeypatch, key):
    monkeypatch.setenv(key, "")

    config = _config()

    assert_that(getattr(config, key.lower()), equal_to(False))


def test_the_installation_name_is_used_when_set():
    config = _config(installation_name="GG Group", web_app_url="https://agentbarn.gg-group.com")

    assert_that(config.installation_display_name, equal_to("GG Group"))


@pytest.mark.parametrize("name", ["", "   "])
def test_the_installation_name_falls_back_to_the_web_app_host(name):
    config = _config(installation_name=name, web_app_url="https://agentbarn.gg-group.com/app")

    assert_that(config.installation_display_name, equal_to("agentbarn.gg-group.com"))

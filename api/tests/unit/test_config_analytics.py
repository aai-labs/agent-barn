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


@pytest.mark.parametrize(
    "web_app_url",
    [
        "http://localhost:3000",
        "localhost:3000",
        "http://LOCALHOST.",
        "http://app.localhost",
        "http://127.0.0.1:3000",
        "http://127.5.5.5",
        "http://[::1]:3000",
        "http://[::ffff:127.0.0.1]",
        "http://0.0.0.0:3000",
        "http://[::]",
        "",
        "   ",
        "http://:3000",
        "http://[abc",
    ],
)
def test_a_developer_machine_web_app_url_is_a_local_installation(web_app_url):
    assert_that(_config(web_app_url=web_app_url).is_local_installation, equal_to(True))


@pytest.mark.parametrize(
    "web_app_url",
    [
        "http://agentbarn.local",
        "http://agentfarm.local",
        "http://10.0.5.20",
        "http://192.168.1.2:8080",
        "http://169.254.1.1",
        "http://100.64.0.1",
        "http://intranet",
        "https://app.agentbarn.dev",
        "https://cloud.agentbarn.dev/app",
        "http://8.8.8.8",
    ],
)
def test_any_other_web_app_url_is_a_remote_installation(web_app_url):
    assert_that(_config(web_app_url=web_app_url).is_local_installation, equal_to(False))


@pytest.mark.parametrize(
    ("web_app_url", "host"),
    [
        (" https://Agents.GG-Group.com:8443/app?x=1 ", "agents.gg-group.com"),
        ("https://app.example.com.", "app.example.com"),
        ("app.example.com/path", "app.example.com"),
        ("https://user:pw@host.example.com", "host.example.com"),
        ("http://[abc", ""),
    ],
)
def test_the_web_app_host_is_the_normalised_hostname_only(web_app_url, host):
    assert_that(_config(web_app_url=web_app_url).web_app_host, equal_to(host))


def test_a_leftover_installation_name_variable_is_ignored(monkeypatch):
    monkeypatch.setenv("INSTALLATION_NAME", "Old Name")

    config = _config(web_app_url="https://app.agentbarn.dev")

    assert_that(hasattr(config, "installation_name"), equal_to(False))

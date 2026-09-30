from hamcrest import assert_that, equal_to

from api.core.config import Config


def _config(*, environment: str = "local", api_port: int = 8000, api_external_url: str = "") -> Config:
    return Config(
        db_connection_url="postgresql://user:pass@localhost:5432/db",
        secret_signing_key="signing-key",
        platform_admin_credentials="admin@example.com:StrongPass123",
        environment=environment,
        api_port=api_port,
        api_external_url=api_external_url,
    )


def test_a_local_run_derives_the_api_url_from_its_published_port():
    assert_that(_config(api_port=8080).api_external_url, equal_to("http://localhost:8080"))


def test_an_explicit_value_is_never_overridden():
    config = _config(api_external_url="https://tunnel.example.com")

    assert_that(config.api_external_url, equal_to("https://tunnel.example.com"))


def test_a_deployed_environment_without_one_stays_empty():
    """Better a blank webhook URL than a localhost one a caller cannot reach."""
    assert_that(_config(environment="production").api_external_url, equal_to(""))

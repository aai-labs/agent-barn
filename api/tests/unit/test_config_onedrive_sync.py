import pytest
from hamcrest import assert_that, equal_to

from api.core.config import Config

ONEDRIVE_SYNC_FIELDS = ("onedrive_sync_client_id", "onedrive_sync_client_secret")


def _config(**overrides: str) -> Config:
    enabled = Config(
        db_connection_url="postgresql://user:pass@localhost:5432/db",
        secret_signing_key="signing-key",
        platform_admin_credentials="admin@example.com:StrongPass123",
        onedrive_sync_client_id="00000000-0000-0000-0000-000000000001",
        onedrive_sync_client_secret="client-secret",
    )
    return enabled.model_copy(update=overrides)


def test_onedrive_sync_is_enabled_when_client_id_and_secret_are_set():
    assert_that(_config().is_onedrive_sync_enabled, equal_to(True))


@pytest.mark.parametrize("missing", ONEDRIVE_SYNC_FIELDS)
def test_onedrive_sync_is_disabled_when_a_platform_app_value_is_missing(missing):
    assert_that(_config(**{missing: ""}).is_onedrive_sync_enabled, equal_to(False))


@pytest.mark.parametrize("field", ONEDRIVE_SYNC_FIELDS)
def test_whitespace_only_platform_app_values_do_not_enable_onedrive_sync(field):
    assert_that(_config(**{field: "   "}).is_onedrive_sync_enabled, equal_to(False))


def test_onedrive_sync_is_disabled_by_default():
    config = Config(
        db_connection_url="postgresql://user:pass@localhost:5432/db",
        secret_signing_key="signing-key",
        platform_admin_credentials="admin@example.com:StrongPass123",
        _env_file=None,
    )

    assert_that(config.is_onedrive_sync_enabled, equal_to(False))

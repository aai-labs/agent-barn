import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from dotenv import load_dotenv
from testcontainers.postgres import PostgresContainer

from api.core.config import get_config
from api.infrastructure.openrouter.client import clear_models_cache
from api.infrastructure.slack.client import clear_directory_cache

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
logger.addHandler(logging.StreamHandler())

ROOT_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(ROOT_ENV_PATH, override=False)


def _set_default(key: str, value: str) -> None:
    # .env may define these keys with an empty value (e.g. email disabled locally),
    # which `os.environ.setdefault` would treat as "already set" and never override.
    if not os.environ.get(key):
        os.environ[key] = value


os.environ["ENVIRONMENT"] = "test"
_set_default("SECRET_SIGNING_KEY", "test-secret-key")
_set_default("PLATFORM_ADMIN_CREDENTIALS", "admin@example.com:StrongPass123")
# Forced, not defaulted: a developer's real Cloudflare credentials in .env would otherwise
# win and the suite would send live email to fixture addresses, burning sending quota and
# bounce reputation on @example.com recipients.
os.environ["CLOUDFLARE_ACCOUNT_ID"] = "test-account-id"
os.environ["CLOUDFLARE_API_TOKEN"] = "test-api-token"
os.environ["SENDER_EMAIL"] = "noreply@example.com"

alembic_dir = Path(__file__).resolve().parents[1]
alembic_ini_path = alembic_dir / "alembic.ini"
config = Config(alembic_ini_path)


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    postgres_image = os.environ.get("TESTCONTAINERS_POSTGRES_IMAGE", "postgres:18")
    logger.info("Starting test Postgres container using image %s", postgres_image)

    with PostgresContainer(postgres_image, driver="psycopg2") as postgres:
        connection_url = postgres.get_connection_url()
        os.environ["DB_CONNECTION_URL"] = connection_url

        get_config.cache_clear()
        logger.info("Upgrading test database to head")
        command.upgrade(config, "head")
        yield


@pytest.fixture(autouse=True)
def clear_slack_directory_cache():
    """Slack directory cache is process-global; reset it between tests."""
    clear_directory_cache()
    yield


@pytest.fixture(autouse=True)
def clear_openrouter_models_cache():
    """OpenRouter catalogue cache is process-global; reset it between tests."""
    clear_models_cache()
    yield


@pytest.fixture(autouse=True)
def block_outbound_email():
    """Only one integration test binds MockEmailModule, so every other test that triggers an
    invite reaches the real EmailClient. Block the transport for the whole suite: a test that
    genuinely exercises sending patches this target itself, which overrides this fixture."""

    def _refuse(*args, **kwargs):
        raise RuntimeError(
            "Outbound email attempted in tests. Patch api.infrastructure.email.client.httpx.post "
            "or bind MockEmailModule if this send is intentional."
        )

    with patch("api.infrastructure.email.client.httpx.post", side_effect=_refuse):
        yield

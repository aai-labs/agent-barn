from uuid import UUID

from hamcrest import assert_that, equal_to, is_, not_

from api.core.config import Config
from api.domains.artifacts.buckets import bucket_name


def test_bucket_name_is_fixed_and_derived_only_from_the_agent_uuid():
    agent_id = UUID("12345678-1234-1234-1234-123456789abc")
    assert_that(bucket_name(agent_id), equal_to("agent-artifacts-12345678123412341234123456789abc"))
    assert_that(bucket_name(agent_id), not_(equal_to(bucket_name(UUID(int=0)))))
    assert_that(len(bucket_name(agent_id)) <= 63, is_(True))


def test_bucket_prefix_is_not_a_configuration_option(monkeypatch):
    monkeypatch.setenv("ARTIFACT_S3_BUCKET_PREFIX", "retired-setting")
    config = Config(
        db_connection_url="postgresql://user:pass@localhost:5432/db",
        secret_signing_key="fixture",
        platform_admin_credentials="admin@example.com:StrongPass123",
    )
    assert_that(hasattr(config, "artifact_s3_bucket_prefix"), is_(False))

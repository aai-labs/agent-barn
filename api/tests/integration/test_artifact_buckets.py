"""Real Garage authority boundaries and durable provisioning/deletion retries."""

import re
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from botocore.exceptions import ClientError
from hamcrest import assert_that, equal_to, has_length, is_, is_in, none, not_
from sqlmodel import Session, select

from api.core.config import Config
from api.domains.agents.models import Agent
from api.domains.artifacts.buckets import ArtifactBucketRepository
from api.domains.artifacts.models import Artifact, ArtifactBucket
from api.domains.artifacts.provisioning import ArtifactBucketProvisioner
from api.domains.artifacts.service import ArtifactService
from api.infrastructure.crypto import decrypt_token
from api.infrastructure.s3.client import ArtifactStorage
from api.tests.core.givenpy import given
from api.tests.core.modules import set_env_variable
from api.tests.integration.test_artifacts import CONTENT, publish, storage  # noqa: F401
from api.tests.integration.test_workflows import _GIVEN
from api.tests.steps.agent import there_is_an_agent
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token


def due(context):
    with Session(context.postgres_delegate.engine) as session:
        for row in session.exec(select(ArtifactBucket)).all():
            row.retry_at = datetime.now(UTC) - timedelta(seconds=1)
            session.add(row)
        session.commit()


def journal(context):
    with Session(context.postgres_delegate.engine) as session:
        return session.exec(select(ArtifactBucket).where(ArtifactBucket.agent_id == context.agent.id)).one()


def assert_cross_bucket_denied(error: ClientError, *, operation: str, target_type: str, direction: str) -> None:
    response = error.response
    code = response.get("Error", {}).get("Code")
    # Provider messages and arbitrary response values may include resource names or credentials.
    safe_code = code if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_]{1,80}", code) else "unavailable"
    assert_that(
        response["ResponseMetadata"]["HTTPStatusCode"],
        is_in((403, 404)),
        f"Cross-bucket {operation} ({direction}, {target_type}); provider error code: {safe_code}",
    )


@pytest.mark.parametrize("other_tenant", [False, True])
def test_each_agent_key_cannot_read_write_or_administer_another_bucket(storage, other_tenant):  # noqa: F811
    env, provider = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        first = publish(context)
        adapter = context.injector.get(ArtifactStorage)
        with Session(context.postgres_delegate.engine) as session:
            first_row = session.get_one(Artifact, UUID(first["id"]))
        first_s3 = adapter.client(first_row)
        first_bucket = journal(context)
        if other_tenant:
            there_is_an_organization_with_user_and_access_token()(context)
        there_is_an_agent()(context)
        second = publish(context, content=CONTENT)  # Same content does not imply shared storage.
        with Session(context.postgres_delegate.engine) as session:
            second_row = session.get_one(Artifact, UUID(second["id"]))
        second_s3 = adapter.client(second_row)
        second_bucket = journal(context)
        assert_that(first_bucket.name, not_(equal_to(second_bucket.name)))
        assert_that(first_bucket.provider_id, not_(equal_to(second_bucket.provider_id)))
        assert_that(first_bucket.access_key, not_(equal_to(second_bucket.access_key)))
        assert_that(first_bucket.secret_key_encrypted, not_(equal_to(second_bucket.secret_key_encrypted)))
        config = context.injector.get(Config)
        assert_that((config.artifact_provisioner_token, config.artifact_provisioner_url), equal_to(("", "")))
        assert_that(hasattr(config, "artifact_s3_secret_key"), is_(False))
        secret = decrypt_token(first_bucket.secret_key_encrypted, config.agent_token_encryption_key)
        assert_that(secret in repr(first_bucket) + repr(first), is_(False))
        for direction, attacker, victim, victim_bucket in (
            ("first to second", first_s3, second_row, second_bucket),
            ("second to first", second_s3, first_row, first_bucket),
        ):
            # Test the provider ID too: a private alias alone could hide a shared
            # bucket while both credentials still have access to its actual ID.
            for target_type, target in (("alias", victim.bucket), ("provider ID", victim_bucket.provider_id)):
                with pytest.raises(ClientError) as denied:
                    attacker.get_object(Bucket=target, Key=victim.object_key)
                assert_cross_bucket_denied(
                    denied.value, operation="get_object", target_type=target_type, direction=direction
                )
                with pytest.raises(ClientError) as denied:
                    attacker.put_object(Bucket=target, Key=victim.object_key, Body=b"overwrite")
                assert_cross_bucket_denied(
                    denied.value, operation="put_object", target_type=target_type, direction=direction
                )
        anonymous = httpx.get(
            env["ARTIFACT_S3_ENDPOINT_URL"] + "/" + first_bucket.provider_id + "/" + first_row.object_key,
            trust_env=False,
        )
        assert_that(anonymous.status_code, equal_to(403))
        for client, row, bucket in ((first_s3, first_row, first_bucket), (second_s3, second_row, second_bucket)):
            with client.get_object(Bucket=row.bucket, Key=row.object_key)["Body"] as stream:
                assert_that(stream.read(), equal_to(CONTENT))
            with pytest.raises(ClientError) as denied:
                client.create_bucket(Bucket="cannot-create-" + row.agent_id.hex)
            assert_that(denied.value.response["ResponseMetadata"]["HTTPStatusCode"], equal_to(403))
            with pytest.raises(ClientError) as denied:
                client.delete_bucket(Bucket=row.bucket)
            assert_that(denied.value.response["ResponseMetadata"]["HTTPStatusCode"], equal_to(403))
            key = provider.key(bucket.access_key)
            assert_that(key, not_(none()))
            assert_that(key["permissions"], equal_to({"createBucket": False}))
            assert_that(key["buckets"], has_length(1))
            assert_that(key["buckets"][0]["permissions"], equal_to({"read": True, "write": True, "owner": False}))


def test_uncertain_bucket_creation_recovers_same_key_and_bucket(storage, monkeypatch):  # noqa: F811
    env, provider = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        worker = ArtifactBucketProvisioner(
            context.injector.get(ArtifactBucketRepository), context.injector.get(Config), provider
        )
        worker.buckets.reserve(context.agent.id, context.agent.organization_id)
        due(context)
        original = provider.create_bucket

        def lose_response(*args):
            original(*args)
            raise OSError("lost successful response")

        monkeypatch.setattr(provider, "create_bucket", lose_response)
        worker.run()
        pending = journal(context)
        assert_that((pending.state, pending.last_error), equal_to(("PENDING", "OSError")))
        key = provider.key(pending.access_key)
        assert_that(key, not_(none()))
        assert_that(key["buckets"], has_length(1))
        created_id = key["buckets"][0]["id"]
        monkeypatch.setattr(provider, "create_bucket", original)
        due(context)
        worker.run()
        ready = journal(context)
        assert_that((ready.state, ready.provider_id), equal_to(("READY", created_id)))
        assert_that(ready.access_key, equal_to(pending.access_key))
        assert_that(ready.secret_key_encrypted, equal_to(pending.secret_key_encrypted))


@pytest.mark.parametrize("hard_delete", [False, True])
def test_owner_deletion_keeps_key_until_bytes_purged_then_reclaims_bucket_and_key(storage, hard_delete):  # noqa: F811
    env, provider = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        published = publish(context)
        bucket = journal(context)
        worker = ArtifactBucketProvisioner(
            context.injector.get(ArtifactBucketRepository), context.injector.get(Config), provider
        )
        with Session(context.postgres_delegate.engine) as session:
            agent = session.get_one(Agent, context.agent.id)
            if hard_delete:
                session.delete(agent)
            else:
                agent.deleted_at = datetime.now(UTC)
                session.add(agent)
            session.commit()
        due(context)
        worker.run()
        assert_that(journal(context).state, equal_to("DELETING"))
        assert_that(provider.key(bucket.access_key), not_(none()))
        assert_that(context.injector.get(ArtifactService).purge(), equal_to(1))
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.get_one(Artifact, UUID(published["id"])).state, equal_to("DELETED"))
        deadline = time.monotonic() + 15
        while journal(context).state != "DELETED":
            due(context)
            worker.run()
            assert_that(time.monotonic() < deadline, is_(True), "Bucket cleanup must converge")
            time.sleep(0.1)
        assert_that(provider.bucket(bucket.provider_id), none())
        assert_that(provider.key(bucket.access_key), none())
        assert_that(journal(context).secret_key_encrypted, equal_to(""))


def test_uncertain_key_deletion_retains_journal_then_finishes_idempotently(storage, monkeypatch):  # noqa: F811
    env, provider = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        worker = ArtifactBucketProvisioner(
            context.injector.get(ArtifactBucketRepository), context.injector.get(Config), provider
        )
        worker.buckets.reserve(context.agent.id, context.agent.organization_id)
        worker.run()
        bucket = journal(context)
        with Session(context.postgres_delegate.engine) as session:
            agent = session.get_one(Agent, context.agent.id)
            agent.deleted_at = datetime.now(UTC)
            session.add(agent)
            session.commit()
        original = provider.delete_key

        def lose_response(access_key):
            original(access_key)
            raise OSError("lost key revocation response")

        monkeypatch.setattr(provider, "delete_key", lose_response)
        due(context)
        worker.run()
        retained = journal(context)
        assert_that((retained.state, retained.last_error), equal_to(("DELETING", "OSError")))
        assert_that(retained.secret_key_encrypted, equal_to(bucket.secret_key_encrypted))
        assert_that(provider.key(bucket.access_key), none())
        assert_that(provider.bucket(bucket.provider_id), none())
        monkeypatch.setattr(provider, "delete_key", original)
        due(context)
        worker.run()
        assert_that(journal(context).state, equal_to("DELETED"))
        assert_that(journal(context).secret_key_encrypted, equal_to(""))


def test_initializing_bucket_is_retryable_without_creating_file_metadata(storage):  # noqa: F811
    from api.tests.integration.test_artifacts import metadata
    from api.tests.integration.test_workflows import auth, base

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        response = context.client.post(base(context) + "/artifacts", headers=auth(context), json=metadata())
        assert_that(response.status_code, equal_to(503))
        assert_that("initializing" in response.text, is_(True))
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.exec(select(Artifact)).all(), has_length(0))

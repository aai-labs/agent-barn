"""Durable async creation and explicit storage requests against real Garage."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from hamcrest import assert_that, equal_to, has_length, none
from sqlmodel import Session, select

from api.domains.agents.models import Agent
from api.domains.agents.repository import AgentRepository
from api.domains.artifacts.models import ArtifactBucket
from api.domains.artifacts.provisioning import ArtifactBucketProvisioner
from api.domains.events.models import OutboxMessage
from api.infrastructure.s3.provisioner import GarageProvisioner
from api.tests.core.givenpy import given
from api.tests.core.modules import set_env_variable
from api.tests.helpers.artifacts import ADMIN_TOKEN, garage_storage
from api.tests.integration.test_agents import _BASE, _GIVEN, _VALID_CREATE, _auth
from api.tests.integration.test_workflows import _GIVEN as existing_agent
from api.tests.integration.test_workflows import auth, base


@pytest.fixture(scope="module")
def storage():
    with garage_storage() as (env, provider):
        yield {**env, "ARTIFACT_PROVISIONER_URL": provider.origin, "ARTIFACT_PROVISIONER_TOKEN": ADMIN_TOKEN}


def test_disabled_storage_keeps_creation_text_only():
    with given([set_env_variable({"ARTIFACT_S3_ENDPOINT_URL": ""}), *_GIVEN]) as context:
        response = context.client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))
        assert_that(response.status_code, equal_to(201), response.text)
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.exec(select(ArtifactBucket)).all(), has_length(0))


def test_creation_commits_agent_and_request_before_provider_io(storage, monkeypatch):
    with given([set_env_variable(storage), *_GIVEN]) as context:
        provider = context.injector.get(GarageProvisioner)
        original = provider.create_bucket
        observed = []

        def verify_committed(*args):
            with Session(context.postgres_delegate.engine) as session:
                assert_that(session.exec(select(Agent)).all(), has_length(1))
                assert_that(len(session.exec(select(OutboxMessage)).all()) > 0, equal_to(True))
                observed.append(session.exec(select(ArtifactBucket)).one().state)
            return original(*args)

        monkeypatch.setattr(provider, "create_bucket", verify_committed)
        response = context.client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))
        assert_that(response.status_code, equal_to(201), response.text)
        assert_that(observed, equal_to(["PENDING"]))
        result = context.client.get(_BASE + f"/{response.json()['id']}/artifacts/storage", headers=_auth(context))
        assert_that(result.json(), equal_to({"state": "READY"}))


def test_provider_failure_does_not_fail_creation_and_worker_recovers_same_identity(storage, monkeypatch):
    with given([set_env_variable(storage), *_GIVEN]) as context:
        provider = context.injector.get(GarageProvisioner)
        original = provider.create_bucket

        def lose_response(*args):
            original(*args)
            raise OSError("lost successful response")

        monkeypatch.setattr(provider, "create_bucket", lose_response)
        response = context.client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))
        assert_that(response.status_code, equal_to(201), response.text)
        path = _BASE + f"/{response.json()['id']}/artifacts/storage"
        assert_that(context.client.get(path, headers=_auth(context)).json(), equal_to({"state": "FAILED"}))
        with Session(context.postgres_delegate.engine) as session:
            row = session.exec(select(ArtifactBucket)).one()
            identity = (row.id, row.access_key)
            row.retry_at = datetime.now(UTC) - timedelta(seconds=1)
            session.add(row)
            session.commit()
        monkeypatch.setattr(provider, "create_bucket", original)
        context.injector.get(ArtifactBucketProvisioner).run()
        assert_that(context.client.get(path, headers=_auth(context)).json(), equal_to({"state": "READY"}))
        with Session(context.postgres_delegate.engine) as session:
            row = session.exec(select(ArtifactBucket)).one()
            assert_that((row.id, row.access_key), equal_to(identity))


def test_failed_agent_commit_leaves_no_storage_request_or_provider_side_effect(storage, monkeypatch):
    with given([set_env_variable(storage), *_GIVEN]) as context:
        calls = []
        monkeypatch.setattr(context.injector.get(GarageProvisioner), "create_bucket", lambda *args: calls.append(args))

        def fail_commit(*args, **kwargs):
            raise RuntimeError("injected commit failure")

        monkeypatch.setattr(context.injector.get(AgentRepository), "create_with_creator_access", fail_commit)
        with pytest.raises(RuntimeError, match="injected commit"):
            context.client.post(_BASE, json=_VALID_CREATE, headers=_auth(context))
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.exec(select(Agent)).all(), has_length(0))
            assert_that(session.exec(select(ArtifactBucket)).all(), has_length(0))
        assert_that(calls, has_length(0))


def test_old_agent_can_explicitly_provision_idempotently(storage):
    with given([set_env_variable(storage), *existing_agent]) as context:
        path = base(context) + "/artifacts/storage"
        assert_that(context.client.get(path, headers=auth(context)).json(), equal_to({"state": "NOT_PROVISIONED"}))
        response = context.client.post(path, headers=auth(context))
        assert_that(response.status_code, equal_to(202), response.text)
        assert_that(response.json(), equal_to({"state": "PROVISIONING"}))
        assert_that(context.client.get(path, headers=auth(context)).json(), equal_to({"state": "READY"}))
        with Session(context.postgres_delegate.engine) as session:
            before = session.exec(select(ArtifactBucket)).one()
        assert_that(context.client.post(path, headers=auth(context)).status_code, equal_to(202))
        with Session(context.postgres_delegate.engine) as session:
            after = session.exec(select(ArtifactBucket)).one()
            assert_that((after.id, after.access_key), equal_to((before.id, before.access_key)))
        assert_that(before.access_key in response.text or before.secret_key_encrypted in response.text, equal_to(False))


def test_explicit_retry_recovers_and_clears_safe_failure(storage, monkeypatch):
    with given([set_env_variable(storage), *existing_agent]) as context:
        provider = context.injector.get(GarageProvisioner)
        original = provider.create_bucket

        def fail(*args):
            raise OSError("private provider failure")

        monkeypatch.setattr(provider, "create_bucket", fail)
        path = base(context) + "/artifacts/storage"
        assert_that(context.client.post(path, headers=auth(context)).status_code, equal_to(202))
        response = context.client.get(path, headers=auth(context))
        assert_that(response.json(), equal_to({"state": "FAILED"}))
        monkeypatch.setattr(provider, "create_bucket", original)
        assert_that(context.client.post(path, headers=auth(context)).json(), equal_to({"state": "PROVISIONING"}))
        assert_that(context.client.get(path, headers=auth(context)).json(), equal_to({"state": "READY"}))


def test_storage_status_and_mutation_enforce_current_scope_and_read_only_key(storage):
    with given([set_env_variable(storage), *existing_agent]) as context:
        path = base(context) + "/artifacts/storage"
        key = context.client.post(
            "/api/v1/auth/me/api-keys", headers=auth(context), json={"name": "Files", "access_mode": "READ_ONLY"}
        ).json()["token"]
        headers = {"Authorization": "Bearer " + key}
        assert_that(context.client.get(path, headers=headers).status_code, equal_to(200))
        assert_that(context.client.post(path, headers=headers).status_code, equal_to(403))
        hidden = path.replace(str(context.agent.id), str(uuid4()))
        foreign = path.replace(str(context.organization.id), str(uuid4()))
        for target, expected in ((hidden, 404), (foreign, 403)):
            assert_that(context.client.get(target, headers=auth(context)).status_code, equal_to(expected))
            assert_that(context.client.post(target, headers=auth(context)).status_code, equal_to(expected))
        assert_that(context.client.post(path).status_code, equal_to(401))
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.exec(select(ArtifactBucket)).first(), none())


def test_storage_disabled_is_visible_but_cannot_be_requested():
    with given([set_env_variable({"ARTIFACT_S3_ENDPOINT_URL": ""}), *existing_agent]) as context:
        path = base(context) + "/artifacts/storage"
        assert_that(context.client.get(path, headers=auth(context)).json(), equal_to({"state": "NOT_CONFIGURED"}))
        assert_that(context.client.post(path, headers=auth(context)).status_code, equal_to(503))


def test_recovery_never_discovers_agents_without_requests(storage):
    with given([set_env_variable(storage), *existing_agent]) as context:
        assert_that(context.injector.get(ArtifactBucketProvisioner).run(), equal_to(0))
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.exec(select(ArtifactBucket)).all(), has_length(0))


def test_creation_returns_over_http_while_provider_is_still_running(storage, monkeypatch):
    from threading import Event

    import httpx

    from api.tests.helpers.artifacts import running_product_api

    with given([set_env_variable(storage), *_GIVEN]) as context:
        provider = context.injector.get(GarageProvisioner)
        original = provider.create_bucket
        entered, release = Event(), Event()

        def hold_provider(*args):
            entered.set()
            if not release.wait(timeout=15):
                raise RuntimeError("HTTP response waited for storage")
            return original(*args)

        monkeypatch.setattr(provider, "create_bucket", hold_provider)
        with running_product_api(context) as origin:
            try:
                with httpx.Client(base_url=origin, trust_env=False, timeout=5) as client:
                    collection = _BASE.format(organization_id=context.organization.id)
                    response = client.post(collection, json=_VALID_CREATE, headers=_auth(context))
                    assert_that(response.status_code, equal_to(201), response.text)
                    assert_that(entered.wait(timeout=5), equal_to(True))
                    path = collection + f"/{response.json()['id']}/artifacts/storage"
                    assert_that(client.get(path, headers=_auth(context)).json(), equal_to({"state": "PROVISIONING"}))
                    duplicate = client.post(path, headers=_auth(context))
                    assert_that(duplicate.status_code, equal_to(202))
                    assert_that(duplicate.json(), equal_to({"state": "PROVISIONING"}))
            finally:
                release.set()
        assert_that(context.client.get(path, headers=_auth(context)).json(), equal_to({"state": "READY"}))


def test_concurrent_requests_share_one_durable_bucket_identity(storage):
    from concurrent.futures import ThreadPoolExecutor

    from api.domains.artifacts.buckets import ArtifactBucketRepository

    with given([set_env_variable(storage), *existing_agent]) as context:
        repository = context.injector.get(ArtifactBucketRepository)
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda _: repository.reserve(context.agent.id, context.organization.id), range(4)))
        assert_that(len({(row.id, row.access_key) for row in rows}), equal_to(1))
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.exec(select(ArtifactBucket)).all(), has_length(1))


def test_deleted_owner_pending_request_is_reclaimed_without_provisioning(storage):
    from api.domains.artifacts.buckets import ArtifactBucketRepository

    with given([set_env_variable(storage), *existing_agent]) as context:
        row = context.injector.get(ArtifactBucketRepository).reserve(context.agent.id, context.organization.id)
        with Session(context.postgres_delegate.engine) as session:
            agent = session.get_one(Agent, context.agent.id)
            agent.deleted_at = datetime.now(UTC)
            session.add(agent)
            session.commit()
        context.injector.get(ArtifactBucketProvisioner).process(row.id)
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.get_one(ArtifactBucket, row.id).state, equal_to("DELETED"))
        assert_that(context.injector.get(GarageProvisioner).key(row.access_key), none())

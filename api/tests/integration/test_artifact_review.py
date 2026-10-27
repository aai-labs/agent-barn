"""Independent-review regressions at real PostgreSQL/Garage boundaries."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from hamcrest import assert_that, equal_to, is_
from sqlalchemy.exc import DBAPIError
from sqlmodel import Session, select

from api.core.config import Config
from api.domains.agents.builders.artifacts import ARTIFACT_INSTRUCTIONS, ARTIFACT_TOOL
from api.domains.agents.repository import AgentRepository
from api.domains.artifacts import config as artifact_config
from api.domains.artifacts.models import Artifact, ArtifactCreate
from api.domains.artifacts.references import pin, release
from api.domains.artifacts.service import ArtifactService
from api.domains.workflows.run_models import WorkflowRun
from api.domains.workflows.runtime_service import WorkflowRuntimeService
from api.infrastructure.crypto import encrypt_token
from api.infrastructure.s3.client import ArtifactStorage
from api.tests.core.givenpy import given
from api.tests.core.modules import set_env_variable
from api.tests.integration.test_artifacts import (
    CONTENT,
    metadata,
    publish,
    runtime_auth,
    staged,
    storage,  # noqa: F401
)
from api.tests.integration.test_workflow_runs import attempt, start
from api.tests.integration.test_workflows import _GIVEN, auth, base

RUNTIME_PATH = "/api/v1/agent-artifacts/runtime/artifacts"


def workflow_file(context):
    headers = runtime_auth(context)
    response, _, _ = start(context)
    repo, active, token = attempt(context, response.json()["id"])
    staged_response = context.client.post(RUNTIME_PATH + f"?attempt_id={active.id}", headers=headers, json=metadata())
    assert_that(staged_response.status_code, equal_to(201), staged_response.text)
    return headers, repo, active, token, staged_response.json()


def test_workflow_file_tool_never_receives_completion_authority(storage):  # noqa: F811
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        headers, _, active, token, row = workflow_file(context)
        handoff = context.injector.get(WorkflowRuntimeService).handoff(active.id, token)
        assert_that(token not in handoff["prompt"], is_(True))
        assert_that("--attempt-token" not in ARTIFACT_TOOL + ARTIFACT_INSTRUCTIONS + handoff["prompt"], is_(True))
        assert_that(str(active.id) in handoff["prompt"], is_(True))
        result = context.client.post(
            f"/workflow-runtime/v1/attempts/{active.id}/result",
            headers=headers,
            json={"summary": "Forged", "criteria_met": True},
        )
        assert_that(result.status_code, equal_to(409))
        response = context.client.put(RUNTIME_PATH + f"/{row['id']}/content", headers=headers, content=CONTENT)
        assert_that(response.status_code, equal_to(200), response.text)
        # Human write authority cannot masquerade as a runtime workflow publication.
        human = context.client.put(
            base(context) + f"/artifacts/{row['id']}/content", headers=auth(context), content=CONTENT
        )
        assert_that(human.status_code, equal_to(403))


def test_upload_locks_file_but_not_run_and_cancel_fences_ready(storage, monkeypatch):  # noqa: F811
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        headers, _, active, _, row = workflow_file(context)
        adapter = context.injector.get(ArtifactStorage)
        original = adapter.put

        def cancel_while_writing(artifact, content):
            original(artifact, content)
            with Session(context.postgres_delegate.engine) as probe:
                with pytest.raises(DBAPIError):
                    probe.exec(select(Artifact).where(Artifact.id == artifact.id).with_for_update(nowait=True)).one()
            with Session(context.postgres_delegate.engine) as probe:
                probe.exec(
                    select(WorkflowRun).where(WorkflowRun.id == active.run_id).with_for_update(nowait=True)
                ).one()
            state = context.client.get(base(context) + f"/workflow-runs/{active.run_id}", headers=auth(context)).json()
            cancelled = context.client.post(
                base(context) + f"/workflow-runs/{active.run_id}/cancel",
                headers=auth(context),
                json={"expected_revision": state["revision"]},
            )
            assert_that(cancelled.status_code, equal_to(200), cancelled.text)

        monkeypatch.setattr(adapter, "put", cancel_while_writing)
        response = context.client.put(RUNTIME_PATH + f"/{row['id']}/content", headers=headers, content=CONTENT)
        assert_that(response.status_code, equal_to(409), response.text)
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.get_one(Artifact, UUID(row["id"])).state, equal_to("DELETING"))


def test_ready_duplicate_does_not_write_storage_again(storage, monkeypatch):  # noqa: F811
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = publish(context)
        calls = []
        monkeypatch.setattr(context.injector.get(ArtifactStorage), "put", lambda *args: calls.append(args))
        assert_that(publish(context, row)["id"], equal_to(row["id"]))
        assert_that(calls, equal_to([]))


def test_runtime_rotation_during_storage_cannot_become_ready(storage, monkeypatch):  # noqa: F811
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        headers = runtime_auth(context)
        row = context.client.post(RUNTIME_PATH, headers=headers, json=metadata()).json()
        adapter = context.injector.get(ArtifactStorage)
        original = adapter.put

        def rotate_during_put(artifact, content):
            original(artifact, content)
            context.agent.ingest_key_encrypted = encrypt_token(
                "rotated", context.injector.get(Config).agent_token_encryption_key
            )
            context.injector.get(AgentRepository).save(context.agent)

        monkeypatch.setattr(adapter, "put", rotate_during_put)
        response = context.client.put(RUNTIME_PATH + f"/{row['id']}/content", headers=headers, content=CONTENT)
        assert_that(response.status_code, equal_to(401), response.text)
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.get_one(Artifact, UUID(row["id"])).state, equal_to("DELETING"))


def test_expired_staging_is_fenced_inside_publication(storage, monkeypatch):  # noqa: F811
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = staged(context)
        with Session(context.postgres_delegate.engine) as session:
            artifact = session.get_one(Artifact, UUID(row["id"]))
            artifact.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.add(artifact)
            session.commit()
        service = context.injector.get(ArtifactService)
        calls = []
        monkeypatch.setattr(service.storage, "put", lambda *args: calls.append(args))
        # Bypass the route's early body-admission check to exercise finalization's own fence.
        with pytest.raises(HTTPException, match="Upload expired") as error:
            service.publish(
                UUID(row["id"]),
                context.agent.id,
                service.runtime_scope(runtime_auth(context)["Authorization"].split(" ", 1)[1])[1],
                CONTENT,
            )
        assert_that(error.value.status_code, equal_to(409))
        assert_that(calls, equal_to([]))


def test_unsafe_purge_backoff_does_not_starve_newer_candidate(storage):  # noqa: F811
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        bad, good = staged(context), staged(context)
        with Session(context.postgres_delegate.engine) as session:
            for value in (bad, good):
                artifact = session.get_one(Artifact, UUID(value["id"]))
                artifact.expires_at = datetime.now(UTC) - timedelta(hours=2)
                if value == bad:
                    artifact.object_key += "/unsafe"
                    artifact.expires_at -= timedelta(hours=1)
                session.add(artifact)
            session.commit()
        service = context.injector.get(ArtifactService)
        assert_that(service.purge(limit=1), equal_to(0))
        with Session(context.postgres_delegate.engine) as session:
            failed = session.get_one(Artifact, UUID(bad["id"]))
            assert_that(failed.purge_attempts, equal_to(1))
            assert_that(failed.expires_at > datetime.now(UTC), is_(True))
        assert_that(service.purge(limit=1), equal_to(1))
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.get_one(Artifact, UUID(good["id"])).state, equal_to("DELETED"))


def test_workflow_attempt_file_count_and_run_context_are_bounded(storage, monkeypatch):  # noqa: F811
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        headers, _, active, _, _ = workflow_file(context)
        path = RUNTIME_PATH + f"?attempt_id={active.id}"
        for _ in range(artifact_config.MAX_FILES_PER_ATTEMPT - 1):
            assert_that(context.client.post(path, headers=headers, json=metadata()).status_code, equal_to(201))
        rejected = context.client.post(path, headers=headers, json=metadata())
        assert_that(rejected.status_code, equal_to(409))
        assert_that("file limit" in rejected.text, is_(True))
        # Independently exercise the shared run manifest budget, not just the per-attempt count.
        monkeypatch.setattr(artifact_config, "MAX_FILES_PER_ATTEMPT", 100)
        monkeypatch.setattr(artifact_config, "MAX_RUN_FILE_CONTEXT_BYTES", 100)
        rejected = context.client.post(path, headers=headers, json=metadata())
        assert_that(rejected.status_code, equal_to(409))
        assert_that("file-reference context limit" in rejected.text, is_(True))


@pytest.mark.parametrize("kind", ["review", "run"])
def test_releasing_pin_preserves_pending_purge_backoff(storage, kind):  # noqa: F811
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = publish(context)
        with Session(context.postgres_delegate.engine) as session:
            owner = uuid4()
            pin(session, UUID(row["id"]), row["checksum"], context.agent.id, context.organization.id, kind, owner)
            artifact = session.get_one(Artifact, UUID(row["id"]))
            retry_at = datetime.now(UTC) + timedelta(minutes=2)
            artifact.state, artifact.expires_at = "DELETING", retry_at
            session.add(artifact)
            session.commit()
            if kind == "review":
                release(session, kind, owner, 30)
                session.commit()
            else:
                context.injector.get(ArtifactService).repository.cleanup_candidates()
                session.expire_all()
            assert_that(session.get_one(Artifact, artifact.id).expires_at, equal_to(retry_at))


@pytest.mark.parametrize("filename", ["bad\x7fname", "report\u202ecsv.exe"])
def test_filename_rejects_control_and_bidi_characters(filename):
    with pytest.raises(ValueError):
        ArtifactCreate.model_validate(metadata(filename=filename))


def test_disabled_storage_handoff_omits_file_tool_instructions():
    with given([set_env_variable({"ARTIFACT_S3_ENDPOINT_URL": ""}), *_GIVEN]) as context:
        response, _, _ = start(context)
        _, active, token = attempt(context, response.json()["id"])
        prompt = context.injector.get(WorkflowRuntimeService).handoff(active.id, token)["prompt"]
        assert_that("file_publication" not in prompt and token not in prompt, is_(True))


def test_overlapping_publication_is_retryable_without_waiting_or_poisoning(storage, monkeypatch):  # noqa: F811
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        headers, _, active, _, row = workflow_file(context)
        path = RUNTIME_PATH + f"/{row['id']}/content"
        writing, release_write = Event(), Event()
        adapter = context.injector.get(ArtifactStorage)
        original = adapter.put
        writes = []

        def blocked_storage(artifact, content):
            writes.append(artifact.id)
            original(artifact, content)
            writing.set()
            assert release_write.wait(10), "Test did not release the first writer"

        monkeypatch.setattr(adapter, "put", blocked_storage)
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(context.client.put, path, headers=headers, content=CONTENT)
            try:
                assert writing.wait(10)
                second = pool.submit(context.client.put, path, headers=headers, content=CONTENT)
                conflict = second.result(timeout=3)
                assert_that(conflict.status_code, equal_to(409), conflict.text)
                assert_that("publication in progress" in conflict.text, is_(True))
                with Session(context.postgres_delegate.engine) as probe:
                    probe.exec(
                        select(WorkflowRun).where(WorkflowRun.id == active.run_id).with_for_update(nowait=True)
                    ).one()
                    assert_that(probe.get_one(Artifact, UUID(row["id"])).state, equal_to("UPLOADING"))
            finally:
                release_write.set()
            assert_that(first.result(timeout=10).status_code, equal_to(200))
        assert_that(len(writes), equal_to(1))
        assert_that(
            context.client.get(base(context) + f"/artifacts/{row['id']}", headers=auth(context)).json()["state"],
            equal_to("READY"),
        )


def test_finalization_contention_releases_run_lock_and_preserves_staging(storage, monkeypatch):  # noqa: F811
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        headers, _, active, _, row = workflow_file(context)
        service = context.injector.get(ArtifactService)
        original = service.repository.authenticate
        finalizing, locked = Event(), Event()
        calls = []

        def before_finalization(token):
            calls.append(token)
            if len(calls) == 2:
                finalizing.set()
                assert locked.wait(10), "Test did not acquire competing file lock"
            return original(token)

        monkeypatch.setattr(service.repository, "authenticate", before_finalization)
        path = RUNTIME_PATH + f"/{row['id']}/content"
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(context.client.put, path, headers=headers, content=CONTENT)
            with Session(context.postgres_delegate.engine) as holder:
                try:
                    assert finalizing.wait(10)
                    holder.exec(
                        select(Artifact).where(Artifact.id == UUID(row["id"])).with_for_update(nowait=True)
                    ).one()
                    locked.set()
                    response = pending.result(timeout=3)
                    assert_that(response.status_code, equal_to(409), response.text)
                    with Session(context.postgres_delegate.engine) as probe:
                        probe.exec(
                            select(WorkflowRun).where(WorkflowRun.id == active.run_id).with_for_update(nowait=True)
                        ).one()
                        assert_that(probe.get_one(Artifact, UUID(row["id"])).state, equal_to("UPLOADING"))
                finally:
                    locked.set()
                    holder.rollback()
        monkeypatch.setattr(service.repository, "authenticate", original)
        retry = context.client.put(path, headers=headers, content=CONTENT)
        assert_that(retry.status_code, equal_to(200), retry.text)


def test_human_workflow_publication_is_rejected_before_request_body(storage):  # noqa: F811
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        _, _, _, _, row = workflow_file(context)

        def unread_body():
            raise AssertionError("Unauthorized file body was consumed")
            yield b"unreachable"

        response = context.client.put(
            base(context) + f"/artifacts/{row['id']}/content", headers=auth(context), content=unread_body()
        )
        assert_that(response.status_code, equal_to(403), response.text)


@pytest.mark.parametrize("owner_deleted", [False, True])
def test_pin_committed_after_cleanup_snapshot_preserves_live_owner_bytes(storage, owner_deleted):  # noqa: F811
    from concurrent.futures import ThreadPoolExecutor

    from botocore.exceptions import ClientError

    from api.domains.agents.models import Agent
    from api.domains.artifacts.models import ArtifactReference
    from api.tests.helpers.artifacts import cleanup_snapshot_barrier

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        published = publish(context)
        artifact_id = UUID(published["id"])
        engine = context.postgres_delegate.engine
        service = context.injector.get(ArtifactService)
        with Session(engine) as session:
            artifact = session.get_one(Artifact, artifact_id)
            artifact.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.add(artifact)
            session.commit()
        with cleanup_snapshot_barrier(engine) as wait_for_snapshot, ThreadPoolExecutor(max_workers=1) as pool:
            cleanup = pool.submit(service.purge)
            wait_for_snapshot()
            with Session(engine) as session:
                pin(
                    session,
                    artifact_id,
                    published["checksum"],
                    context.agent.id,
                    context.organization.id,
                    "review",
                    uuid4(),
                )
                if owner_deleted:
                    agent = session.get_one(Agent, context.agent.id)
                    agent.deleted_at = datetime.now(UTC)
                    session.add(agent)
                session.commit()
            purged = cleanup.result(timeout=10)
        with Session(engine) as session:
            artifact = session.get_one(Artifact, artifact_id)
            reference = session.exec(
                select(ArtifactReference).where(ArtifactReference.artifact_id == artifact_id)
            ).one()
            assert_that(reference.released_at, equal_to(None))
            assert_that(artifact.state, equal_to("DELETED" if owner_deleted else "READY"))
            assert_that(purged, equal_to(1 if owner_deleted else 0))
        client = context.injector.get(ArtifactStorage).client(artifact)
        if owner_deleted:
            with pytest.raises(ClientError) as error:
                client.get_object(Bucket=artifact.bucket, Key=artifact.object_key)
            assert_that(error.value.response["Error"]["Code"], equal_to("NoSuchKey"))
        else:
            response = client.get_object(Bucket=artifact.bucket, Key=artifact.object_key)
            with response["Body"] as stream:
                assert_that(stream.read(), equal_to(CONTENT))

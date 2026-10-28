import base64
import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit
from uuid import UUID, uuid4

import pytest
from hamcrest import assert_that, equal_to, has_length, is_
from sqlmodel import Session, select

from api.core.config import Config
from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.artifacts.credentials import runtime_token
from api.domains.artifacts.models import Artifact, ArtifactReference
from api.domains.artifacts.service import ArtifactService
from api.domains.workflows.run_models import AttemptResult
from api.domains.workflows.runtime_service import WorkflowRuntimeService
from api.infrastructure.crypto import encrypt_token
from api.tests.core.givenpy import given
from api.tests.core.modules import set_env_variable
from api.tests.helpers.artifacts import garage_storage, provision_agents
from api.tests.helpers.workflows import draft
from api.tests.integration.test_workflow_runs import attempt, start
from api.tests.integration.test_workflows import _GIVEN, auth, base, switch_member

CONTENT = b"actual private file bytes\x00\xff\n"


@pytest.fixture(scope="module")
def storage():
    with garage_storage() as fixture:
        yield fixture


def metadata(content=CONTENT, **changes):
    return {
        "filename": "report.csv",
        "content_type": "text/csv",
        "size": len(content),
        "checksum": hashlib.sha256(content).hexdigest(),
        **changes,
    }


def staged(context, payload=None):
    provision_agents(context)
    response = context.client.post(base(context) + "/artifacts", headers=auth(context), json=payload or metadata())
    assert_that(response.status_code, equal_to(201), response.text)
    return response.json()


def publish(context, row=None, content=CONTENT):
    row = row or staged(context)
    response = context.client.put(
        base(context) + f"/artifacts/{row['id']}/content", headers=auth(context), content=content
    )
    assert_that(response.status_code, equal_to(200), response.text)
    return response.json()


def test_real_private_bytes_signed_download_and_fresh_link(storage):
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = publish(context)
        assert_that(row["state"], equal_to("READY"))
        path = base(context) + f"/artifacts/{row['id']}"
        link = context.client.get(path + "/download-link", headers=auth(context)).json()
        response = context.client.get(link["url"])
        assert_that(response.content, equal_to(CONTENT))
        assert_that(response.headers["content-disposition"].startswith("attachment"), is_(True))
        assert_that(context.client.get(link["url"].split("?", 1)[0]).status_code, equal_to(403))
        access = parse_qs(urlsplit(link["url"]).query)["access"][0]
        assert_that("X-Amz-Expires=900" in base64.urlsafe_b64decode(access).decode(), is_(True))
        assert_that(
            context.client.get(path + "/download-link?seconds=3601", headers=auth(context)).status_code, equal_to(422)
        )
        listing = context.client.get(base(context) + "/artifacts", headers=auth(context)).json()
        assert_that(listing["items"], has_length(1))
        assert_that(set(row).intersection({"bucket", "object_key", "organization_id"}), equal_to(set()))


def test_download_uses_app_origin_and_provider_authority_without_a_public_store(storage):
    env, _ = storage
    with given([set_env_variable({**env, "WEB_APP_URL": "https://files.example.test"}), *_GIVEN]) as context:
        row = publish(context)
        path = base(context) + f"/artifacts/{row['id']}/download-link"
        response = context.client.get(path, headers=auth(context))
        assert_that(response.status_code, equal_to(200))
        url = response.json()["url"]
        parsed = urlsplit(url)
        assert_that(f"{parsed.scheme}://{parsed.netloc}", equal_to("https://files.example.test"))
        assert_that("agent-artifact-test" in url or env["ARTIFACT_S3_ENDPOINT_URL"] in url, is_(False))
        download = context.client.get(url)
        assert_that(download.status_code, equal_to(200))
        assert_that(download.content, equal_to(CONTENT))
        assert_that(download.headers["cache-control"], equal_to("private, no-store"))
        assert_that(download.headers["x-content-type-options"], equal_to("nosniff"))
        assert_that(download.headers["content-type"], equal_to("application/octet-stream"))
        assert_that(download.headers["content-length"], equal_to(str(len(CONTENT))))
        assert_that(context.client.get(parsed.path).status_code, equal_to(403))
        tampered = urlunsplit(parsed._replace(query=urlencode({"access": "invalid"})))
        assert_that(context.client.get(tampered).status_code, equal_to(403))
        headers = runtime_auth(context)
        runtime_path = f"/api/v1/agent-artifacts/runtime/artifacts/{row['id']}/download-link"
        shared = context.client.get(runtime_path, headers=headers).json()["url"]
        assert_that(urlsplit(shared).netloc, equal_to(parsed.netloc))
        assert_that(context.client.get(shared).content, equal_to(CONTENT))


def test_provider_rejects_changed_authority_and_capability_for_a_different_file(storage):
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = publish(context)
        other = publish(context)
        link = context.client.get(
            base(context) + f"/artifacts/{row['id']}/download-link", headers=auth(context)
        ).json()["url"]
        assert_that(context.client.get(link).content, equal_to(CONTENT))
        wrong_target = link.replace(row["id"], other["id"])
        assert_that(context.client.get(wrong_target).status_code, equal_to(403))
        wrong_tenant = link.replace(str(context.organization.id), str(uuid4()))
        assert_that(context.client.get(wrong_tenant).status_code, equal_to(403))
        parsed = urlsplit(link)
        access = parse_qs(parsed.query)["access"][0]
        authority = base64.urlsafe_b64decode(access).decode().replace("X-Amz-Expires=900", "X-Amz-Expires=901")
        changed = base64.urlsafe_b64encode(authority.encode()).decode()
        forged = urlunsplit(parsed._replace(query=urlencode({"access": changed})))
        denied = context.client.get(forged)
        assert_that(denied.status_code, equal_to(403))
        assert_that("garage" in denied.text.lower() or "Signature" in denied.text, is_(False))


@pytest.mark.parametrize("content", [b"", bytes(range(256)) * 1000])
def test_app_streams_exact_empty_and_multichunk_bytes_with_safe_unicode_filename(storage, content):
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = publish(context, staged(context, metadata(content, filename="résumé.csv")), content)
        link = context.client.get(
            base(context) + f"/artifacts/{row['id']}/download-link", headers=auth(context)
        ).json()["url"]
        response = context.client.get(link)
        assert_that(response.status_code, equal_to(200))
        assert_that(response.content, equal_to(content))
        assert_that("r%C3%A9sum%C3%A9.csv" in response.headers["content-disposition"], is_(True))


def test_private_store_failure_returns_retryable_error_without_its_address(storage, monkeypatch):
    from api.infrastructure.s3.client import ArtifactStorage

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = publish(context)
        link = context.client.get(
            base(context) + f"/artifacts/{row['id']}/download-link", headers=auth(context)
        ).json()["url"]

        def unavailable(*args):
            raise OSError("Private provider URL and credentials must not escape")

        monkeypatch.setattr(context.injector.get(ArtifactStorage), "download", unavailable)
        response = context.client.get(link)
        assert_that(response.status_code, equal_to(503))
        assert_that(response.json(), equal_to({"detail": "Artifact storage is unavailable"}))


def test_checksum_failure_unavailable_and_retry_gets_new_identity(storage):
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = staged(context)
        response = context.client.put(
            base(context) + f"/artifacts/{row['id']}/content", headers=auth(context), content=b"wrong"
        )
        assert_that(response.status_code, equal_to(422))
        assert_that(
            context.client.get(
                base(context) + f"/artifacts/{row['id']}/download-link", headers=auth(context)
            ).status_code,
            equal_to(404),
        )
        replacement = publish(context)
        assert_that(replacement["id"] != row["id"], is_(True))
        assert_that(context.injector.get(ArtifactService).purge(), equal_to(1))


def test_duplicate_publish_immutable_and_changed_bytes_rejected(storage):
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = publish(context)
        assert_that(publish(context, row)["id"], equal_to(row["id"]))
        response = context.client.put(
            base(context) + f"/artifacts/{row['id']}/content", headers=auth(context), content=b"changed"
        )
        assert_that(response.status_code, equal_to(422))
        assert_that(
            context.client.get(base(context) + f"/artifacts/{row['id']}", headers=auth(context)).json()["state"],
            equal_to("READY"),
        )


def runtime_auth(context):
    provision_agents(context)
    context.agent.status = AgentStatus.RUNNING
    context.agent.ingest_key_encrypted = encrypt_token(
        "test-ingest", context.injector.get(Config).agent_token_encryption_key
    )
    context.injector.get(AgentRepository).save(context.agent)
    return {"Authorization": "Bearer " + runtime_token(context.agent.id, "test-ingest")}


@pytest.mark.parametrize("runtime", ["hermes", "openclaw"])
def test_runtime_chat_publication_and_rotated_credential(storage, runtime):
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        context.agent.agent_type = runtime
        headers = runtime_auth(context)
        path = "/api/v1/agent-artifacts/runtime/artifacts"
        assert_that(context.client.get("/artifact-runtime/v1/artifacts", headers=headers).status_code, equal_to(404))
        row = context.client.post(path, headers=headers, json=metadata()).json()
        response = context.client.put(path + f"/{row['id']}/content", headers=headers, content=CONTENT)
        assert_that(response.status_code, equal_to(200), response.text)
        link = context.client.get(path + f"/{row['id']}/download-link", headers=headers).json()
        assert_that(context.client.get(link["url"]).content, equal_to(CONTENT))
        context.agent.ingest_key_encrypted = encrypt_token(
            "rotated", context.injector.get(Config).agent_token_encryption_key
        )
        context.injector.get(AgentRepository).save(context.agent)
        assert_that(context.client.get(path, headers=headers).status_code, equal_to(401))
        # Previously issued bearer URL remains usable until its provider expiry.
        assert_that(context.client.get(link["url"]).content, equal_to(CONTENT))


def test_workflow_exact_handoff_pins_retention_and_cancel_keeps_files(storage):
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        headers = runtime_auth(context)
        definition = draft()
        definition["steps"].append({**definition["steps"][0], "id": str(uuid4()), "name": "Consume file"})
        saved = context.client.post(base(context) + "/workflows", headers=auth(context), json=definition).json()
        response, _, _ = start(context, saved)
        run_id = response.json()["id"]
        repo, current, token = attempt(context, run_id)
        path = "/api/v1/agent-artifacts/runtime/artifacts"
        row = context.client.post(path + f"?attempt_id={current.id}", headers=headers, json=metadata()).json()
        response = context.client.put(path + f"/{row['id']}/content", headers=headers, content=CONTENT)
        assert_that(response.status_code, equal_to(200), response.text)
        repo.complete(current.id, token, AttemptResult(summary="File prepared", criteria_met=True))
        _, next_attempt, next_token = attempt(context, run_id)
        packet = context.injector.get(WorkflowRuntimeService).handoff(next_attempt.id, next_token)
        assert_that(row["id"] in packet["prompt"] and row["checksum"] in packet["prompt"], is_(True))
        with Session(context.postgres_delegate.engine) as session:
            artifact = session.get_one(Artifact, UUID(row["id"]))
            artifact.expires_at = datetime.now(UTC) - timedelta(days=60)
            session.add(artifact)
            session.commit()
        assert_that(context.injector.get(ArtifactService).purge(), equal_to(0))
        assert_that(
            context.client.delete(base(context) + f"/artifacts/{row['id']}", headers=auth(context)).status_code,
            equal_to(409),
        )
        state = context.client.get(base(context) + f"/workflow-runs/{run_id}", headers=auth(context)).json()
        context.client.post(
            base(context) + f"/workflow-runs/{run_id}/cancel",
            headers=auth(context),
            json={"expected_revision": state["revision"]},
        )
        repo.advance(UUID(run_id), stopped=True)
        with Session(context.postgres_delegate.engine) as session:
            artifact = session.get_one(Artifact, UUID(row["id"]))
            ref = session.exec(select(ArtifactReference).where(ArtifactReference.artifact_id == artifact.id)).one()
            assert_that(
                ref.released_at is not None and artifact.expires_at > datetime.now(UTC) + timedelta(days=29), is_(True)
            )
        assert_that(
            context.client.get(
                base(context) + f"/artifacts/{row['id']}/download-link", headers=auth(context)
            ).status_code,
            equal_to(200),
        )


def test_stale_attempt_cannot_publish_orphan_bytes(storage):
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        headers = runtime_auth(context)
        response, _, _ = start(context)
        repo, current, token = attempt(context, response.json()["id"])
        path = "/api/v1/agent-artifacts/runtime/artifacts"
        row = context.client.post(path + f"?attempt_id={current.id}", headers=headers, json=metadata()).json()
        repo.complete(current.id, token, AttemptResult(summary="Done", criteria_met=True))
        response = context.client.put(path + f"/{row['id']}/content", headers=headers, content=CONTENT)
        assert_that(response.status_code, equal_to(409), response.text)
        with Session(context.postgres_delegate.engine) as session:
            record = session.get_one(Artifact, UUID(row["id"]))
            record.expires_at = datetime.now(UTC) - timedelta(hours=1)
            session.add(record)
            session.commit()
        assert_that(context.injector.get(ArtifactService).purge(), equal_to(1))


def test_viewer_read_current_access_and_update_gate(storage):
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = publish(context)
        switch_member(context)
        from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID
        from api.tests.steps.agent import there_is_agent_access

        there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID)(context)
        path = base(context) + f"/artifacts/{row['id']}"
        assert_that(context.client.get(path + "/download-link", headers=auth(context)).status_code, equal_to(200))
        assert_that(context.client.delete(path, headers=auth(context)).status_code, equal_to(403))
        assert_that(
            context.client.post(base(context) + "/artifacts", headers=auth(context), json=metadata()).status_code,
            equal_to(403),
        )
        switch_member(context)
        assert_that(context.client.get(path, headers=auth(context)).status_code, equal_to(404))


def test_soft_and_hard_delete_preserve_cleanup_journal(storage):
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = publish(context)
        with Session(context.postgres_delegate.engine) as session:
            agent = session.get_one(type(context.agent), context.agent.id)
            agent.deleted_at = datetime.now(UTC)
            session.add(agent)
            session.commit()
        assert_that(context.client.get(base(context) + "/artifacts", headers=auth(context)).status_code, equal_to(404))
        with Session(context.postgres_delegate.engine) as session:
            session.delete(session.get_one(type(context.agent), context.agent.id))
            session.commit()
        assert_that(context.injector.get(ArtifactService).purge(), equal_to(1))
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.get_one(Artifact, UUID(row["id"])).state, equal_to("DELETED"))


def test_signed_link_expires_without_deleting_file(storage):
    import time

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = publish(context)
        path = base(context) + f"/artifacts/{row['id']}/download-link"
        old = context.client.get(path + "?seconds=1", headers=auth(context)).json()
        assert_that(context.client.get(old["url"]).content, equal_to(CONTENT))
        time.sleep(2)
        expired = context.client.get(old["url"])
        assert_that(expired.status_code, equal_to(403))  # Provider rejection is concealed by the app.
        assert_that(expired.content != CONTENT, is_(True))
        fresh = context.client.get(path, headers=auth(context)).json()
        assert_that(context.client.get(fresh["url"]).content, equal_to(CONTENT))


def test_failed_storage_after_put_never_ready_and_purge_retries(storage, monkeypatch):
    from api.infrastructure.s3.client import ArtifactStorage

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = staged(context)
        adapter = context.injector.get(ArtifactStorage)
        original = adapter.put

        def fail_after_put(artifact, content):
            original(artifact, content)
            raise OSError("Lost response after accepting bytes")

        monkeypatch.setattr(adapter, "put", fail_after_put)
        response = context.client.put(
            base(context) + f"/artifacts/{row['id']}/content", headers=auth(context), content=CONTENT
        )
        assert_that(response.status_code, equal_to(503))
        assert_that(
            context.client.get(base(context) + "/artifacts", headers=auth(context)).json()["total"], equal_to(0)
        )
        original_delete = adapter.delete

        def offline(_):
            raise OSError("Storage offline")

        monkeypatch.setattr(adapter, "delete", offline)
        service = context.injector.get(ArtifactService)
        assert_that(service.purge(), equal_to(0))
        with Session(context.postgres_delegate.engine) as session:
            record = session.get_one(Artifact, UUID(row["id"]))
            assert_that((record.state, record.purge_attempts), equal_to(("DELETING", 1)))
            bucket, key = record.bucket, record.object_key
            s3 = adapter.client(record)
            record.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.add(record)
            session.commit()
        monkeypatch.setattr(adapter, "delete", original_delete)
        assert_that(service.purge(), equal_to(1))
        assert_that(service.purge(), equal_to(0))
        with pytest.raises(s3.exceptions.NoSuchKey):
            s3.get_object(Bucket=bucket, Key=key)


def test_incomplete_upload_cleanup_and_unsafe_key_refusal(storage):
    from api.domains.artifacts.repository import object_key

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        incomplete = staged(context)
        protected = publish(context)
        with Session(context.postgres_delegate.engine) as session:
            row = session.get_one(Artifact, UUID(incomplete["id"]))
            row.expires_at = datetime.now(UTC) - timedelta(hours=2)
            other = session.get_one(Artifact, UUID(protected["id"]))
            row.object_key = other.object_key + "/corrupt"
            session.add(row)
            session.commit()
        assert_that(context.injector.get(ArtifactService).purge(), equal_to(0))
        path = base(context) + f"/artifacts/{protected['id']}/download-link"
        assert_that(
            context.client.get(context.client.get(path, headers=auth(context)).json()["url"]).content, equal_to(CONTENT)
        )
        with Session(context.postgres_delegate.engine) as session:
            row = session.get_one(Artifact, UUID(incomplete["id"]))
            row.object_key = object_key(row)
            row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.add(row)
            session.commit()
        assert_that(context.injector.get(ArtifactService).purge(), equal_to(1))


def test_read_only_key_cannot_publish_or_delete(storage):
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = publish(context)
        key = context.client.post(
            "/api/v1/auth/me/api-keys", headers=auth(context), json={"name": "Files", "access_mode": "READ_ONLY"}
        ).json()["token"]
        key_auth = {"Authorization": "Bearer " + key}
        path = base(context) + f"/artifacts/{row['id']}"
        assert_that(context.client.get(path + "/download-link", headers=key_auth).status_code, equal_to(200))
        assert_that(
            context.client.post(base(context) + "/artifacts", headers=key_auth, json=metadata()).status_code,
            equal_to(403),
        )
        assert_that(context.client.delete(path, headers=key_auth).status_code, equal_to(403))


def test_disabled_storage_keeps_text_workflows_usable():
    with given([set_env_variable({"ARTIFACT_S3_ENDPOINT_URL": ""}), *_GIVEN]) as context:
        response = context.client.post(base(context) + "/artifacts", headers=auth(context), json=metadata())
        assert_that(response.status_code, equal_to(503))
        response, _, _ = start(context)
        repo, current, token = attempt(context, response.json()["id"])
        repo.complete(current.id, token, AttemptResult(summary="Text remains usable", criteria_met=True))
        assert_that(
            context.client.get(base(context) + f"/workflow-runs/{current.run_id}", headers=auth(context)).json()[
                "final_summary"
            ],
            equal_to("Text remains usable"),
        )


@pytest.mark.parametrize("general", [False, True])
def test_custom_read_role_and_general_access_need_no_activity_permission(storage, general):
    from api.domains.rbac.catalog import PERMISSION_ID_BY_KEY, PermissionKey
    from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
    from api.tests.steps.agent import there_is_agent_access

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = publish(context)
        role = AgentAccessRole(name="File reader", organization_id=context.organization.id)
        with Session(context.postgres_delegate.engine) as session:
            session.add(role)
            session.flush()
            session.add(
                AgentAccessRolePermission(role_id=role.id, permission_id=PERMISSION_ID_BY_KEY[PermissionKey.AGENT_READ])
            )
            session.commit()
            role_id = role.id
        switch_member(context)
        if general:
            context.agent.general_access_role_id = role_id
            context.injector.get(AgentRepository).save(context.agent)
        else:
            there_is_agent_access(access_role_id=role_id)(context)
        path = base(context) + f"/artifacts/{row['id']}"
        assert_that(context.client.get(path + "/download-link", headers=auth(context)).status_code, equal_to(200))
        assert_that(context.client.delete(path, headers=auth(context)).status_code, equal_to(403))
        storage_path = base(context) + "/artifacts/storage"
        assert_that(context.client.get(storage_path, headers=auth(context)).json(), equal_to({"state": "READY"}))
        assert_that(context.client.post(storage_path, headers=auth(context)).status_code, equal_to(403))


def test_cross_tenant_and_runtime_identity_cannot_select_another_agents_bytes(storage):
    from api.tests.steps.agent import there_is_an_agent
    from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = publish(context)
        link = context.client.get(base(context) + f"/artifacts/{row['id']}/download-link", headers=auth(context)).json()
        there_is_an_organization_with_user_and_access_token()(context)
        there_is_an_agent(status=AgentStatus.STOPPED)(context)
        path = base(context) + f"/artifacts/{row['id']}"
        assert_that(context.client.get(path, headers=auth(context)).status_code, equal_to(404))
        assert_that(context.client.delete(path, headers=auth(context)).status_code, equal_to(404))
        machine = runtime_auth(context)
        assert_that(
            context.client.get(
                f"/api/v1/agent-artifacts/runtime/artifacts/{row['id']}/download-link", headers=machine
            ).status_code,
            equal_to(404),
        )
        assert_that(context.client.get(link["url"]).content, equal_to(CONTENT))


def test_exact_review_reference_keeps_bytes_until_final_release(storage):
    from fastapi import HTTPException

    from api.domains.artifacts.references import pin, release

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = publish(context)
        owner_id = uuid4()
        with Session(context.postgres_delegate.engine) as session:
            with pytest.raises(HTTPException) as conflict:
                pin(session, UUID(row["id"]), "0" * 64, context.agent.id, context.organization.id, "review", owner_id)
            assert_that(conflict.value.status_code, equal_to(409))
            pin(
                session, UUID(row["id"]), row["checksum"], context.agent.id, context.organization.id, "review", owner_id
            )
            artifact = session.get_one(Artifact, UUID(row["id"]))
            artifact.expires_at = datetime.now(UTC) - timedelta(days=31)
            session.add(artifact)
            session.commit()
        assert_that(context.injector.get(ArtifactService).purge(), equal_to(0))
        with Session(context.postgres_delegate.engine) as session:
            release(session, "review", owner_id, 30)
            session.commit()
            assert_that(
                session.get_one(Artifact, UUID(row["id"])).expires_at > datetime.now(UTC) + timedelta(days=29),
                is_(True),
            )


def test_attempt_expiring_during_real_storage_cannot_become_ready(storage, monkeypatch):
    import time

    from api.domains.workflows.run_models import WorkflowAttempt
    from api.infrastructure.s3.client import ArtifactStorage

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        headers = runtime_auth(context)
        response, _, _ = start(context)
        _, active, _ = attempt(context, response.json()["id"])
        path = "/api/v1/agent-artifacts/runtime/artifacts"
        row = context.client.post(path + f"?attempt_id={active.id}", headers=headers, json=metadata()).json()
        with Session(context.postgres_delegate.engine) as session:
            current = session.get_one(WorkflowAttempt, active.id)
            current.expires_at = datetime.now(UTC) + timedelta(seconds=2)
            session.add(current)
            session.commit()
        adapter = context.injector.get(ArtifactStorage)
        original = adapter.put

        def slow_storage(artifact, content):
            original(artifact, content)
            time.sleep(2)

        monkeypatch.setattr(adapter, "put", slow_storage)
        response = context.client.put(path + f"/{row['id']}/content", headers=headers, content=CONTENT)
        assert_that(response.status_code, equal_to(409), response.text)
        assert_that(
            context.client.get(base(context) + "/artifacts", headers=auth(context)).json()["total"], equal_to(0)
        )
        assert_that(context.injector.get(ArtifactService).purge(), equal_to(1))


def test_human_authority_revoked_during_storage_cannot_publish(storage, monkeypatch):
    from api.domains.users.organization_users.models import OrganizationUser
    from api.infrastructure.s3.client import ArtifactStorage

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = staged(context)
        adapter = context.injector.get(ArtifactStorage)
        original = adapter.put

        def revoked_during_put(artifact, content):
            original(artifact, content)
            with Session(context.postgres_delegate.engine) as session:
                session.delete(session.get_one(OrganizationUser, context.organization_user.id))
                session.commit()

        monkeypatch.setattr(adapter, "put", revoked_during_put)
        response = context.client.put(
            base(context) + f"/artifacts/{row['id']}/content", headers=auth(context), content=CONTENT
        )
        assert_that(response.status_code, equal_to(403), response.text)
        with Session(context.postgres_delegate.engine) as session:
            assert_that(session.get_one(Artifact, UUID(row["id"])).state, equal_to("DELETING"))


def test_concurrent_finalization_preserves_immutable_garage_bytes(storage):
    from concurrent.futures import ThreadPoolExecutor

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        row = staged(context)
        path = base(context) + f"/artifacts/{row['id']}"
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(
                pool.map(
                    lambda _: context.client.put(path + "/content", headers=auth(context), content=CONTENT), range(2)
                )
            )
        assert_that(all(response.status_code in {200, 409} for response in responses), is_(True))
        assert_that(any(response.status_code == 200 for response in responses), is_(True))
        changed = context.client.put(path + "/content", headers=auth(context), content=b"replacement")
        assert_that(changed.status_code, equal_to(422))
        link = context.client.get(path + "/download-link", headers=auth(context)).json()
        assert_that(context.client.get(link["url"]).content, equal_to(CONTENT))


def test_previous_storage_layout_has_specific_download_error_without_affecting_current_files(storage):
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        previous, current = publish(context), publish(context)
        with Session(context.postgres_delegate.engine) as session:
            row = session.get_one(Artifact, UUID(previous["id"]))
            row.bucket = "agent-artifacts"
            session.add(row)
            session.commit()
        response = context.client.get(
            base(context) + f"/artifacts/{previous['id']}/download-link", headers=auth(context)
        )
        assert_that(response.status_code, equal_to(409))
        assert_that("previous storage layout" in response.json()["detail"], equal_to(True))
        assert_that("uploaded again" in response.json()["detail"], equal_to(True))
        link = context.client.get(base(context) + f"/artifacts/{current['id']}/download-link", headers=auth(context))
        assert_that(link.status_code, equal_to(200))
        assert_that(context.client.get(link.json()["url"]).content, equal_to(CONTENT))


def test_current_file_missing_usable_credentials_reports_specific_cause(storage):
    from api.domains.artifacts.models import ArtifactBucket

    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        artifact = publish(context)
        with Session(context.postgres_delegate.engine) as session:
            row = session.exec(select(ArtifactBucket)).one()
            row.state = "PENDING"
            session.add(row)
            session.commit()
        response = context.client.get(
            base(context) + f"/artifacts/{artifact['id']}/download-link", headers=auth(context)
        )
        assert_that(response.status_code, equal_to(503))
        assert_that("Storage credentials for this file are unavailable" in response.json()["detail"], equal_to(True))


def test_files_have_stable_pagination_when_publication_timestamps_match(storage):
    env, _ = storage
    with given([set_env_variable(env), *_GIVEN]) as context:
        artifacts = [publish(context) for _ in range(3)]
        with Session(context.postgres_delegate.engine) as session:
            for artifact in artifacts:
                row = session.get_one(Artifact, UUID(artifact["id"]))
                row.created_at = datetime(2026, 10, 26, tzinfo=UTC)
                session.add(row)
            session.commit()
        ids = []
        for page in (1, 2):
            response = context.client.get(base(context) + f"/artifacts?page={page}&page_size=2", headers=auth(context))
            assert_that(response.status_code, equal_to(200))
            assert_that(response.json()["total"], equal_to(3))
            ids.extend(item["id"] for item in response.json()["items"])
        assert_that(ids, equal_to(sorted((row["id"] for row in artifacts), reverse=True)))

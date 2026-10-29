"""Workflow inputs and accepted outputs against PostgreSQL and private Garage bytes."""

from uuid import UUID, uuid4

import pytest
from sqlmodel import Session, select

from api.domains.artifacts.models import ArtifactReference
from api.domains.workflows.repository import WorkflowConflict
from api.domains.workflows.run_models import WorkflowRun
from api.domains.workflows.runtime_service import WorkflowRuntimeService
from api.tests.core.givenpy import given
from api.tests.core.modules import set_env_variable
from api.tests.helpers.artifacts import garage_storage
from api.tests.helpers.workflows import draft
from api.tests.integration.test_artifacts import CONTENT, metadata, publish, runtime_auth, staged
from api.tests.integration.test_workflow_runs import attempt, result, start
from api.tests.integration.test_workflows import _GIVEN, auth, base


@pytest.fixture(scope="module")
def storage():
    with garage_storage() as fixture:
        yield fixture[0]


def file_workflow(context):
    body = draft()
    body["inputs"][0]["type"] = "file"
    body["steps"].append({**body["steps"][0], "id": str(uuid4()), "name": "Consume file"})
    response = context.client.post(base(context) + "/workflows", headers=auth(context), json=body)
    assert response.status_code == 201, response.text
    return response.json()


def file_value(row):
    return {"artifact_id": row["id"], "checksum": row["checksum"]}


def publish_output(context, current, headers, content=CONTENT):
    path = "/api/v1/agent-artifacts/runtime/artifacts"
    response = context.client.post(
        path, params={"attempt_id": str(current.id)}, headers=headers, json=metadata(content)
    )
    assert response.status_code == 201, response.text
    row = response.json()
    response = context.client.put(path + f"/{row['id']}/content", headers=headers, content=content)
    assert response.status_code == 200, response.text
    return response.json()


def test_exact_inputs_and_checkpoint_files_are_pinned_and_exposed_separately(storage):
    with given([set_env_variable(storage), *_GIVEN]) as context:
        source = publish(context)
        saved = file_workflow(context)
        inputs = {"period": file_value(source)}
        response, _, payload = start(context, saved, inputs=inputs)
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        assert response.json()["inputs"]["period"] == {
            **inputs["period"],
            "filename": source["filename"],
            "size": source["size"],
        }
        repeated = context.client.post(
            base(context) + f"/workflows/{saved['id']}/runs", headers=auth(context), json=payload
        )
        assert repeated.json()["id"] == run_id
        path = base(context) + f"/artifacts/{source['id']}"
        assert context.client.delete(path, headers=auth(context)).status_code == 409
        repository, first, token = attempt(context, run_id)
        handoff = context.injector.get(WorkflowRuntimeService).handoff(first.id, token)
        assert handoff["files"] == [response.json()["inputs"]["period"]]
        output = publish_output(context, first, runtime_auth(context))
        repository.complete(first.id, token, result())
        second, _ = repository.advance(first.run_id)
        handoff = context.injector.get(WorkflowRuntimeService).handoff(second.id, repository.token(second.id))
        assert {file["artifact_id"] for file in handoff["files"]} == {source["id"], output["id"]}
        final = publish_output(context, second, runtime_auth(context), b"final deliverable\n")
        repository.complete(second.id, repository.token(second.id), result())
        detail = context.client.get(base(context) + f"/workflow-runs/{run_id}", headers=auth(context)).json()
        assert detail["state"] == "SUCCEEDED"
        assert [file["artifact_id"] for file in detail["final_artifacts"]] == [final["id"]]
        assert detail["steps"][0]["artifacts"][0]["artifact_id"] == output["id"]
        with Session(context.postgres_delegate.engine) as session:
            refs = session.exec(select(ArtifactReference).where(ArtifactReference.owner_id == first.run_id)).all()
            assert len(refs) == 3 and all(ref.released_at for ref in refs)
        assert context.client.delete(path, headers=auth(context)).status_code == 204


@pytest.mark.parametrize("invalid", ["checksum", "missing", "uploading", "other_agent"])
def test_invalid_file_input_rolls_back_run_and_all_pins(storage, invalid):
    from api.domains.artifacts.models import Artifact

    with given([set_env_variable(storage), *_GIVEN]) as context:
        row = staged(context) if invalid == "uploading" else publish(context)
        value = file_value(row)
        if invalid == "checksum":
            value["checksum"] = "0" * 64
        elif invalid == "missing":
            value["artifact_id"] = str(uuid4())
        elif invalid == "other_agent":
            with Session(context.postgres_delegate.engine) as session:
                artifact = session.get_one(Artifact, UUID(row["id"]))
                artifact.agent_id = uuid4()
                session.add(artifact)
                session.commit()
        response, _, _ = start(context, file_workflow(context), inputs={"period": value})
        assert response.status_code == (409 if invalid == "checksum" else 404), response.text
        with Session(context.postgres_delegate.engine) as session:
            assert session.exec(select(WorkflowRun)).all() == []
            assert session.exec(select(ArtifactReference)).all() == []


@pytest.mark.parametrize("transition", ["cancel", "failure", "revoke"])
def test_input_pins_follow_settlement_and_parked_run_lifecycle(storage, transition):
    from sqlalchemy import text

    from api.domains.workflows.run_models import AttemptFailure

    with given([set_env_variable(storage), *_GIVEN]) as context:
        source = publish(context)
        response, _, _ = start(context, file_workflow(context), inputs={"period": file_value(source)})
        assert response.status_code == 202, response.text
        repository, current, token = attempt(context, response.json()["id"])
        runtime_headers = runtime_auth(context)
        link_path = f"/api/v1/agent-artifacts/runtime/artifacts/{source['id']}/download-link?attempt_id={current.id}"
        assert context.client.get(link_path, headers=runtime_headers).status_code == 200
        if transition == "cancel":
            run = repository.inspect(current.run_id)[0]
            response = context.client.post(
                base(context) + f"/workflow-runs/{run.id}/cancel",
                headers=auth(context),
                json={"expected_revision": run.revision},
            )
            assert response.status_code == 200, response.text
            repository.advance(run.id, stopped=True)
        elif transition == "failure":
            repository.fail(current.id, token, AttemptFailure(reason="Upload failed after possible external effects"))
        else:
            with context.postgres_delegate.engine.begin() as connection:
                connection.execute(text("DELETE FROM user_organization WHERE user_id=:user"), {"user": context.user.id})
            repository.advance(current.run_id, stopped=True)
        assert context.client.get(link_path, headers=runtime_headers).status_code == 409
        with pytest.raises(WorkflowConflict, match="fenced"):
            repository.admit(current.id, token)
        with Session(context.postgres_delegate.engine) as session:
            ref = session.exec(select(ArtifactReference).where(ArtifactReference.owner_id == current.run_id)).one()
            assert (ref.released_at is not None) == (transition == "cancel")
        run = repository.inspect(current.run_id)[0]
        assert run.state == {"cancel": "CANCELLED", "failure": "BLOCKED", "revoke": "PAUSED"}[transition]

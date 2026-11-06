"""AF-412: Agents record their own Tasks through the ingest app, authenticated by their ingest key."""

import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid7

import uvicorn
from fastapi import status
from hamcrest import assert_that, contains_exactly, contains_string, equal_to, has_entries
from injector import Module, provider, singleton
from sqlmodel import Session, col, select
from starlette.testclient import TestClient

from api.api_app import create_app
from api.domains.agents.models import AgentStatus
from api.domains.agents.repository import AgentRepository
from api.domains.artifacts.buckets import bucket_name
from api.domains.artifacts.credentials import runtime_token
from api.domains.artifacts.models import Artifact, ArtifactBucket, ArtifactReference
from api.domains.artifacts.storage import ArtifactDownload, ArtifactStorage
from api.infrastructure.crypto import encrypt_token
from api.ingest_app import create_ingest_app
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_an_agent,
)
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization


def _given(**env: str):
    return [
        set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY, **env}),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule()]),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization(),
    ]


def _an_agent_with_an_ingest_key(name: str = "Test Agent", key: str = "test-ingest-key-abc"):
    def step(context):
        there_is_an_agent(name=name)(context)
        repository: AgentRepository = context.injector.get(AgentRepository)
        agent = repository.get_by_id(context.agent.id)
        assert agent is not None
        agent.ingest_key_encrypted = encrypt_token(key, TEST_ENCRYPTION_KEY)
        repository.save(agent)
        context.agent = agent
        context.ingest_key = key
        context.ingest_client = TestClient(create_ingest_app(injector=context.injector))

    return step


def _the_agent_is_remembered_as(name: str):
    def step(context):
        setattr(context, name, (context.agent, context.ingest_key))

    return step


def _headers(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"}


def _tasks_url(agent) -> str:
    return f"/ingest/v1/agents/{agent.id}/tasks"


def _create(context, title: str = "Reconcile invoices", agent=None, key: str | None = None, **fields):
    agent = agent or context.agent
    return context.ingest_client.post(
        _tasks_url(agent), json={"title": title, **fields}, headers=_headers(key or context.ingest_key)
    )


# --- authentication ---


def test_a_task_cannot_be_created_without_the_agents_ingest_key():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        response = _create(context, key="wrong-key")

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


def test_a_task_cannot_be_created_without_an_authorization_header():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        response = context.ingest_client.post(_tasks_url(context.agent), json={"title": "Reconcile invoices"})

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_an_agent_cannot_act_as_another_agent_with_its_own_key():
    with given(
        [
            *_given(),
            _an_agent_with_an_ingest_key(),
            _the_agent_is_remembered_as("first"),
            _an_agent_with_an_ingest_key(name="Second", key="second-key"),
        ]
    ) as context:
        first_agent, _ = context.first

        response = _create(context, agent=first_agent, key="second-key")

        assert_that(response.status_code, equal_to(status.HTTP_401_UNAUTHORIZED))


# --- writes ---


def test_an_agent_creates_an_open_task():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        with when("the Agent creates a Task"):
            response = _create(context, description="For October")

            with then("it is open and belongs to the Agent"):
                assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
                assert_that(
                    response.json(),
                    has_entries(
                        agent_id=str(context.agent.id),
                        title="Reconcile invoices",
                        description="For October",
                        status="open",
                        origin="agent",
                    ),
                )


def test_a_task_recorded_automatically_says_so():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        with when("the Agent's runtime records a Task the Agent did not"):
            response = _create(context, origin="automatic")
            shown = context.ingest_client.get(
                f"{_tasks_url(context.agent)}/{response.json()['id']}", headers=_headers(context.ingest_key)
            )

            with then("the Task carries its origin"):
                assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
                assert_that(shown.json(), has_entries(origin="automatic"))


def test_an_agent_creates_a_task_already_in_progress():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        with when("the Agent creates a Task it is starting on"):
            response = _create(context, status="in_progress")

            with then("it is in progress from the one request"):
                assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
                assert_that(response.json(), has_entries(status="in_progress"))


def test_an_unknown_origin_is_rejected():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        with when("a Task is created with an origin that does not exist"):
            response = _create(context, origin="person")

            with then("it is rejected"):
                assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_CONTENT))


def test_the_agent_and_organization_come_from_the_key_not_the_body():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        response = _create(context, agent_id="00000000-0000-0000-0000-000000000000")

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_an_agent_updates_its_tasks_status():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]

        response = context.ingest_client.patch(
            f"{_tasks_url(context.agent)}/{task_id}", json={"status": "done"}, headers=_headers(context.ingest_key)
        )

        assert_that((response.status_code, response.json()["status"]), equal_to((status.HTTP_200_OK, "done")))


def test_an_unknown_status_is_rejected():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]

        response = context.ingest_client.patch(
            f"{_tasks_url(context.agent)}/{task_id}", json={"status": "paused"}, headers=_headers(context.ingest_key)
        )

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_an_agent_adds_notes_to_its_task():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]

        response = context.ingest_client.post(
            f"{_tasks_url(context.agent)}/{task_id}/notes",
            json={"body": "Matched 40 of 42 invoices"},
            headers=_headers(context.ingest_key),
        )

        assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
        assert_that(response.json(), has_entries(body="Matched 40 of 42 invoices"))


def test_an_agent_cannot_touch_another_agents_task():
    with given(
        [
            *_given(),
            _an_agent_with_an_ingest_key(),
            _the_agent_is_remembered_as("first"),
            _an_agent_with_an_ingest_key(name="Second", key="second-key"),
        ]
    ) as context:
        first_agent, first_key = context.first
        task_id = _create(context, agent=first_agent, key=first_key).json()["id"]
        url = f"{_tasks_url(context.agent)}/{task_id}"
        headers = _headers(context.ingest_key)

        with when("the second Agent reaches for the first Agent's Task through its own routes"):
            responses = [
                context.ingest_client.patch(url, json={"status": "failed"}, headers=headers),
                context.ingest_client.post(f"{url}/notes", json={"body": "Mine now"}, headers=headers),
                context.ingest_client.get(url, headers=headers),
            ]

            with then("the Task is not found"):
                assert_that([response.status_code for response in responses], equal_to([status.HTTP_404_NOT_FOUND] * 3))


# --- reads ---


def test_an_agent_lists_its_own_tasks_newest_first():
    with given(
        [
            *_given(),
            _an_agent_with_an_ingest_key(),
            _the_agent_is_remembered_as("first"),
            _an_agent_with_an_ingest_key(name="Second", key="second-key"),
        ]
    ) as context:
        first_agent, first_key = context.first
        _create(context, title="Someone else's", agent=first_agent, key=first_key)
        _create(context, title="Older")
        _create(context, title="Newer")

        response = context.ingest_client.get(_tasks_url(context.agent), headers=_headers(context.ingest_key))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that([task["title"] for task in response.json()["items"]], contains_exactly("Newer", "Older"))


def test_an_agent_lists_its_tasks_most_recently_changed_first():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        reopened_id = _create(context, title="Reopened").json()["id"]
        _create(context, title="Created later")
        context.ingest_client.patch(
            f"{_tasks_url(context.agent)}/{reopened_id}", json={"status": "done"}, headers=_headers(context.ingest_key)
        )

        with when("the Agent lists its Tasks"):
            response = context.ingest_client.get(_tasks_url(context.agent), headers=_headers(context.ingest_key))

            with then("the Task it finished last comes first, so it is shown among its latest work"):
                assert_that(
                    [task["title"] for task in response.json()["items"]], contains_exactly("Reopened", "Created later")
                )


def test_an_agent_filters_its_tasks_by_status():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        done_id = _create(context, title="Finished").json()["id"]
        _create(context, title="Still open")
        context.ingest_client.patch(
            f"{_tasks_url(context.agent)}/{done_id}", json={"status": "done"}, headers=_headers(context.ingest_key)
        )

        response = context.ingest_client.get(
            _tasks_url(context.agent), params={"status": "open"}, headers=_headers(context.ingest_key)
        )

        assert_that([task["title"] for task in response.json()["items"]], contains_exactly("Still open"))


def test_an_agent_reads_its_task_with_its_notes():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]
        url = f"{_tasks_url(context.agent)}/{task_id}"
        context.ingest_client.post(f"{url}/notes", json={"body": "First"}, headers=_headers(context.ingest_key))
        context.ingest_client.post(f"{url}/notes", json={"body": "Second"}, headers=_headers(context.ingest_key))

        response = context.ingest_client.get(url, headers=_headers(context.ingest_key))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that([note["body"] for note in response.json()["notes"]], contains_exactly("First", "Second"))
        assert_that(response.json()["files"], equal_to([]))


# --- files ---


class _InMemoryArtifactStorage(ArtifactStorage):
    """Keeps published bytes in memory, so Agents can publish Artifacts without a bucket."""

    def __init__(self):
        self.objects: dict[UUID, bytes] = {}

    def put(self, artifact: Artifact, content: bytes) -> None:
        self.objects[artifact.id] = content

    def issue_download(self, artifact: Artifact, seconds: int) -> str:
        return f"signed-{artifact.id}"

    def download(self, artifact: Artifact, access: str) -> ArtifactDownload:
        raise AssertionError("not used")

    def delete(self, artifact: Artifact) -> None:
        self.objects.pop(artifact.id, None)


class _InMemoryArtifactStorageModule(Module):
    @provider
    @singleton
    def provide_artifact_storage(self) -> ArtifactStorage:
        return _InMemoryArtifactStorage()


def _given_artifacts(**env: str):
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "ARTIFACT_S3_ENDPOINT_URL": "http://garage.invalid",
                **env,
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), _InMemoryArtifactStorageModule()]),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization(),
    ]


def _published(context, agent=None, filename: str = "report.csv", content: bytes = b"invoice,amount\n1,10\n"):
    """An Artifact the Agent has published."""
    agent = agent or context.agent
    row = Artifact(
        organization_id=agent.organization_id,
        agent_id=agent.id,
        filename=filename,
        content_type="text/csv",
        size=len(content),
        checksum=hashlib.sha256(content).hexdigest(),
        state="READY",
        bucket=bucket_name(agent.id),
        object_key=f"objects/{uuid7()}",
        published_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        source="chat",
    )
    with Session(context.postgres_delegate.engine, expire_on_commit=False) as session:
        session.add(row)
        session.commit()
    return row


def _attach(context, task_id: str, artifact_id, agent=None, key: str | None = None):
    return context.ingest_client.post(
        f"{_tasks_url(agent or context.agent)}/{task_id}/files",
        json={"artifact_id": str(artifact_id)},
        headers=_headers(key or context.ingest_key),
    )


def _pins(context, artifact_id) -> list[ArtifactReference]:
    with Session(context.postgres_delegate.engine) as session:
        return list(
            session.exec(select(ArtifactReference).where(col(ArtifactReference.artifact_id) == artifact_id)).all()
        )


def test_an_agent_attaches_a_published_artifact_to_its_task():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]
        artifact = _published(context)

        with when("the Agent attaches the Artifact"):
            response = _attach(context, task_id, artifact.id)

            with then("it is on the Task with the Artifact's name, type and size"):
                assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
                assert_that(
                    response.json(),
                    has_entries(
                        artifact_id=str(artifact.id), filename="report.csv", content_type="text/csv", size_bytes=20
                    ),
                )
                detail = context.ingest_client.get(
                    f"{_tasks_url(context.agent)}/{task_id}", headers=_headers(context.ingest_key)
                ).json()
                assert_that([stored["filename"] for stored in detail["files"]], contains_exactly("report.csv"))


def test_an_unknown_artifact_is_not_found():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]

        response = _attach(context, task_id, uuid7())

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_a_file_upload_is_not_accepted_any_more():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]

        response = context.ingest_client.post(
            f"{_tasks_url(context.agent)}/{task_id}/files",
            params={"filename": "report.csv"},
            content=b"data",
            headers={**_headers(context.ingest_key), "Content-Type": "text/csv"},
        )

        assert_that(response.status_code, equal_to(status.HTTP_422_UNPROCESSABLE_ENTITY))


def test_a_file_cannot_be_attached_to_another_agents_task():
    with given(
        [
            *_given(),
            _an_agent_with_an_ingest_key(),
            _the_agent_is_remembered_as("first"),
            _an_agent_with_an_ingest_key(name="Second", key="second-key"),
        ]
    ) as context:
        first_agent, first_key = context.first
        task_id = _create(context, agent=first_agent, key=first_key).json()["id"]

        response = _attach(context, task_id, _published(context).id)

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_an_agent_cannot_attach_another_agents_artifact():
    with given(
        [
            *_given(),
            _an_agent_with_an_ingest_key(),
            _the_agent_is_remembered_as("first"),
            _an_agent_with_an_ingest_key(name="Second", key="second-key"),
        ]
    ) as context:
        first_agent, _ = context.first
        task_id = _create(context).json()["id"]

        response = _attach(context, task_id, _published(context, agent=first_agent).id)

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --- removing files ---


def _remove(context, task_id: str, file_id: str):
    return context.ingest_client.delete(
        f"{_tasks_url(context.agent)}/{task_id}/files/{file_id}", headers=_headers(context.ingest_key)
    )


def test_an_agent_removes_a_file_from_its_task():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]
        file_id = _attach(context, task_id, _published(context).id).json()["id"]

        with when("the Agent removes the file"):
            response = _remove(context, task_id, file_id)

            with then("it is gone from the Task"):
                assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
                detail = context.ingest_client.get(
                    f"{_tasks_url(context.agent)}/{task_id}", headers=_headers(context.ingest_key)
                ).json()
                assert_that(detail["files"], equal_to([]))


def test_removing_a_file_lets_its_artifact_expire_again():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]
        artifact = _published(context)
        file_id = _attach(context, task_id, artifact.id).json()["id"]

        with when("the Agent removes the file"):
            _remove(context, task_id, file_id)

            with then("the File's pin is released and the Artifact has its usual retention from now"):
                [pin] = _pins(context, artifact.id)
                assert_that((pin.owner_id, pin.released_at is not None), equal_to((UUID(file_id), True)))
                with Session(context.postgres_delegate.engine) as session:
                    expires_at = session.get_one(Artifact, artifact.id).expires_at
                assert_that(expires_at > datetime.now(UTC) + timedelta(days=29), equal_to(True))


def test_removing_one_file_keeps_another_tasks_pin_on_the_same_artifact():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        artifact = _published(context)
        first_task = _create(context).json()["id"]
        second_task = _create(context).json()["id"]
        removed = _attach(context, first_task, artifact.id).json()["id"]
        kept = _attach(context, second_task, artifact.id).json()["id"]

        _remove(context, first_task, removed)

        assert_that(
            {str(pin.owner_id): pin.released_at is None for pin in _pins(context, artifact.id)},
            equal_to({removed: False, kept: True}),
        )


def test_an_unknown_file_is_not_found():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]

        response = _remove(context, task_id, "00000000-0000-7000-8000-000000000000")

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_an_agent_cannot_remove_another_agents_file():
    with given(
        [
            *_given(),
            _an_agent_with_an_ingest_key(),
            _the_agent_is_remembered_as("first"),
            _an_agent_with_an_ingest_key(name="Second", key="second-key"),
        ]
    ) as context:
        first_agent, first_key = context.first
        task_id = _create(context, agent=first_agent, key=first_key).json()["id"]
        file_id = _attach(
            context, task_id, _published(context, agent=first_agent).id, agent=first_agent, key=first_key
        ).json()["id"]

        response = _remove(context, task_id, file_id)

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --- the in-pod command against the real apps ---

_TASK_COMMAND = Path(__file__).parents[2] / "domains/agents/scripts/agentbarn_task.py"


def _serve(app) -> tuple[str, Callable[[], object]]:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "the app did not start"
        time.sleep(0.05)
    return f"http://127.0.0.1:{port}", lambda: (setattr(server, "should_exit", True), thread.join(10))


def _the_agent_runs_with_ready_file_storage():
    """Running, so its Artifact credential is accepted, with a ready bucket to publish into."""

    def step(context):
        repository: AgentRepository = context.injector.get(AgentRepository)
        agent = repository.get_by_id(context.agent.id)
        assert agent is not None
        agent.status = AgentStatus.RUNNING
        repository.save(agent)
        context.agent = agent
        with Session(context.postgres_delegate.engine) as session:
            session.add(
                ArtifactBucket(
                    organization_id=agent.organization_id,
                    agent_id=agent.id,
                    name=bucket_name(agent.id),
                    access_key=f"key-{agent.id.hex}",
                    secret_key_encrypted="unused",
                    state="READY",
                    retry_at=datetime.now(UTC),
                )
            )
            session.commit()

    return step


def _the_apps_are_served_over_sockets():
    def step(context):
        ingest_origin, stop_ingest = _serve(create_ingest_app(injector=context.injector))
        api_origin, stop_api = _serve(create_app(injector=context.injector))
        context.ingest_url = f"{ingest_origin}/ingest/v1"
        context.artifact_url = f"{api_origin}/api/v1/agent-artifacts/runtime"
        context.stop_servers = lambda: (stop_ingest(), stop_api())

    return step


def _task_command(context, workspace: Path, *args: str, **env: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_TASK_COMMAND), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
        cwd=workspace,
        env={
            **os.environ,
            "AGENT_ID": str(context.agent.id),
            "INGEST_URL": context.ingest_url,
            "INGEST_API_KEY": context.ingest_key,
            "ARTIFACT_URL": context.artifact_url,
            "ARTIFACT_API_KEY": runtime_token(context.agent.id, context.ingest_key),
            "ARTIFACT_MAX_BYTES": "1048576",
            "ARTIFACT_UPLOAD_ROOTS": str(workspace),
            **env,
        },
    )


_COMMAND_GIVEN = [
    *_given_artifacts(),
    _an_agent_with_an_ingest_key(),
    _the_agent_runs_with_ready_file_storage(),
    _the_apps_are_served_over_sockets(),
]


def test_the_command_records_a_task_end_to_end(tmp_path: Path):
    with given(_COMMAND_GIVEN) as context:
        try:
            report = tmp_path / "report.csv"
            report.write_bytes(b"invoice,amount\n1,10\n")

            with when("the Agent opens a Task, works it and attaches its output"):
                created = _task_command(context, tmp_path, "create", "--title", "Reconcile invoices")
                task_id = json.loads(created.stdout)["id"]
                _task_command(context, tmp_path, "status", task_id, "in_progress")
                attached = _task_command(context, tmp_path, "attach", task_id, str(report))
                _task_command(context, tmp_path, "status", task_id, "done")
                shown = json.loads(_task_command(context, tmp_path, "show", task_id).stdout)

                with then("the Task carries the status and the file, published as an Artifact"):
                    assert_that(attached.returncode, equal_to(0), attached.stderr)
                    assert_that(shown["status"], equal_to("done"))
                    [stored] = shown["files"]
                    assert_that((stored["filename"], stored["size_bytes"]), equal_to(("report.csv", 20)))
                    storage = context.injector.get(ArtifactStorage)
                    assert_that(storage.objects[UUID(stored["artifact_id"])], equal_to(b"invoice,amount\n1,10\n"))
        finally:
            context.stop_servers()


def test_the_command_notes_in_the_same_call_and_replaces_a_file_of_the_same_name(tmp_path: Path):
    with given(_COMMAND_GIVEN) as context:
        try:
            plan = tmp_path / "offsite.md"

            with when("the Agent opens a Task with a note and attaches a file twice, replacing it"):
                created = _task_command(
                    context,
                    tmp_path,
                    "create",
                    "--title",
                    "Plan the offsite",
                    "--status",
                    "in_progress",
                    "--note",
                    "Venues first",
                )
                task_id = json.loads(created.stdout)["id"]
                plan.write_text("# Venues")
                _task_command(context, tmp_path, "attach", task_id, str(plan), "--replace")
                plan.write_text("# Venues\n\n## Agenda")
                replaced = _task_command(context, tmp_path, "attach", task_id, str(plan), "--replace")
                _task_command(context, tmp_path, "status", task_id, "done", "--note", "Agenda added")
                shown = json.loads(_task_command(context, tmp_path, "show", task_id).stdout)

                with then("the Task holds both notes and only the latest copy of the file"):
                    assert_that(replaced.returncode, equal_to(0), replaced.stderr)
                    assert_that(shown["status"], equal_to("done"))
                    assert_that(
                        sorted(note["body"] for note in shown["notes"]), equal_to(["Agenda added", "Venues first"])
                    )
                    assert_that(
                        [(f["filename"], f["size_bytes"]) for f in shown["files"]],
                        contains_exactly(("offsite.md", len("# Venues\n\n## Agenda"))),
                    )
        finally:
            context.stop_servers()


def test_the_command_shows_the_file_under_the_name_it_is_given(tmp_path: Path):
    with given(_COMMAND_GIVEN) as context:
        try:
            export = tmp_path / "tmp-7f3a.csv"
            export.write_bytes(b"a,b\n")
            task_id = json.loads(_task_command(context, tmp_path, "create", "--title", "Export").stdout)["id"]

            attached = _task_command(context, tmp_path, "attach", task_id, str(export), "--name", "export.csv")

            assert_that(attached.returncode, equal_to(0), attached.stderr)
            assert_that(json.loads(attached.stdout)["filename"], equal_to("export.csv"))
        finally:
            context.stop_servers()


def test_the_command_refuses_a_file_outside_the_workspace(tmp_path: Path):
    with given(_COMMAND_GIVEN) as context:
        try:
            workspace = tmp_path / "workspace"
            workspace.mkdir()
            outside = tmp_path / "secrets.env"
            outside.write_text("TOKEN=x")
            task_id = json.loads(_task_command(context, workspace, "create", "--title", "Leak").stdout)["id"]

            result = _task_command(context, workspace, "attach", task_id, str(outside))

            assert_that(result.returncode, equal_to(1))
            assert_that(result.stderr, contains_string("inside your workspace"))
            assert_that(context.injector.get(ArtifactStorage).objects, equal_to({}))
        finally:
            context.stop_servers()


def test_the_command_refuses_a_file_over_the_limit_before_uploading(tmp_path: Path):
    with given(_COMMAND_GIVEN) as context:
        try:
            large = tmp_path / "export.csv"
            large.write_bytes(b"x" * 11)
            task_id = json.loads(_task_command(context, tmp_path, "create", "--title", "Export").stdout)["id"]

            result = _task_command(context, tmp_path, "attach", task_id, str(large), ARTIFACT_MAX_BYTES="10")

            assert_that(result.returncode, equal_to(1))
            assert_that(result.stderr, contains_string("larger than the 10-byte limit"))
            assert_that(context.injector.get(ArtifactStorage).objects, equal_to({}))
        finally:
            context.stop_servers()


def test_the_command_says_files_are_unavailable_without_file_storage(tmp_path: Path):
    with given(_COMMAND_GIVEN) as context:
        try:
            report = tmp_path / "report.csv"
            report.write_bytes(b"a,b\n")
            task_id = json.loads(_task_command(context, tmp_path, "create", "--title", "Report").stdout)["id"]

            result = _task_command(context, tmp_path, "attach", task_id, str(report), ARTIFACT_API_KEY="")

            assert_that(result.returncode, equal_to(1))
            assert_that(result.stderr, contains_string("Files cannot be attached"))
        finally:
            context.stop_servers()

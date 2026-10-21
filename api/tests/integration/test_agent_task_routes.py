"""AF-412: Agents record their own Tasks through the ingest app, authenticated by their ingest key."""

import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import status
from hamcrest import assert_that, contains_exactly, contains_string, equal_to, has_entries
from starlette.testclient import TestClient

from api.domains.agents.repository import AgentRepository
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
                    ),
                )


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


def _attach(context, task_id: str, data: bytes, filename: str = "report.csv", content_type: str = "text/csv"):
    return context.ingest_client.post(
        f"{_tasks_url(context.agent)}/{task_id}/files",
        params={"filename": filename},
        content=data,
        headers={**_headers(context.ingest_key), "Content-Type": content_type},
    )


def test_an_agent_attaches_a_file_to_its_task():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]

        with when("the Agent uploads a file"):
            response = _attach(context, task_id, b"invoice,amount\n1,10\n")

            with then("it is stored on the Task with its name, type and size"):
                assert_that(response.status_code, equal_to(status.HTTP_201_CREATED))
                assert_that(response.json(), has_entries(filename="report.csv", content_type="text/csv", size_bytes=20))
                detail = context.ingest_client.get(
                    f"{_tasks_url(context.agent)}/{task_id}", headers=_headers(context.ingest_key)
                ).json()
                assert_that([stored["filename"] for stored in detail["files"]], contains_exactly("report.csv"))


def test_a_file_over_the_per_file_limit_is_rejected_with_a_clear_error():
    with given([*_given(TASK_FILE_MAX_BYTES="10"), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]

        response = _attach(context, task_id, b"x" * 11)

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(response.json(), has_entries(detail="The file is larger than the 10-byte limit."))


def test_a_file_past_the_organization_limit_is_rejected_with_a_clear_error():
    with given([*_given(TASK_ORGANIZATION_STORAGE_MAX_BYTES="10"), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]
        _attach(context, task_id, b"x" * 6)

        response = _attach(context, task_id, b"x" * 5, filename="second.csv")

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))
        assert_that(
            response.json(),
            has_entries(detail="The file is larger than the space left for this Organization's Task Files."),
        )


def test_an_empty_file_is_rejected():
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]

        response = _attach(context, task_id, b"")

        assert_that(response.status_code, equal_to(status.HTTP_400_BAD_REQUEST))


@pytest.mark.parametrize(
    ("filename", "content_type"),
    [("../report.csv", "text/csv"), ("report.csv", "text/csv; charset=utf-8"), ("", "text/csv")],
)
def test_an_unsafe_filename_or_content_type_is_rejected(filename: str, content_type: str):
    with given([*_given(), _an_agent_with_an_ingest_key()]) as context:
        task_id = _create(context).json()["id"]

        response = _attach(context, task_id, b"data", filename=filename, content_type=content_type)

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

        response = _attach(context, task_id, b"data")

        assert_that(response.status_code, equal_to(status.HTTP_404_NOT_FOUND))


# --- the in-pod command against the real app ---

_TASK_COMMAND = Path(__file__).parents[2] / "domains/agents/scripts/agentbarn_task.py"


def _the_ingest_app_is_served_over_a_socket():
    def step(context):
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        server = uvicorn.Server(
            uvicorn.Config(create_ingest_app(injector=context.injector), host="127.0.0.1", port=port, log_level="error")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline, "the ingest app did not start"
            time.sleep(0.05)
        context.ingest_url = f"http://127.0.0.1:{port}/ingest/v1"
        context.stop_server = lambda: (setattr(server, "should_exit", True), thread.join(10))

    return step


def _task_command(context, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_TASK_COMMAND), *args],
        text=True,
        capture_output=True,
        check=False,
        timeout=60,
        env={
            **os.environ,
            "AGENT_ID": str(context.agent.id),
            "INGEST_URL": context.ingest_url,
            "INGEST_API_KEY": context.ingest_key,
        },
    )


def test_an_upload_refused_part_way_reaches_the_agent_as_a_clear_error(tmp_path: Path):
    with given(
        [
            *_given(TASK_ORGANIZATION_STORAGE_MAX_BYTES=str(1024 * 1024)),
            _an_agent_with_an_ingest_key(),
            _the_ingest_app_is_served_over_a_socket(),
        ]
    ) as context:
        try:
            task_id = _create(context).json()["id"]
            large = tmp_path / "export.csv"
            large.write_bytes(b"x" * (8 * 1024 * 1024))

            with when("the Agent attaches a file that passes the Organization's limit part way through"):
                result = _task_command(context, "attach", task_id, str(large))

                with then("the command reports the limit, not a broken connection"):
                    assert_that(result.returncode, equal_to(1))
                    assert_that(result.stderr, contains_string("space left for this Organization's Task Files"))
        finally:
            context.stop_server()


def test_the_command_records_a_task_end_to_end(tmp_path: Path):
    with given([*_given(), _an_agent_with_an_ingest_key(), _the_ingest_app_is_served_over_a_socket()]) as context:
        try:
            report = tmp_path / "report.csv"
            report.write_bytes(b"invoice,amount\n1,10\n")

            with when("the Agent opens a Task, works it and attaches its output"):
                created = _task_command(context, "create", "--title", "Reconcile invoices")
                task_id = json.loads(created.stdout)["id"]
                _task_command(context, "status", task_id, "in_progress")
                attached = _task_command(context, "attach", task_id, str(report))
                _task_command(context, "status", task_id, "done")
                shown = json.loads(_task_command(context, "show", task_id).stdout)

                with then("the Task carries the status and the file"):
                    assert_that(attached.returncode, equal_to(0), attached.stderr)
                    assert_that(shown["status"], equal_to("done"))
                    assert_that([f["filename"] for f in shown["files"]], contains_exactly("report.csv"))
        finally:
            context.stop_server()

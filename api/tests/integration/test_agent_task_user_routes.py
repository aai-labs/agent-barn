"""AF-413: people read an Agent's Tasks, Notes and Files through the API, only for
Agents they may read Tasks on."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid7

from fastapi import status
from hamcrest import assert_that, contains_exactly, contains_string, equal_to, has_entries
from injector import Module, provider, singleton
from sqlmodel import Session

from api.domains.agent_tasks.models import AgentTaskCreate, AgentTaskFileCreate, AgentTaskNoteCreate, AgentTaskStatus
from api.domains.agent_tasks.service import AgentTaskService
from api.domains.agents.repository import AgentRepository
from api.domains.artifacts.models import Artifact
from api.domains.artifacts.storage import ArtifactDownload, ArtifactStorage
from api.domains.rbac.catalog import AGENT_VIEWER_ROLE_ID, PERMISSION_ID_BY_KEY, PermissionKey
from api.domains.rbac.models import AgentAccessRole, AgentAccessRolePermission
from api.domains.users.organization_users.models import OrganizationRole
from api.tests.core.givenpy import given, then, when
from api.tests.core.modules import create_test_client, prepare_api_server, prepare_injector, set_env_variable
from api.tests.steps.agent import (
    TEST_ENCRYPTION_KEY,
    MockK8sModule,
    MockLiteLLMModule,
    there_is_agent_access,
    there_is_an_agent,
    use_org_for_auth,
)
from api.tests.steps.agent_memory import signed_in_as
from api.tests.steps.database import database_is_clean, database_repo_is_ready
from api.tests.steps.organization import there_is_an_organization_with_user_and_access_token


class _FakeArtifactStorage(ArtifactStorage):
    """Signs a download without a bucket behind it; the Artifacts download route serves the bytes."""

    def put(self, artifact: Artifact, content: bytes) -> None:
        raise AssertionError("Task reads never upload bytes")

    def issue_download(self, artifact: Artifact, seconds: int) -> str:
        return f"signed-{artifact.id}"

    def download(self, artifact: Artifact, access: str) -> ArtifactDownload:
        raise AssertionError("Task reads never stream bytes")

    def delete(self, artifact: Artifact) -> None:
        raise AssertionError("Task reads never delete bytes")


class _FakeArtifactStorageModule(Module):
    @provider
    @singleton
    def provide_artifact_storage(self) -> ArtifactStorage:
        return _FakeArtifactStorage()


def _api_setup(*steps: Any) -> list[Any]:
    return [
        set_env_variable(
            {
                "AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY,
                "LITELLM_BASE_URL": "http://litellm:4000",
                "LITELLM_SECRET_NAME": "litellm",
                "AGENT_DEFAULT_MODEL": "litellm/gpt-5-mini",
                "ARTIFACT_S3_ENDPOINT_URL": "http://garage.invalid",
            }
        ),
        prepare_injector(modules=[MockK8sModule(), MockLiteLLMModule(), _FakeArtifactStorageModule()]),
        prepare_api_server(),
        create_test_client(),
        database_repo_is_ready(),
        database_is_clean(),
        there_is_an_organization_with_user_and_access_token(),
        use_org_for_auth(),
        *steps,
    ]


def _published_artifact(context, filename: str) -> Artifact:
    """An Artifact the Agent has published, recorded the way the Artifacts domain records one."""
    content = f"bytes of {filename}".encode()
    row = Artifact(
        organization_id=context.organization.id,
        agent_id=context.agent.id,
        filename=filename,
        content_type="text/csv",
        size=len(content),
        checksum=hashlib.sha256(content).hexdigest(),
        state="READY",
        bucket=f"bucket-{context.agent.id}",
        object_key=f"objects/{uuid7()}",
        published_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(days=30),
        source="chat",
    )
    with Session(context.postgres_delegate.engine, expire_on_commit=False) as session:
        session.add(row)
        session.commit()
    return row


_AGENT_TASKS = "/api/v1/organizations/{organization_id}/agents/{agent_id}/tasks"
_ORG_TASKS = "/api/v1/organizations/{organization_id}/tasks"


def _auth(context) -> dict[str, str]:
    return {"Authorization": f"Bearer {context.access_token}"}


def _agent_tasks(context, agent_id: UUID | None = None) -> str:
    return _AGENT_TASKS.replace("{agent_id}", str(agent_id or context.agent.id))


def _service(context) -> AgentTaskService:
    return context.injector.get(AgentTaskService)


def _remember_agent_as(name: str):
    def step(context):
        setattr(context, name, context.agent)

    return step


def _a_task(title: str = "Reconcile invoices", task_status: AgentTaskStatus = AgentTaskStatus.OPEN):
    """A Task on the current Agent, with a Note and a File, remembered as `context.task`."""

    def step(context):
        service = _service(context)
        task = service.create_task(
            context.organization.id, context.agent.id, AgentTaskCreate(title=title, status=task_status)
        )
        service.add_note(
            context.organization.id, context.agent.id, task.id, AgentTaskNoteCreate(body="March is matched")
        )
        context.artifact = _published_artifact(context, "march-reconciliation.csv")
        context.file = service.attach_file(
            context.organization.id, context.agent.id, task.id, AgentTaskFileCreate(artifact_id=context.artifact.id)
        )
        context.task = task

    return step


def _a_role_without_task_read():
    def step(context):
        repository: AgentRepository = context.injector.get(AgentRepository)
        role = AgentAccessRole(organization_id=context.organization.id, name=f"CUSTOM-{uuid7()}", is_system=False)
        repository.delegate.save(role)
        repository.delegate.save(
            AgentAccessRolePermission(role_id=role.id, permission_id=PERMISSION_ID_BY_KEY[PermissionKey.AGENT_READ])
        )
        context.role_without_task_read = role

    return step


def _download(context, task_id: UUID | None = None, file_id: UUID | None = None):
    task = task_id or context.task.id
    file = file_id or context.file.id
    return context.client.get(f"{_agent_tasks(context)}/{task}/files/{file}/download-link", headers=_auth(context))


def test_an_owner_lists_an_agents_tasks_and_filters_them_by_status():
    with given(
        _api_setup(
            there_is_an_agent(),
            _a_task("Reconcile invoices"),
            _a_task("Send reminders", AgentTaskStatus.DONE),
        )
    ) as context:
        with when("the Owner lists the Agent's Tasks"):
            listing = context.client.get(_agent_tasks(context), headers=_auth(context))
            done = context.client.get(_agent_tasks(context), params={"status": "done"}, headers=_auth(context))

        with then("all of them are listed, and the filter keeps only the finished one"):
            assert_that(listing.status_code, equal_to(status.HTTP_200_OK))
            assert_that(listing.json()["total"], equal_to(2))
            assert_that(
                [task["title"] for task in done.json()["items"]],
                contains_exactly("Send reminders"),
            )


def test_an_owner_opens_a_task_with_its_notes_and_files():
    with given(_api_setup(there_is_an_agent(), _a_task())) as context:
        with when("the Owner opens the Task"):
            response = context.client.get(f"{_agent_tasks(context)}/{context.task.id}", headers=_auth(context))

        with then("its Notes and Files come with it"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body, has_entries(id=str(context.task.id), title="Reconcile invoices", status="open"))
            assert_that([note["body"] for note in body["notes"]], contains_exactly("March is matched"))
            assert_that(
                body["files"],
                contains_exactly(
                    has_entries(
                        id=str(context.file.id),
                        filename="march-reconciliation.csv",
                        size_bytes=context.artifact.size,
                    )
                ),
            )


def test_a_file_gets_a_short_lived_download_link():
    with given(_api_setup(there_is_an_agent(), _a_task())) as context:
        with when("the Owner asks to download the File"):
            response = _download(context)

        with then("they get a signed link to the File's Artifact, served by the Artifacts download route"):
            assert_that(response.status_code, equal_to(status.HTTP_200_OK))
            body = response.json()
            assert_that(body["artifact"], has_entries(id=str(context.artifact.id), filename="march-reconciliation.csv"))
            assert_that(
                body["url"],
                contains_string(
                    f"/api/v1/agent-artifacts/{context.organization.id}/{context.agent.id}/{context.artifact.id}?"
                ),
            )
            assert_that(body["url"], contains_string(f"signed-{context.artifact.id}"))


def test_a_file_is_only_found_under_its_own_task():
    with given(
        _api_setup(
            there_is_an_agent(),
            _a_task("First"),
            lambda context: setattr(context, "first", context.task),
            _a_task("Second"),
        )
    ) as context:
        with when("the File is asked for under another Task, or an unknown one"):
            other_task = _download(context, task_id=context.first.id)
            unknown_task = _download(context, task_id=uuid7())
            unknown_file = _download(context, file_id=uuid7())

        with then("it is not found"):
            assert_that(other_task.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(unknown_task.status_code, equal_to(status.HTTP_404_NOT_FOUND))
            assert_that(unknown_file.status_code, equal_to(status.HTTP_404_NOT_FOUND))


def test_an_agent_the_member_cannot_see_is_not_found_on_every_route():
    with given(_api_setup(there_is_an_agent(), _a_task(), signed_in_as(OrganizationRole.MEMBER))) as context:
        with when("a Member without access to the Agent reads its Tasks"):
            responses = [
                context.client.get(_agent_tasks(context), headers=_auth(context)),
                context.client.get(f"{_agent_tasks(context)}/{context.task.id}", headers=_auth(context)),
                _download(context),
            ]

        with then("the Agent is not found, so nothing about it leaks"):
            assert_that(
                [response.status_code for response in responses],
                equal_to([status.HTTP_404_NOT_FOUND] * 3),
            )


def test_a_member_without_task_read_is_forbidden():
    with given(
        _api_setup(
            there_is_an_agent(),
            _a_task(),
            _a_role_without_task_read(),
            signed_in_as(OrganizationRole.MEMBER),
            lambda context: there_is_agent_access(access_role_id=context.role_without_task_read.id)(context),
        )
    ) as context:
        with when("a Member who may see the Agent but not its Tasks reads them"):
            responses = [
                context.client.get(_agent_tasks(context), headers=_auth(context)),
                context.client.get(f"{_agent_tasks(context)}/{context.task.id}", headers=_auth(context)),
                _download(context),
            ]

        with then("they are refused"):
            assert_that(
                [response.status_code for response in responses],
                equal_to([status.HTTP_403_FORBIDDEN] * 3),
            )


def test_a_viewer_reads_and_downloads():
    with given(
        _api_setup(
            there_is_an_agent(),
            _a_task(),
            signed_in_as(OrganizationRole.MEMBER),
            there_is_agent_access(access_role_id=AGENT_VIEWER_ROLE_ID),
        )
    ) as context:
        with when("a Member with Viewer access reads the Tasks and downloads the File"):
            listing = context.client.get(_agent_tasks(context), headers=_auth(context))
            download = _download(context)

        with then("both succeed"):
            assert_that(listing.status_code, equal_to(status.HTTP_200_OK))
            assert_that(download.status_code, equal_to(status.HTTP_200_OK))


def test_the_organization_list_covers_only_visible_agents_and_filters_by_agent_and_status():
    with given(
        _api_setup(
            there_is_an_agent(name="Billing"),
            _remember_agent_as("billing"),
            _a_task("Reconcile invoices"),
            _a_task("Send reminders", AgentTaskStatus.DONE),
            there_is_an_agent(name="Hidden"),
            _a_task("Secret work"),
            signed_in_as(OrganizationRole.MEMBER),
            lambda context: there_is_agent_access(agent_id=context.billing.id, access_role_id=AGENT_VIEWER_ROLE_ID)(
                context
            ),
        )
    ) as context:
        with when("the Member lists the Organization's Tasks"):
            everything = context.client.get(_ORG_TASKS, headers=_auth(context))
            by_agent = context.client.get(
                _ORG_TASKS, params={"agent_id": str(context.agent.id)}, headers=_auth(context)
            )
            done = context.client.get(_ORG_TASKS, params={"status": "done"}, headers=_auth(context))

        with then("only the visible Agent's Tasks are listed, and the filters narrow them"):
            assert_that(everything.status_code, equal_to(status.HTTP_200_OK))
            assert_that(
                sorted(task["title"] for task in everything.json()["items"]),
                equal_to(["Reconcile invoices", "Send reminders"]),
            )
            assert_that(by_agent.json()["items"], equal_to([]))
            assert_that([task["title"] for task in done.json()["items"]], contains_exactly("Send reminders"))


def _a_later_note(body: str):
    def step(context):
        _service(context).add_note(
            context.organization.id, context.agent.id, context.task.id, AgentTaskNoteCreate(body=body)
        )

    return step


def _a_bare_task(title: str):
    def step(context):
        _service(context).create_task(context.organization.id, context.agent.id, AgentTaskCreate(title=title))

    return step


def test_listed_tasks_say_how_many_files_and_notes_they_have_and_their_latest_note():
    with given(
        _api_setup(
            there_is_an_agent(),
            _a_task("Reconcile invoices"),
            _a_later_note("Two invoices are still unpaid"),
            _a_bare_task("Send reminders"),
        )
    ) as context:
        with when("the Owner lists the Agent's Tasks and the Organization's Tasks"):
            listings = [
                context.client.get(_agent_tasks(context), headers=_auth(context)),
                context.client.get(_ORG_TASKS, headers=_auth(context)),
            ]

        with then("each Task carries its File and Note counts and its latest Note"):
            for listing in listings:
                by_title = {task["title"]: task for task in listing.json()["items"]}
                assert_that(
                    by_title["Reconcile invoices"],
                    has_entries(file_count=1, note_count=2, latest_note="Two invoices are still unpaid"),
                )
                assert_that(by_title["Send reminders"], has_entries(file_count=0, note_count=0, latest_note=None))

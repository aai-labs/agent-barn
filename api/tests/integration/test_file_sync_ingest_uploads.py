from datetime import UTC, datetime, timedelta

from fastapi import status
from hamcrest import assert_that, close_to, equal_to, has_length, none, not_none
from sqlmodel import Session, col, select

from api.domains.agents.models import Agent, AgentType
from api.domains.file_sync.engine import FileSyncEngine
from api.domains.file_sync.models import SyncActivity, SyncActivityKind, SyncAgentFolder, SyncFile
from api.infrastructure.crypto import encrypt_token
from api.tests.core.givenpy import given
from api.tests.core.modules import prepare_ingest_server, prepare_injector, set_env_variable
from api.tests.steps.agent import TEST_ENCRYPTION_KEY, there_is_an_agent
from api.tests.steps.database import database_repo_is_ready
from api.tests.steps.file_sync_provider import TestDriveModule, fake_drive, there_is_a_sync_connection
from api.tests.steps.organization import there_is_an_organization

_KEY = "agent-ingest-key"
_SHA_A = "a" * 64
_SHA_B = "b" * 64

_BASE = [
    set_env_variable({"AGENT_TOKEN_ENCRYPTION_KEY": TEST_ENCRYPTION_KEY}),
    prepare_injector(modules=[TestDriveModule()]),
    database_repo_is_ready(),
    prepare_ingest_server(),
    there_is_an_organization(),
]


def _ready(context, agent_type: AgentType = AgentType.OPENCLAW) -> Agent:
    there_is_an_agent(name="Sales Bot", agent_type=agent_type)(context)
    with Session(context.postgres_delegate.engine) as session:
        row = session.get(Agent, context.agent.id)
        assert row is not None
        row.ingest_key_encrypted = encrypt_token(_KEY, TEST_ENCRYPTION_KEY)
        session.add(row)
        session.commit()
    there_is_a_sync_connection()(context)
    context.injector.get(FileSyncEngine).reconcile_folders(context.connection)
    return context.agent


def _entry(path: str, sha: str = _SHA_A, size: int = 5) -> dict:
    return {"path": path, "size": size, "sha256": sha}


def _report(context, agent: Agent, *entries: dict, complete: bool = True):
    return context.ingest_client.post(
        f"/ingest/v1/agents/{agent.id}/file-sync/changes",
        json={"complete": complete, "entries": list(entries)},
        headers={"Authorization": f"Bearer {_KEY}"},
    )


def _complete(context, agent: Agent, path: str, key: str = _KEY):
    return context.ingest_client.post(
        f"/ingest/v1/agents/{agent.id}/file-sync/uploads/complete",
        json={"path": path},
        headers={"Authorization": f"Bearer {key}"},
    )


def _folder(context) -> SyncAgentFolder:
    with Session(context.postgres_delegate.engine) as session:
        folder = session.exec(select(SyncAgentFolder).where(col(SyncAgentFolder.agent_id) == context.agent.id)).first()
        assert folder is not None
        return folder


def _files(context) -> dict[str, SyncFile]:
    with Session(context.postgres_delegate.engine) as session:
        rows = session.exec(select(SyncFile).where(col(SyncFile.folder_id) == _folder(context).id))
        return {row.path: row for row in rows}


def _activity(context) -> list[tuple[SyncActivityKind, str | None]]:
    with Session(context.postgres_delegate.engine) as session:
        rows = session.exec(select(SyncActivity).where(col(SyncActivity.agent_id) == context.agent.id))
        return [(row.kind, row.path) for row in rows]


def _upload_through_the_pod(context, agent: Agent, path: str, content: bytes) -> None:
    response = _report(context, agent, _entry(path, size=len(content)))
    upload = next(upload for upload in response.json()["uploads"] if upload["path"] == path)
    fake_drive(context).complete_upload(upload["url"], content)
    assert _complete(context, agent, path).status_code == status.HTTP_204_NO_CONTENT


def test_a_new_file_gets_an_upload_url_and_is_recorded_as_under_way():
    with given(_BASE) as context:
        agent = _ready(context)

        response = _report(context, agent, _entry("workspace/notes.md"))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        uploads = response.json()["uploads"]
        assert_that([upload["path"] for upload in uploads], equal_to(["workspace/notes.md"]))
        assert_that(uploads[0]["url"].startswith("https://testdrive.example.test/upload/"), equal_to(True))
        assert_that(uploads[0]["expires_at"], not_none())
        row = _files(context)["workspace/notes.md"]
        assert_that((row.local_sha256, row.size, row.item_id), equal_to((_SHA_A, 5, None)))
        assert_that(row.upload_started_at, not_none())


def test_a_completed_upload_is_recorded_from_the_provider_and_not_asked_for_again():
    with given(_BASE) as context:
        agent = _ready(context)

        _upload_through_the_pod(context, agent, "workspace/notes.md", b"hello")
        again = _report(context, agent, _entry("workspace/notes.md"))

        row = _files(context)["workspace/notes.md"]
        folder_item_id = _folder(context).folder_item_id
        assert folder_item_id is not None
        provider = fake_drive(context).get_item_by_path(
            context.sync_root, parent_id=folder_item_id, rel_path="workspace/notes.md"
        )
        assert_that(
            (row.item_id, row.etag, row.ctag, row.remote_hash),
            equal_to((provider.id, provider.version, provider.content_version, provider.content_hash)),
        )
        assert_that((row.upload_started_at, row.synced_at is not None), equal_to((None, True)))
        assert_that(again.json()["uploads"], equal_to([]))


def test_a_changed_file_gets_a_new_upload():
    with given(_BASE) as context:
        agent = _ready(context)
        _upload_through_the_pod(context, agent, "workspace/notes.md", b"hello")

        response = _report(context, agent, _entry("workspace/notes.md", sha=_SHA_B, size=9))

        assert_that([upload["path"] for upload in response.json()["uploads"]], equal_to(["workspace/notes.md"]))
        assert_that(_files(context)["workspace/notes.md"].local_sha256, equal_to(_SHA_B))


def test_an_upload_under_way_is_not_handed_out_again_until_its_link_could_have_expired():
    with given(_BASE) as context:
        agent = _ready(context)
        _report(context, agent, _entry("workspace/notes.md"))

        while_fresh = _report(context, agent, _entry("workspace/notes.md"))
        with Session(context.postgres_delegate.engine) as session:
            row = session.get(SyncFile, _files(context)["workspace/notes.md"].id)
            assert row is not None
            row.upload_started_at = datetime.now(UTC) - timedelta(minutes=15)
            session.add(row)
            session.commit()
        after_expiry = _report(context, agent, _entry("workspace/notes.md"))

        assert_that(while_fresh.json()["uploads"], equal_to([]))
        assert_that(after_expiry.json()["uploads"], has_length(1))


def test_an_empty_file_is_written_by_the_server_without_an_upload():
    with given(_BASE) as context:
        agent = _ready(context)

        response = _report(
            context,
            agent,
            _entry(
                "workspace/empty.txt", sha="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", size=0
            ),
        )

        assert_that(response.json()["uploads"], equal_to([]))
        row = _files(context)["workspace/empty.txt"]
        assert_that((row.item_id is not None, row.size, row.upload_started_at), equal_to((True, 0, None)))
        provider = fake_drive(context).get_item(context.sync_root, item_id=row.item_id or "")
        assert_that((provider.path, provider.size), equal_to(("Sales Bot/workspace/empty.txt", 0)))


def test_a_file_over_the_size_limit_is_skipped_and_recorded_once():
    with given(_BASE) as context:
        agent = _ready(context)
        huge = _entry("workspace/video.mp4", size=100 * 1024 * 1024 + 1)

        first = _report(context, agent, huge)
        second = _report(context, agent, huge)

        assert_that((first.json()["uploads"], second.json()["uploads"]), equal_to(([], [])))
        assert_that(_activity(context), equal_to([(SyncActivityKind.SKIPPED_TOO_LARGE, "workspace/video.mp4")]))
        assert_that(_files(context), equal_to({}))


def test_a_name_the_provider_refuses_is_skipped_and_recorded_once():
    with given(_BASE) as context:
        agent = _ready(context)

        _report(context, agent, _entry("workspace/a:b.md"), _entry("workspace/trailing."), _entry("workspace/ok.md"))
        response = _report(context, agent, _entry("workspace/a:b.md"), _entry("workspace/trailing."))

        assert_that(response.json()["uploads"], equal_to([]))
        activity = _activity(context)
        assert_that(len(activity), equal_to(2))
        assert_that(
            set(activity),
            equal_to(
                {
                    (SyncActivityKind.SKIPPED_NAME, "workspace/a:b.md"),
                    (SyncActivityKind.SKIPPED_NAME, "workspace/trailing."),
                }
            ),
        )


def test_a_path_too_long_for_the_provider_is_skipped():
    with given(_BASE) as context:
        agent = _ready(context)
        long_path = "workspace/" + "/".join(["d" * 90] * 5) + "/notes.md"

        response = _report(context, agent, _entry(long_path))

        assert_that(response.json()["uploads"], equal_to([]))
        assert_that(_activity(context), equal_to([(SyncActivityKind.SKIPPED_NAME, long_path)]))


def test_two_paths_differing_only_in_case_upload_one_and_skip_the_other():
    with given(_BASE) as context:
        agent = _ready(context)

        response = _report(context, agent, _entry("workspace/Notes.md"), _entry("workspace/notes.md", sha=_SHA_B))

        assert_that([upload["path"] for upload in response.json()["uploads"]], equal_to(["workspace/Notes.md"]))
        assert_that(_activity(context), equal_to([(SyncActivityKind.SKIPPED_NAME, "workspace/notes.md")]))


def test_completing_with_no_upload_under_way_is_a_conflict():
    with given(_BASE) as context:
        agent = _ready(context)

        response = _complete(context, agent, "workspace/notes.md")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_completing_before_the_file_reached_the_provider_is_a_conflict():
    with given(_BASE) as context:
        agent = _ready(context)
        _report(context, agent, _entry("workspace/notes.md"))

        response = _complete(context, agent, "workspace/notes.md")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(_files(context)["workspace/notes.md"].item_id, none())


def test_completing_when_the_provider_holds_a_different_size_is_a_conflict():
    with given(_BASE) as context:
        agent = _ready(context)
        upload = _report(context, agent, _entry("workspace/notes.md", size=5)).json()["uploads"][0]
        fake_drive(context).complete_upload(upload["url"], b"not five bytes")

        response = _complete(context, agent, "workspace/notes.md")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(_files(context)["workspace/notes.md"].synced_at, none())


def test_completing_needs_the_agents_key_and_an_allowed_path():
    with given(_BASE) as context:
        agent = _ready(context)

        assert_that(_complete(context, agent, "workspace/notes.md", key="wrong").status_code, equal_to(401))
        assert_that(_complete(context, agent, "openclaw.json").status_code, equal_to(400))


def test_provider_throttling_tells_the_pod_when_to_come_back():
    with given(_BASE) as context:
        agent = _ready(context)
        fake_drive(context).throttle_next(120)

        response = _report(context, agent, _entry("workspace/notes.md"))

        assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
        assert_that(response.headers["Retry-After"], equal_to("120"))
        assert_that(_files(context), equal_to({}))


def test_every_report_records_when_the_pod_last_checked_in():
    with given(_BASE) as context:
        agent = _ready(context)
        assert_that(_folder(context).last_contact_at, none())

        _report(context, agent, _entry("workspace/notes.md"))

        contact = _folder(context).last_contact_at
        assert contact is not None
        assert_that((datetime.now(UTC) - contact).total_seconds(), close_to(0, 10))

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status
from hamcrest import assert_that, close_to, equal_to, has_length, none, not_none
from sqlmodel import Session

from api.domains.file_sync.models import SyncActivityKind, SyncFile
from api.domains.sync_provider.plugins.base import ProviderUnavailable, RemoteNameTaken
from api.tests.core.givenpy import given
from api.tests.steps.file_sync_ingest import (
    SHA_A,
    SHA_B,
    activity_entries,
    agent_folder,
    complete_upload,
    file_entry,
    file_sync_ingest_base,
    provider_has,
    ready_agent,
    report_files,
    synced_files,
    upload_through_the_pod,
)
from api.tests.steps.file_sync_provider import fake_drive

_BASE = file_sync_ingest_base()


def test_a_new_file_gets_an_upload_url_and_is_recorded_as_under_way():
    with given(_BASE) as context:
        agent = ready_agent(context)

        response = report_files(context, agent, file_entry("workspace/notes.md"))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        uploads = response.json()["uploads"]
        assert_that([upload["path"] for upload in uploads], equal_to(["workspace/notes.md"]))
        assert_that(uploads[0]["url"].startswith("https://testdrive.example.test/upload/"), equal_to(True))
        assert_that(uploads[0]["expires_at"], not_none())
        row = synced_files(context)["workspace/notes.md"]
        assert_that((row.local_sha256, row.size, row.item_id), equal_to((SHA_A, 5, None)))
        assert_that(row.upload_started_at, not_none())


def test_a_completed_upload_is_recorded_from_the_provider_and_not_asked_for_again():
    with given(_BASE) as context:
        agent = ready_agent(context)

        upload_through_the_pod(context, agent, "workspace/notes.md", b"hello")
        again = report_files(context, agent, file_entry("workspace/notes.md"))

        row = synced_files(context)["workspace/notes.md"]
        folder_item_id = agent_folder(context).folder_item_id
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
        agent = ready_agent(context)
        upload_through_the_pod(context, agent, "workspace/notes.md", b"hello")

        response = report_files(context, agent, file_entry("workspace/notes.md", sha=SHA_B, size=9))

        assert_that([upload["path"] for upload in response.json()["uploads"]], equal_to(["workspace/notes.md"]))
        assert_that(synced_files(context)["workspace/notes.md"].local_sha256, equal_to(SHA_B))


def test_an_upload_under_way_is_not_handed_out_again_until_its_link_could_have_expired():
    with given(_BASE) as context:
        agent = ready_agent(context)
        report_files(context, agent, file_entry("workspace/notes.md"))

        while_fresh = report_files(context, agent, file_entry("workspace/notes.md"))
        with Session(context.postgres_delegate.engine) as session:
            row = session.get(SyncFile, synced_files(context)["workspace/notes.md"].id)
            assert row is not None
            row.upload_started_at = datetime.now(UTC) - timedelta(minutes=15)
            session.add(row)
            session.commit()
        after_expiry = report_files(context, agent, file_entry("workspace/notes.md"))

        assert_that(while_fresh.json()["uploads"], equal_to([]))
        assert_that(after_expiry.json()["uploads"], has_length(1))


def test_an_empty_file_is_written_by_the_server_without_an_upload():
    with given(_BASE) as context:
        agent = ready_agent(context)

        response = report_files(
            context,
            agent,
            file_entry(
                "workspace/empty.txt", sha="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", size=0
            ),
        )

        assert_that(response.json()["uploads"], equal_to([]))
        row = synced_files(context)["workspace/empty.txt"]
        assert_that((row.item_id is not None, row.size, row.upload_started_at), equal_to((True, 0, None)))
        provider = fake_drive(context).get_item(context.sync_root, item_id=row.item_id or "")
        assert_that((provider.path, provider.size), equal_to(("Sales Bot/workspace/empty.txt", 0)))


def test_a_file_over_the_size_limit_is_skipped_and_recorded_once():
    with given(_BASE) as context:
        agent = ready_agent(context)
        huge = file_entry("workspace/video.mp4", size=100 * 1024 * 1024 + 1)

        first = report_files(context, agent, huge)
        second = report_files(context, agent, huge)

        assert_that((first.json()["uploads"], second.json()["uploads"]), equal_to(([], [])))
        assert_that(activity_entries(context), equal_to([(SyncActivityKind.SKIPPED_TOO_LARGE, "workspace/video.mp4")]))
        assert_that(synced_files(context), equal_to({}))


def test_a_name_the_provider_refuses_is_skipped_and_recorded_once():
    with given(_BASE) as context:
        agent = ready_agent(context)

        report_files(
            context,
            agent,
            file_entry("workspace/a:b.md"),
            file_entry("workspace/trailing."),
            file_entry("workspace/ok.md"),
        )
        response = report_files(context, agent, file_entry("workspace/a:b.md"), file_entry("workspace/trailing."))

        assert_that(response.json()["uploads"], equal_to([]))
        activity = activity_entries(context)
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
        agent = ready_agent(context)
        long_path = "workspace/" + "/".join(["d" * 90] * 5) + "/notes.md"

        response = report_files(context, agent, file_entry(long_path))

        assert_that(response.json()["uploads"], equal_to([]))
        assert_that(activity_entries(context), equal_to([(SyncActivityKind.SKIPPED_NAME, long_path)]))


def test_two_paths_differing_only_in_case_upload_one_and_skip_the_other():
    with given(_BASE) as context:
        agent = ready_agent(context)

        response = report_files(
            context, agent, file_entry("workspace/Notes.md"), file_entry("workspace/notes.md", sha=SHA_B)
        )

        assert_that([upload["path"] for upload in response.json()["uploads"]], equal_to(["workspace/Notes.md"]))
        assert_that(activity_entries(context), equal_to([(SyncActivityKind.SKIPPED_NAME, "workspace/notes.md")]))


def test_completing_with_no_upload_under_way_is_a_conflict():
    with given(_BASE) as context:
        agent = ready_agent(context)

        response = complete_upload(context, agent, "workspace/notes.md")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))


def test_completing_before_the_file_reached_the_provider_is_a_conflict():
    with given(_BASE) as context:
        agent = ready_agent(context)
        report_files(context, agent, file_entry("workspace/notes.md"))

        response = complete_upload(context, agent, "workspace/notes.md")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(synced_files(context)["workspace/notes.md"].item_id, none())


def test_an_office_file_the_provider_rewrote_is_confirmed_from_the_providers_record():
    with given(_BASE) as context:
        agent = ready_agent(context)
        upload = report_files(context, agent, file_entry("workspace/report.docx", size=877)).json()["uploads"][0]
        stored = fake_drive(context).complete_upload(upload["url"], b"x" * 877)

        response = complete_upload(context, agent, "workspace/report.docx")

        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        row = synced_files(context)["workspace/report.docx"]
        assert_that((row.item_id, row.ctag, row.size), equal_to((stored.id, stored.content_version, 877)))
        assert_that(row.upload_started_at, none())
        assert_that(stored.size > 877, equal_to(True))


def test_completing_when_a_person_wrote_the_file_is_a_conflict():
    with given(_BASE) as context:
        agent = ready_agent(context)
        report_files(context, agent, file_entry("workspace/notes.md", size=5))
        fake_drive(context).user_adds(context.sync_root, "Sales Bot/workspace/notes.md", b"mine!")

        response = complete_upload(context, agent, "workspace/notes.md")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(synced_files(context)["workspace/notes.md"].synced_at, none())


def test_completing_when_the_file_was_not_written_since_the_upload_started_is_a_conflict():
    with given(_BASE) as context:
        agent = ready_agent(context)
        upload_through_the_pod(context, agent, "workspace/notes.md", b"hello")
        node = next(node for node in fake_drive(context).nodes.values() if node.name == "notes.md")
        node.modified_at = datetime.now(UTC) - timedelta(minutes=10)
        report_files(context, agent, file_entry("workspace/notes.md", sha=SHA_B, size=5), complete=False)

        response = complete_upload(context, agent, "workspace/notes.md")

        assert_that(response.status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(synced_files(context)["workspace/notes.md"].upload_started_at, not_none())


def test_completing_needs_the_agents_key_and_an_allowed_path():
    with given(_BASE) as context:
        agent = ready_agent(context)

        assert_that(complete_upload(context, agent, "workspace/notes.md", key="wrong").status_code, equal_to(401))
        assert_that(complete_upload(context, agent, "openclaw.json").status_code, equal_to(400))


def test_provider_throttling_tells_the_pod_when_to_come_back():
    with given(_BASE) as context:
        agent = ready_agent(context)
        fake_drive(context).throttle_next(120)

        response = report_files(context, agent, file_entry("workspace/notes.md"))

        assert_that(response.status_code, equal_to(status.HTTP_503_SERVICE_UNAVAILABLE))
        assert_that(response.headers["Retry-After"], equal_to("120"))
        assert_that(synced_files(context), equal_to({}))


def test_every_report_records_when_the_pod_last_checked_in():
    with given(_BASE) as context:
        agent = ready_agent(context)
        assert_that(agent_folder(context).last_contact_at, none())

        report_files(context, agent, file_entry("workspace/notes.md"))

        contact = agent_folder(context).last_contact_at
        assert contact is not None
        assert_that((datetime.now(UTC) - contact).total_seconds(), close_to(0, 10))


def test_a_file_missing_from_a_complete_report_is_deleted_at_the_provider_and_recorded():
    with given(_BASE) as context:
        agent = ready_agent(context)
        upload_through_the_pod(context, agent, "workspace/notes.md", b"hello")
        upload_through_the_pod(context, agent, "workspace/kept.md", b"hello")

        response = report_files(context, agent, file_entry("workspace/kept.md"))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(
            (provider_has(context, "workspace/notes.md"), provider_has(context, "workspace/kept.md")),
            equal_to((False, True)),
        )
        assert_that(sorted(synced_files(context)), equal_to(["workspace/kept.md"]))
        assert_that(activity_entries(context), equal_to([(SyncActivityKind.DELETED_BY_AGENT, "workspace/notes.md")]))


def test_an_incomplete_report_never_deletes():
    with given(_BASE) as context:
        agent = ready_agent(context)
        upload_through_the_pod(context, agent, "workspace/notes.md", b"hello")

        report_files(context, agent, complete=False)

        assert_that(provider_has(context, "workspace/notes.md"), equal_to(True))
        assert_that(sorted(synced_files(context)), equal_to(["workspace/notes.md"]))
        assert_that(activity_entries(context), equal_to([]))


def test_a_file_still_listed_but_now_skipped_is_not_deleted():
    with given(_BASE) as context:
        agent = ready_agent(context)
        upload_through_the_pod(context, agent, "workspace/video.mp4", b"small")

        report_files(context, agent, file_entry("workspace/video.mp4", sha=SHA_B, size=100 * 1024 * 1024 + 1))

        assert_that(provider_has(context, "workspace/video.mp4"), equal_to(True))
        assert_that(activity_entries(context), equal_to([(SyncActivityKind.SKIPPED_TOO_LARGE, "workspace/video.mp4")]))


def test_a_path_listed_in_another_case_is_not_deleted():
    with given(_BASE) as context:
        agent = ready_agent(context)
        upload_through_the_pod(context, agent, "workspace/notes.md", b"hello")

        report_files(context, agent, file_entry("workspace/NOTES.md"))

        assert_that(provider_has(context, "workspace/notes.md"), equal_to(True))
        assert_that(activity_entries(context), equal_to([]))


def test_a_first_upload_that_never_finished_is_forgotten_without_calling_the_provider():
    with given(_BASE) as context:
        agent = ready_agent(context)
        upload_through_the_pod(context, agent, "workspace/kept.md", b"k")
        report_files(context, agent, file_entry("workspace/draft.md"), complete=False)
        calls_before = len(fake_drive(context).calls)

        report_files(context, agent, file_entry("workspace/kept.md", size=1))

        assert_that(sorted(synced_files(context)), equal_to(["workspace/kept.md"]))
        assert_that("delete_item" in fake_drive(context).calls[calls_before:], equal_to(False))
        assert_that(activity_entries(context), equal_to([]))


def test_a_file_already_gone_at_the_provider_is_simply_forgotten():
    with given(_BASE) as context:
        agent = ready_agent(context)
        upload_through_the_pod(context, agent, "workspace/notes.md", b"hello")
        upload_through_the_pod(context, agent, "workspace/kept.md", b"k")
        fake_drive(context).user_deletes(context.sync_root, "Sales Bot/workspace/notes.md")

        response = report_files(context, agent, file_entry("workspace/kept.md", size=1))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        assert_that(sorted(synced_files(context)), equal_to(["workspace/kept.md"]))


def test_a_delete_interrupted_by_throttling_is_retried_on_the_next_report():
    with given(_BASE) as context:
        agent = ready_agent(context)
        upload_through_the_pod(context, agent, "workspace/notes.md", b"hello")
        upload_through_the_pod(context, agent, "workspace/kept.md", b"k")
        fake_drive(context).throttle_next(30)

        throttled = report_files(context, agent, file_entry("workspace/kept.md", size=1))
        kept = sorted(synced_files(context))
        retried = report_files(context, agent, file_entry("workspace/kept.md", size=1))

        assert_that((throttled.status_code, retried.status_code), equal_to((503, 200)))
        assert_that(
            (kept, sorted(synced_files(context))),
            equal_to((["workspace/kept.md", "workspace/notes.md"], ["workspace/kept.md"])),
        )
        assert_that(provider_has(context, "workspace/notes.md"), equal_to(False))


def _refuse_upload_links_for(context, monkeypatch: pytest.MonkeyPatch, path: str, error: Exception) -> None:
    plugin = fake_drive(context)
    upload_target = plugin.upload_target

    def refusing(root, *, parent_id: str, rel_path: str):
        if rel_path == path:
            raise error
        return upload_target(root, parent_id=parent_id, rel_path=rel_path)

    monkeypatch.setattr(plugin, "upload_target", refusing)


@pytest.mark.parametrize(
    "error", [RemoteNameTaken("upload session refused"), ProviderUnavailable("Test Drive is down.")]
)
def test_one_file_the_provider_refuses_does_not_stop_the_rest(monkeypatch: pytest.MonkeyPatch, error):
    with given(_BASE) as context:
        agent = ready_agent(context)
        _refuse_upload_links_for(context, monkeypatch, "workspace/a.md", error)

        response = report_files(context, agent, file_entry("workspace/a.md"), file_entry("workspace/b.md"))

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that([upload["path"] for upload in response.json()["uploads"]], equal_to(["workspace/b.md"]))
        assert_that("workspace/a.md" in synced_files(context), equal_to(False))


def test_a_refused_file_gets_its_link_on_the_next_report(monkeypatch: pytest.MonkeyPatch):
    with given(_BASE) as context:
        agent = ready_agent(context)
        _refuse_upload_links_for(context, monkeypatch, "workspace/a.md", RemoteNameTaken("upload session refused"))
        report_files(context, agent, file_entry("workspace/a.md"))
        monkeypatch.undo()

        response = report_files(context, agent, file_entry("workspace/a.md"))

        assert_that([upload["path"] for upload in response.json()["uploads"]], equal_to(["workspace/a.md"]))


def test_one_delete_the_provider_fails_does_not_stop_the_others(monkeypatch: pytest.MonkeyPatch):
    with given(_BASE) as context:
        agent = ready_agent(context)
        for path in ("workspace/a.md", "workspace/b.md", "workspace/kept.md"):
            upload_through_the_pod(context, agent, path, b"hello")
        plugin = fake_drive(context)
        delete_item = plugin.delete_item
        failing_id = synced_files(context)["workspace/a.md"].item_id

        def failing(root, *, item_id: str) -> None:
            if item_id == failing_id:
                raise ProviderUnavailable("Test Drive is down.")
            delete_item(root, item_id=item_id)

        monkeypatch.setattr(plugin, "delete_item", failing)

        response = report_files(context, agent, file_entry("workspace/kept.md", size=5), complete=True)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(
            (provider_has(context, "workspace/a.md"), provider_has(context, "workspace/b.md")), equal_to((True, False))
        )
        assert_that(sorted(synced_files(context)), equal_to(["workspace/a.md", "workspace/kept.md"]))


def test_a_complete_report_with_no_files_deletes_nothing():
    with given(_BASE) as context:
        agent = ready_agent(context)
        upload_through_the_pod(context, agent, "workspace/notes.md", b"hello")

        response = report_files(context, agent, complete=True)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK), response.text)
        assert_that(provider_has(context, "workspace/notes.md"), equal_to(True))
        assert_that(sorted(synced_files(context)), equal_to(["workspace/notes.md"]))
        assert_that(activity_entries(context), equal_to([]))

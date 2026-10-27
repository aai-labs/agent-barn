import logging
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import status
from hamcrest import assert_that, close_to, equal_to, has_length, none, not_none
from sqlmodel import Session

from api.domains.agents.models import Agent
from api.domains.file_sync.models import SyncActivityKind, SyncFile, SyncPendingAction
from api.domains.sync_provider.plugins.base import ProviderUnavailable
from api.tests.core.givenpy import given
from api.tests.steps.file_sync_ingest import (
    AGENT_KEY,
    SHA_A,
    SHA_B,
    activity_entries,
    complete_upload,
    file_entry,
    file_sync_ingest_base,
    ready_agent,
    report_files,
    synced_files,
    upload_through_the_pod,
)
from api.tests.steps.file_sync_provider import fake_drive

_BASE = file_sync_ingest_base()
_PATH = "workspace/notes.md"
_REMOTE_PATH = f"Sales Bot/{_PATH}"


def _claim(context, agent: Agent, key: str = AGENT_KEY):
    return context.ingest_client.get(
        f"/ingest/v1/agents/{agent.id}/file-sync/operations", headers={"Authorization": f"Bearer {key}"}
    )


def _result(context, agent: Agent, outcome: str, path: str = _PATH, **fields):
    return context.ingest_client.post(
        f"/ingest/v1/agents/{agent.id}/file-sync/operations/result",
        json={"path": path, "outcome": outcome, **fields},
        headers={"Authorization": f"Bearer {AGENT_KEY}"},
    )


def _update(context, path: str = _PATH, **fields) -> None:
    with Session(context.postgres_delegate.engine) as session:
        row = session.get(SyncFile, synced_files(context)[path].id)
        assert row is not None
        for key, value in fields.items():
            setattr(row, key, value)
        session.add(row)
        session.commit()


def _user_edited(context, agent: Agent, content: bytes = b"user edit") -> None:
    upload_through_the_pod(context, agent, _PATH, b"hello")
    fake_drive(context).user_edits(context.sync_root, _REMOTE_PATH, content)
    _update(context, pending=SyncPendingAction.DOWNLOAD)


def _row(context) -> SyncFile:
    return synced_files(context)[_PATH]


def test_a_pending_download_is_handed_out_with_a_link_and_the_version_it_points_to():
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)

        response = _claim(context, agent)

        assert_that(response.status_code, equal_to(status.HTTP_200_OK))
        operations = response.json()["operations"]
        assert_that(operations, has_length(1))
        operation = operations[0]
        remote = fake_drive(context).get_item(context.sync_root, item_id=_row(context).item_id or "")
        assert_that(
            (operation["path"], operation["action"], operation["version"]),
            equal_to((_PATH, "download", remote.content_version)),
        )
        assert_that(fake_drive(context).content_at(operation["url"]), equal_to(b"user edit"))
        assert_that((_row(context).attempts, _row(context).lease_until is not None), equal_to((1, True)))


def test_a_claimed_job_is_not_handed_out_again_until_its_lease_runs_out():
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)
        _claim(context, agent)

        while_leased = _claim(context, agent)
        _update(context, lease_until=datetime.now(UTC) - timedelta(seconds=1))
        after_lease = _claim(context, agent)

        assert_that(while_leased.json()["operations"], equal_to([]))
        assert_that(after_lease.json()["operations"], has_length(1))
        assert_that(_row(context).attempts, equal_to(2))


def test_a_job_waiting_to_be_retried_is_not_handed_out_yet():
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)
        _update(context, retry_at=datetime.now(UTC) + timedelta(minutes=5))

        assert_that(_claim(context, agent).json()["operations"], equal_to([]))


def test_a_finished_download_is_recorded_as_synced():
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)
        operation = _claim(context, agent).json()["operations"][0]

        response = _result(context, agent, "done", version=operation["version"], sha256=SHA_B, size=9)

        assert_that(response.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        row = _row(context)
        assert_that((row.pending, row.lease_until, row.attempts), equal_to((None, None, 0)))
        assert_that((row.local_sha256, row.size, row.ctag), equal_to((SHA_B, 9, operation["version"])))


def test_a_download_overtaken_by_another_edit_is_queued_again():
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)
        operation = _claim(context, agent).json()["operations"][0]
        fake_drive(context).user_edits(context.sync_root, _REMOTE_PATH, b"a newer edit")

        _result(context, agent, "done", version=operation["version"], sha256=SHA_B, size=9)

        row = _row(context)
        assert_that((row.pending, row.lease_until), equal_to((SyncPendingAction.DOWNLOAD, None)))
        assert_that(_claim(context, agent).json()["operations"], has_length(1))


def test_no_space_for_a_download_is_recorded_once_and_retried_later():
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)
        _claim(context, agent)
        _result(context, agent, "skipped_no_space")
        _update(context, retry_at=None)
        _claim(context, agent)

        _result(context, agent, "skipped_no_space")

        row = _row(context)
        assert row.retry_at is not None
        assert_that((row.retry_at - datetime.now(UTC)).total_seconds(), close_to(300, 10))
        assert_that((row.pending, row.lease_until), equal_to((SyncPendingAction.DOWNLOAD, None)))
        assert_that(activity_entries(context), equal_to([(SyncActivityKind.SKIPPED_NO_SPACE, _PATH)]))


@pytest.mark.parametrize(("attempts", "wait"), [(1, 60), (2, 120), (6, 1800), (20, 1800)])
def test_a_failed_job_waits_longer_after_each_attempt(attempts, wait):
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)
        _claim(context, agent)
        _update(context, attempts=attempts)

        _result(context, agent, "failed")

        row = _row(context)
        assert row.retry_at is not None
        assert_that((row.retry_at - datetime.now(UTC)).total_seconds(), close_to(wait, 10))
        assert_that((row.pending, row.lease_until), equal_to((SyncPendingAction.DOWNLOAD, None)))


def test_a_download_the_agent_overtook_locally_is_dropped_and_the_agent_wins():
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)
        _claim(context, agent)

        _result(context, agent, "local_changed")

        row = _row(context)
        assert_that((row.pending, row.lease_until), equal_to((None, None)))
        assert_that(activity_entries(context), equal_to([(SyncActivityKind.CONFLICT_AGENT_WON, _PATH)]))


def test_a_report_with_new_local_content_beats_a_pending_download():
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)

        response = report_files(context, agent, file_entry(_PATH, sha=SHA_B, size=11))

        assert_that([upload["path"] for upload in response.json()["uploads"]], equal_to([_PATH]))
        assert_that(_row(context).pending, none())
        assert_that(activity_entries(context), equal_to([(SyncActivityKind.CONFLICT_AGENT_WON, _PATH)]))
        assert_that(_claim(context, agent).json()["operations"], equal_to([]))


def test_a_report_with_unchanged_local_content_leaves_the_download_pending():
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)

        response = report_files(context, agent, file_entry(_PATH, sha=SHA_A, size=5))

        assert_that(response.json()["uploads"], equal_to([]))
        assert_that(_row(context).pending, equal_to(SyncPendingAction.DOWNLOAD))
        assert_that(activity_entries(context), equal_to([]))


def test_a_pending_reupload_hands_out_an_upload_link_finished_by_upload_completion():
    with given(_BASE) as context:
        agent = ready_agent(context)
        upload_through_the_pod(context, agent, _PATH, b"hello")
        fake_drive(context).user_edits(context.sync_root, _REMOTE_PATH, b"user edit")
        _update(context, pending=SyncPendingAction.REUPLOAD)

        operation = _claim(context, agent).json()["operations"][0]
        fake_drive(context).complete_upload(operation["url"], b"hello")
        completed = complete_upload(context, agent, _PATH)

        assert_that((operation["action"], operation["expires_at"] is not None), equal_to(("reupload", True)))
        assert_that(completed.status_code, equal_to(status.HTTP_204_NO_CONTENT))
        row = _row(context)
        assert_that((row.pending, row.upload_started_at, row.lease_until), equal_to((None, None, None)))
        remote = fake_drive(context).get_item(context.sync_root, item_id=row.item_id or "")
        assert_that(
            fake_drive(context).content_at(fake_drive(context).download_url(context.sync_root, item_id=remote.id)),
            equal_to(b"hello"),
        )


def test_a_download_whose_file_is_gone_at_the_provider_is_dropped():
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)
        fake_drive(context).user_deletes(context.sync_root, _REMOTE_PATH)

        response = _claim(context, agent)

        assert_that(response.json()["operations"], equal_to([]))
        assert_that(_row(context).pending, none())


def test_a_result_needs_a_job_handed_out_for_that_path():
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)

        assert_that(_result(context, agent, "failed").status_code, equal_to(status.HTTP_409_CONFLICT))
        assert_that(
            _result(context, agent, "failed", path="workspace/other.md").status_code, equal_to(status.HTTP_409_CONFLICT)
        )


def test_jobs_and_results_need_the_agents_key_and_an_allowed_path():
    with given(_BASE) as context:
        agent = ready_agent(context)

        assert_that(_claim(context, agent, key="wrong").status_code, equal_to(status.HTTP_401_UNAUTHORIZED))
        assert_that(_result(context, agent, "failed", path="openclaw.json").status_code, equal_to(400))
        assert_that(_result(context, agent, "exploded").status_code, equal_to(422))


def test_handing_out_jobs_records_contact_and_never_returns_anything_but_links():
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)

        operation = _claim(context, agent).json()["operations"][0]

        assert_that(sorted(operation), equal_to(["action", "expires_at", "path", "url", "version"]))
        assert_that(synced_files(context)[_PATH].lease_until, not_none())


def test_a_claimed_job_is_leased_just_past_the_pods_wait():
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)

        _claim(context, agent)

        lease_until = _row(context).lease_until
        assert lease_until is not None
        lease = (lease_until - datetime.now(UTC)).total_seconds()
        assert_that(lease, close_to(180, 10))


def test_a_provider_failure_is_logged_before_the_502(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture):
    with given(_BASE) as context:
        agent = ready_agent(context)
        _user_edited(context, agent)

        def unavailable(root, *, item_id: str) -> str:
            raise ProviderUnavailable("Microsoft couldn't be reached")

        monkeypatch.setattr(fake_drive(context), "download_url", unavailable)

        with caplog.at_level(logging.WARNING):
            response = _claim(context, agent)

        assert_that(response.status_code, equal_to(status.HTTP_502_BAD_GATEWAY))
        logged = [record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING]
        assert_that(any("ProviderUnavailable" in line and str(agent.id) in line for line in logged), equal_to(True))

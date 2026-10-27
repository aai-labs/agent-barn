"""The Graph driveItem calls Agent file sync makes as the platform app. Payload shapes are copied
from the AF-384 verification against a real SharePoint library."""

from datetime import UTC, datetime

import httpx
import pytest
from hamcrest import assert_that, equal_to, none

from api.domains.agents.microsoft_graph_files import (
    DeltaPage,
    DriveItem,
    GraphAccessRefused,
    GraphItemLocked,
    GraphItemNotFound,
    GraphNameConflict,
    GraphPreconditionFailed,
    GraphRequestRejected,
    GraphResyncRequired,
    GraphThrottled,
    GraphTokenRejected,
    GraphUnavailable,
    MicrosoftGraphFiles,
    UploadSession,
    delta_start_url,
)
from api.infrastructure.http import retry_after_seconds

_GRAPH = "https://graph.microsoft.com/v1.0"
_SITE = "aailabs.sharepoint.com,e5dfdaea-bc3c-4b11-a70c-702892a71f7c,7ac376a3-288e-46ab-8735-2aeb42fce7b5"
_DRIVE = f"{_GRAPH}/sites/{_SITE}/drive"
_FILE_ID = "01F65KC4OOANM5D7XUD5CIR2TORAVY3SRI"
_FOLDER_ID = "01F65KC4IA2A6IGVB4OZH2P6CGLMGF7U4C"
_FILE_URL = "https://aailabs.sharepoint.com/sites/AgentBarnTest/Shared%20Documents/Agent%20Barn/AF384%20Test/hello.md"
_FILE = {
    "id": _FILE_ID,
    "name": "hello.md",
    "eTag": '"{D15903CE-F4FE-441F-88EA-6E882B8DCA28},2"',
    "cTag": '"c:{D15903CE-F4FE-441F-88EA-6E882B8DCA28},2"',
    "size": 22,
    "lastModifiedDateTime": "2026-10-21T08:39:12Z",
    "lastModifiedBy": {"user": {"email": "dominykas@aai-labs.com", "displayName": "Dominykas"}},
    "parentReference": {
        "id": "01F65KC4IA2A6IGVB4OZH2P6CGLMGF7U4C",
        "path": "/drives/b!6trf/root:/Agent Barn/AF384 Test",
    },
    "file": {"hashes": {"quickXorHash": "aSxzM1vs4ODedgYgJoMc3tAGEIQ="}, "mimeType": "text/markdown"},
    "webUrl": _FILE_URL,
}
_APP_FILE = {
    **_FILE,
    "lastModifiedBy": {"application": {"displayName": "Agent Barn"}, "user": {"displayName": "SharePoint App"}},
}
_DELETED = {
    "id": _FILE_ID,
    "parentReference": {"id": "01F65KC4OXE6U2ZUAHXNEYKTVCOSGZMYPA"},
    "cTag": '"c:{D15903CE-F4FE-441F-88EA-6E882B8DCA28},-1"',
    "deleted": {"state": "deleted"},
    "file": {"hashes": {"quickXorHash": "AAAAAAAAAAAAAAAAAAAAAAAAAAA="}},
    "size": 0,
}
_FOLDER = {
    "id": _FOLDER_ID,
    "name": "AF384 Test",
    "eTag": '"{833CD000-3C54-4F76-A7F8-465B0C5FD382},2"',
    "size": -13,
    "parentReference": {"id": "01F65KC4PUTIGIFLJ4WBGZHXW6AHK22MPR", "path": "/drives/b!6trf/root:/Agent Barn"},
    "folder": {"childCount": 1},
    "webUrl": "https://aailabs.sharepoint.com/sites/AgentBarnTest/Shared%20Documents/Agent%20Barn/AF384%20Test",
}


class _Recorder:
    def __init__(self, *responses: httpx.Response | Exception):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, method, url, headers=None, json=None, content=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json, "content": content})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def graph(monkeypatch):
    def install(*responses):
        recorder = _Recorder(*responses)
        monkeypatch.setattr(httpx, "request", recorder)
        return recorder

    return install


def test_an_item_is_read_with_its_tags_hash_and_parent(graph):
    recorder = graph(httpx.Response(200, json=_FILE))

    item = MicrosoftGraphFiles().get_item("app-token", site_id=_SITE, item_id=_FILE_ID)

    assert_that(
        item,
        equal_to(
            DriveItem(
                id=_FILE_ID,
                name="hello.md",
                parent_id="01F65KC4IA2A6IGVB4OZH2P6CGLMGF7U4C",
                parent_path="/drives/b!6trf/root:/Agent Barn/AF384 Test",
                etag='"{D15903CE-F4FE-441F-88EA-6E882B8DCA28},2"',
                ctag='"c:{D15903CE-F4FE-441F-88EA-6E882B8DCA28},2"',
                size=22,
                quick_xor_hash="aSxzM1vs4ODedgYgJoMc3tAGEIQ=",
                is_folder=False,
                deleted=False,
                modified_at=datetime(2026, 10, 21, 8, 39, 12, tzinfo=UTC),
                modified_by_app=False,
                web_url=_FILE_URL,
            )
        ),
    )
    assert_that(recorder.calls[0]["method"], equal_to("GET"))
    assert_that(recorder.calls[0]["url"], equal_to(f"{_DRIVE}/items/{_FILE_ID}"))
    assert_that(recorder.calls[0]["headers"], equal_to({"Authorization": "Bearer app-token"}))


def test_an_item_last_changed_by_an_app_says_so(graph):
    graph(httpx.Response(200, json=_APP_FILE))

    item = MicrosoftGraphFiles().get_item("app-token", site_id=_SITE, item_id=_FILE_ID)

    assert_that(item.modified_by_app, equal_to(True))


def test_an_app_acting_for_a_person_is_the_persons_change(graph):
    office_edit = {
        **_FILE,
        "lastModifiedBy": {
            "application": {"displayName": "Microsoft Office"},
            "user": {"email": "dominykas@aai-labs.com", "displayName": "Dominykas"},
        },
    }
    graph(httpx.Response(200, json=office_edit))

    item = MicrosoftGraphFiles().get_item("app-token", site_id=_SITE, item_id=_FILE_ID)

    assert_that(item.modified_by_app, equal_to(False))


def test_a_persons_edit_carries_no_application(graph):
    graph(httpx.Response(200, json=_FILE))

    item = MicrosoftGraphFiles().get_item("app-token", site_id=_SITE, item_id=_FILE_ID)

    assert_that(item.modified_by_app, equal_to(False))


def test_an_item_is_read_by_a_path_under_a_folder_with_each_segment_encoded(graph):
    recorder = graph(httpx.Response(200, json=_FILE))

    MicrosoftGraphFiles().get_item_by_path(
        "app-token", site_id=_SITE, parent_id="parent-1", rel_path="workspace/Q3 #1/50% done.md"
    )

    assert_that(
        recorder.calls[0]["url"],
        equal_to(f"{_DRIVE}/items/parent-1:/workspace/Q3%20%231/50%25%20done.md:"),
    )


def test_a_missing_item_is_not_found(graph):
    graph(httpx.Response(404, json={"error": {"code": "itemNotFound"}}))

    with pytest.raises(GraphItemNotFound):
        MicrosoftGraphFiles().get_item("app-token", site_id=_SITE, item_id="gone")


def test_a_folder_is_created_and_never_merged_into_an_existing_one(graph):
    recorder = graph(httpx.Response(201, json=_FOLDER))

    folder = MicrosoftGraphFiles().create_folder("app-token", site_id=_SITE, parent_id="barn-1", name="Sales Bot")

    assert_that(folder.is_folder, equal_to(True))
    assert_that(folder.size, equal_to(0))
    assert_that(recorder.calls[0]["method"], equal_to("POST"))
    assert_that(recorder.calls[0]["url"], equal_to(f"{_DRIVE}/items/barn-1/children"))
    assert_that(
        recorder.calls[0]["json"],
        equal_to({"name": "Sales Bot", "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}),
    )


def test_a_name_already_taken_is_a_name_conflict(graph):
    graph(httpx.Response(409, json={"error": {"code": "nameAlreadyExists"}}))

    with pytest.raises(GraphNameConflict):
        MicrosoftGraphFiles().create_folder("app-token", site_id=_SITE, parent_id="barn-1", name="Sales Bot")


def test_an_item_is_renamed_and_moved_in_one_request(graph):
    recorder = graph(httpx.Response(200, json=_FILE))

    MicrosoftGraphFiles().move_item("app-token", site_id=_SITE, item_id="item-1", name="notes.md", parent_id="folder-2")

    assert_that(recorder.calls[0]["method"], equal_to("PATCH"))
    assert_that(recorder.calls[0]["url"], equal_to(f"{_DRIVE}/items/item-1"))
    assert_that(recorder.calls[0]["json"], equal_to({"name": "notes.md", "parentReference": {"id": "folder-2"}}))


def test_a_rename_alone_sends_only_the_name(graph):
    recorder = graph(httpx.Response(200, json=_FILE))

    MicrosoftGraphFiles().move_item("app-token", site_id=_SITE, item_id="item-1", name="notes.md")

    assert_that(recorder.calls[0]["json"], equal_to({"name": "notes.md"}))


def test_deleting_an_item_already_gone_is_not_an_error(graph):
    recorder = graph(httpx.Response(204), httpx.Response(404, json={"error": {"code": "itemNotFound"}}))

    MicrosoftGraphFiles().delete_item("app-token", site_id=_SITE, item_id="item-1")
    MicrosoftGraphFiles().delete_item("app-token", site_id=_SITE, item_id="item-1")

    assert_that([call["method"] for call in recorder.calls], equal_to(["DELETE", "DELETE"]))
    assert_that(recorder.calls[0]["url"], equal_to(f"{_DRIVE}/items/item-1"))


def test_the_change_feed_starts_from_now_or_from_the_beginning():
    assert_that(
        delta_start_url(site_id=_SITE, folder_id="barn-1", from_now=True),
        equal_to(f"{_DRIVE}/items/barn-1/delta?token=latest"),
    )
    assert_that(
        delta_start_url(site_id=_SITE, folder_id="barn-1", from_now=False), equal_to(f"{_DRIVE}/items/barn-1/delta")
    )


def test_a_change_page_is_read_from_the_absolute_link_and_keeps_deleted_items(graph):
    next_link = "https://graph.microsoft.com/v1.0/drives/b!6trf/items/barn-1/delta?token=page2"
    recorder = graph(httpx.Response(200, json={"value": [_FILE, _DELETED, _FOLDER], "@odata.nextLink": next_link}))

    page = MicrosoftGraphFiles().delta_page(
        "app-token", "https://graph.microsoft.com/v1.0/drives/b!6trf/items/barn-1/delta?token=a"
    )

    assert_that(
        recorder.calls[0]["url"], equal_to("https://graph.microsoft.com/v1.0/drives/b!6trf/items/barn-1/delta?token=a")
    )
    assert_that(page.next_link, equal_to(next_link))
    assert_that(page.delta_link, none())
    assert_that([item.id for item in page.items], equal_to([_FILE_ID, _FILE_ID, _FOLDER_ID]))
    deleted = page.items[1]
    assert_that((deleted.deleted, deleted.name, deleted.parent_path), equal_to((True, None, None)))
    assert_that(deleted.parent_id, equal_to("01F65KC4OXE6U2ZUAHXNEYKTVCOSGZMYPA"))


def test_the_last_change_page_carries_the_next_cursor(graph):
    delta_link = "https://graph.microsoft.com/v1.0/drives/b!6trf/items/barn-1/delta?token=next"
    graph(httpx.Response(200, json={"value": [], "@odata.deltaLink": delta_link}))

    page = MicrosoftGraphFiles().delta_page("app-token", f"{_DRIVE}/items/barn-1/delta")

    assert_that(page, equal_to(DeltaPage(items=[], next_link=None, delta_link=delta_link)))


def test_an_expired_change_cursor_asks_for_a_full_resync(graph):
    graph(httpx.Response(410, json={"error": {"code": "resyncRequired"}}))

    with pytest.raises(GraphResyncRequired):
        MicrosoftGraphFiles().delta_page("app-token", f"{_DRIVE}/items/barn-1/delta?token=old")


def test_an_upload_session_replaces_the_file_at_its_path(graph):
    recorder = graph(
        httpx.Response(
            200,
            json={
                "uploadUrl": "https://aailabs.sharepoint.com/_api/v2.0/drives/x/items/y/uploadSession?tempauth=v1.e",
                "expirationDateTime": "2026-10-21T08:55:19.626Z",
                "nextExpectedRanges": ["0-"],
            },
        )
    )

    session = MicrosoftGraphFiles().create_upload_session(
        "app-token", site_id=_SITE, parent_id="folder-1", rel_path="workspace/Q3 report.docx"
    )

    assert_that(
        session,
        equal_to(
            UploadSession(
                upload_url="https://aailabs.sharepoint.com/_api/v2.0/drives/x/items/y/uploadSession?tempauth=v1.e",
                expires_at=datetime(2026, 10, 21, 8, 55, 19, 626000, tzinfo=UTC),
            )
        ),
    )
    assert_that(recorder.calls[0]["method"], equal_to("POST"))
    assert_that(
        recorder.calls[0]["url"],
        equal_to(f"{_DRIVE}/items/folder-1:/workspace/Q3%20report.docx:/createUploadSession"),
    )
    assert_that(recorder.calls[0]["json"], equal_to({"item": {"@microsoft.graph.conflictBehavior": "replace"}}))


def test_an_upload_session_without_a_link_is_unavailable(graph):
    graph(httpx.Response(200, json={"expirationDateTime": "2026-10-21T08:55:19.626Z"}))

    with pytest.raises(GraphUnavailable):
        MicrosoftGraphFiles().create_upload_session("app-token", site_id=_SITE, parent_id="folder-1", rel_path="a.md")


def test_a_download_link_is_read_from_the_item(graph):
    recorder = graph(
        httpx.Response(
            200, json={"id": "item-1", "@microsoft.graph.downloadUrl": "https://aailabs.sharepoint.com/dl?t=1"}
        )
    )

    url = MicrosoftGraphFiles().download_url("app-token", site_id=_SITE, item_id="item-1")

    assert_that(url, equal_to("https://aailabs.sharepoint.com/dl?t=1"))
    assert_that(recorder.calls[0]["url"], equal_to(f"{_DRIVE}/items/item-1?select=id,@microsoft.graph.downloadUrl"))


def test_an_item_without_a_download_link_is_unavailable(graph):
    graph(httpx.Response(200, json={"id": "item-1"}))

    with pytest.raises(GraphUnavailable):
        MicrosoftGraphFiles().download_url("app-token", site_id=_SITE, item_id="item-1")


def test_an_empty_file_is_written_directly_because_upload_sessions_refuse_it(graph):
    recorder = graph(httpx.Response(201, json={**_APP_FILE, "size": 0}))

    item = MicrosoftGraphFiles().put_empty_file(
        "app-token", site_id=_SITE, parent_id="folder-1", rel_path="workspace/empty.txt"
    )

    assert_that(item.size, equal_to(0))
    assert_that(recorder.calls[0]["method"], equal_to("PUT"))
    assert_that(recorder.calls[0]["url"], equal_to(f"{_DRIVE}/items/folder-1:/workspace/empty.txt:/content"))
    assert_that(recorder.calls[0]["content"], equal_to(b""))
    assert_that(recorder.calls[0]["json"], none())


@pytest.mark.parametrize(
    ("status", "error"),
    [
        (400, GraphRequestRejected),
        (401, GraphTokenRejected),
        (403, GraphAccessRefused),
        (412, GraphPreconditionFailed),
        (423, GraphItemLocked),
        (500, GraphUnavailable),
    ],
)
def test_graph_failures_map_to_typed_errors(graph, status, error):
    graph(httpx.Response(status, json={"error": {"code": "x"}}))

    with pytest.raises(error):
        MicrosoftGraphFiles().get_item("app-token", site_id=_SITE, item_id="item-1")


def test_rejections_are_still_unavailable_for_callers_that_undo_on_any_failure():
    for error in (
        GraphRequestRejected,
        GraphNameConflict,
        GraphPreconditionFailed,
        GraphResyncRequired,
        GraphThrottled,
        GraphItemLocked,
    ):
        assert_that(issubclass(error, GraphUnavailable), equal_to(True))


def test_throttling_carries_the_full_retry_after(graph):
    graph(httpx.Response(429, headers={"Retry-After": "120"}, json={"error": {"code": "activityLimitReached"}}))

    with pytest.raises(GraphThrottled) as exc:
        MicrosoftGraphFiles().get_item("app-token", site_id=_SITE, item_id="item-1")

    assert_that(exc.value.retry_after, equal_to(120))


def test_throttling_without_retry_after_waits_the_default(graph):
    graph(httpx.Response(429))

    with pytest.raises(GraphThrottled) as exc:
        MicrosoftGraphFiles().get_item("app-token", site_id=_SITE, item_id="item-1")

    assert_that(exc.value.retry_after, equal_to(1))


def test_an_unreachable_graph_is_unavailable(graph):
    graph(httpx.ConnectError("boom"))

    with pytest.raises(GraphUnavailable):
        MicrosoftGraphFiles().get_item("app-token", site_id=_SITE, item_id="item-1")


def test_a_success_without_json_is_unavailable(graph):
    graph(httpx.Response(200, content=b"<html>"))

    with pytest.raises(GraphUnavailable):
        MicrosoftGraphFiles().get_item("app-token", site_id=_SITE, item_id="item-1")


def test_retry_after_keeps_its_cap_unless_a_caller_lifts_it():
    assert_that(retry_after_seconds("120"), equal_to(30))
    assert_that(retry_after_seconds("120", max_seconds=None), equal_to(120))
    assert_that(retry_after_seconds("0", max_seconds=None), equal_to(1))
    assert_that(retry_after_seconds(None, max_seconds=None), equal_to(1))
    assert_that(retry_after_seconds("soon", max_seconds=None), equal_to(1))


def test_a_rejected_token_is_still_access_refused_for_callers_that_dont_retry():
    assert_that(issubclass(GraphTokenRejected, GraphAccessRefused), equal_to(True))


def test_service_unavailable_is_throttling_with_microsofts_wait(graph):
    graph(httpx.Response(503, headers={"Retry-After": "7"}))

    with pytest.raises(GraphThrottled) as exc:
        MicrosoftGraphFiles().get_item("app-token", site_id=_SITE, item_id="item-1")

    assert_that(exc.value.retry_after, equal_to(7))


def test_service_unavailable_without_retry_after_waits_the_default(graph):
    graph(httpx.Response(503))

    with pytest.raises(GraphThrottled) as exc:
        MicrosoftGraphFiles().get_item("app-token", site_id=_SITE, item_id="item-1")

    assert_that(exc.value.retry_after, equal_to(1))

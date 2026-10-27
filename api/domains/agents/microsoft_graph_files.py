"""Microsoft Graph driveItem calls Agent file sync makes as the platform app in one site's default
document library: read items and the change feed, create, move and delete items, and hand out
pre-authenticated upload and download URLs.

Kept apart from ``microsoft_graph_sites`` so the SharePoint integration and the connect flow keep
their own request handling. Shapes follow Graph's driveItem, delta and upload session APIs, as
observed against a real library in the AF-384 verification.
"""

import urllib.parse
from dataclasses import dataclass
from datetime import datetime

import httpx
from injector import singleton

from api.infrastructure.http import retry_after_seconds

_GRAPH = "https://graph.microsoft.com/v1.0"
_TIMEOUT_SECONDS = 30
_CREATE_CONFLICT_BEHAVIOR = "fail"
_UPLOAD_CONFLICT_BEHAVIOR = "replace"
_DOWNLOAD_URL_FIELD = "@microsoft.graph.downloadUrl"


class GraphUnavailable(Exception):
    """Graph could not be reached, or answered with something unexpected."""


class GraphItemNotFound(Exception):
    """No item at that id or path, or the app can't see it."""


class GraphAccessRefused(Exception):
    """Graph refused the app (401 or 403)."""


class GraphTokenRejected(GraphAccessRefused):
    pass


class GraphRequestRejected(GraphUnavailable):
    """Graph rejected the request itself (400), for example a name it does not allow."""


class GraphNameConflict(GraphUnavailable):
    """An item with that name already exists where it was to be created (409)."""


class GraphPreconditionFailed(GraphUnavailable):
    """The item changed since the version the request named (412)."""


class GraphResyncRequired(GraphUnavailable):
    """The change cursor is no longer valid; the folder has to be read again from the start (410)."""


class GraphThrottled(GraphUnavailable):
    """Graph is limiting requests (429), or is briefly unavailable (503). ``retry_after`` is the wait it
    asked for, in seconds."""

    def __init__(self, retry_after: int):
        super().__init__(f"HTTP 429, retry after {retry_after}s")
        self.retry_after = retry_after


@dataclass(frozen=True)
class DriveItem:
    id: str
    name: str | None
    parent_id: str | None
    parent_path: str | None
    etag: str | None
    ctag: str | None
    size: int
    quick_xor_hash: str | None
    is_folder: bool
    deleted: bool
    modified_at: datetime | None
    modified_by_app: bool
    web_url: str | None


@dataclass(frozen=True)
class DeltaPage:
    items: list[DriveItem]
    next_link: str | None
    delta_link: str | None


@dataclass(frozen=True)
class UploadSession:
    upload_url: str
    expires_at: datetime


def _drive(site_id: str) -> str:
    return f"{_GRAPH}/sites/{site_id}/drive"


def _item_path(site_id: str, parent_id: str, rel_path: str) -> str:
    segments = "/".join(urllib.parse.quote(segment, safe="") for segment in rel_path.split("/"))
    return f"{_drive(site_id)}/items/{parent_id}:/{segments}:"


def delta_start_url(*, site_id: str, folder_id: str, from_now: bool) -> str:
    """The first change-feed request for a folder: from now on, or everything under it so far."""
    url = f"{_drive(site_id)}/items/{folder_id}/delta"
    return f"{url}?token=latest" if from_now else url


@singleton
class MicrosoftGraphFiles:
    def get_item(self, token: str, *, site_id: str, item_id: str) -> DriveItem:
        return _drive_item(self._call("GET", f"{_drive(site_id)}/items/{item_id}", token))

    def get_item_by_path(self, token: str, *, site_id: str, parent_id: str, rel_path: str) -> DriveItem:
        return _drive_item(self._call("GET", _item_path(site_id, parent_id, rel_path), token))

    def create_folder(self, token: str, *, site_id: str, parent_id: str, name: str) -> DriveItem:
        """A new folder ``name`` under ``parent_id``. A name already taken is ``GraphNameConflict``."""
        body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": _CREATE_CONFLICT_BEHAVIOR}
        return _drive_item(self._call("POST", f"{_drive(site_id)}/items/{parent_id}/children", token, body=body))

    def move_item(
        self, token: str, *, site_id: str, item_id: str, name: str | None = None, parent_id: str | None = None
    ) -> DriveItem:
        """Rename the item, move it under ``parent_id``, or both in one request."""
        body: dict = {}
        if name is not None:
            body["name"] = name
        if parent_id is not None:
            body["parentReference"] = {"id": parent_id}
        return _drive_item(self._call("PATCH", f"{_drive(site_id)}/items/{item_id}", token, body=body))

    def delete_item(self, token: str, *, site_id: str, item_id: str) -> None:
        """Send the item to the site's recycle bin. One already gone is not an error."""
        try:
            self._call("DELETE", f"{_drive(site_id)}/items/{item_id}", token)
        except GraphItemNotFound:
            pass

    def list_children(self, token: str, *, site_id: str, item_id: str) -> list[DriveItem]:
        url: str | None = f"{_drive(site_id)}/items/{item_id}/children"
        children: list[DriveItem] = []
        while url is not None:
            payload = _object(self._call("GET", url, token))
            entries = payload.get("value")
            if not isinstance(entries, list):
                raise GraphUnavailable("children page without a value list")
            children.extend(_drive_item(entry) for entry in entries)
            url = _text(payload.get("@odata.nextLink"))
        return children

    def delta_page(self, token: str, url: str) -> DeltaPage:
        """One page of the change feed at ``url``: a start URL, a ``nextLink`` or a ``deltaLink``."""
        payload = _object(self._call("GET", url, token))
        entries = payload.get("value")
        if not isinstance(entries, list):
            raise GraphUnavailable("change page without a value list")
        return DeltaPage(
            items=[_drive_item(entry) for entry in entries if isinstance(entry, dict)],
            next_link=_text(payload.get("@odata.nextLink")),
            delta_link=_text(payload.get("@odata.deltaLink")),
        )

    def create_upload_session(self, token: str, *, site_id: str, parent_id: str, rel_path: str) -> UploadSession:
        """A pre-authenticated URL the Agent's pod uploads the file at ``rel_path`` to, replacing it."""
        body = {"item": {"@microsoft.graph.conflictBehavior": _UPLOAD_CONFLICT_BEHAVIOR}}
        payload = _object(
            self._call("POST", f"{_item_path(site_id, parent_id, rel_path)}/createUploadSession", token, body=body)
        )
        upload_url = _text(payload.get("uploadUrl"))
        expires = _text(payload.get("expirationDateTime"))
        if upload_url is None or expires is None:
            raise GraphUnavailable("upload session without a URL or expiry")
        return UploadSession(upload_url=upload_url, expires_at=_timestamp(expires))

    def download_url(self, token: str, *, site_id: str, item_id: str) -> str:
        """A short-lived pre-authenticated URL the Agent's pod downloads the item from."""
        payload = _object(
            self._call("GET", f"{_drive(site_id)}/items/{item_id}?select=id,{_DOWNLOAD_URL_FIELD}", token)
        )
        url = _text(payload.get(_DOWNLOAD_URL_FIELD))
        if url is None:
            raise GraphUnavailable("item without a download URL")
        return url

    def put_empty_file(self, token: str, *, site_id: str, parent_id: str, rel_path: str) -> DriveItem:
        """Write a 0-byte file at ``rel_path``. Upload sessions refuse an empty upload."""
        return _drive_item(self._call("PUT", f"{_item_path(site_id, parent_id, rel_path)}/content", token, content=b""))

    @staticmethod
    def _call(method: str, url: str, token: str, *, body: dict | None = None, content: bytes | None = None) -> object:
        try:
            response = httpx.request(
                method,
                url,
                headers={"Authorization": f"Bearer {token}"},
                json=body,
                content=content,
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise GraphUnavailable(type(exc).__name__) from exc
        status = response.status_code
        if status == 404:
            raise GraphItemNotFound(f"HTTP {status}")
        if status == 401:
            raise GraphTokenRejected(f"HTTP {status}")
        if status == 403:
            raise GraphAccessRefused(f"HTTP {status}")
        if status in (429, 503):
            raise GraphThrottled(retry_after_seconds(response.headers.get("Retry-After"), max_seconds=None))
        if status == 400:
            raise GraphRequestRejected(f"HTTP {status}")
        if status == 409:
            raise GraphNameConflict(f"HTTP {status}")
        if status == 410:
            raise GraphResyncRequired(f"HTTP {status}")
        if status == 412:
            raise GraphPreconditionFailed(f"HTTP {status}")
        if status >= 300:
            raise GraphUnavailable(f"HTTP {status}")
        if status == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise GraphUnavailable(f"HTTP {status} without a JSON body") from exc


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _object(value: object) -> dict[str, object]:
    return {str(key): entry for key, entry in value.items()} if isinstance(value, dict) else {}


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _drive_item(payload: object) -> DriveItem:
    item = _object(payload)
    item_id = _text(item.get("id"))
    if item_id is None:
        raise GraphUnavailable("item response without an id")
    parent = _object(item.get("parentReference"))
    hashes = _object(_object(item.get("file")).get("hashes"))
    modified = _text(item.get("lastModifiedDateTime"))
    modified_by = _object(item.get("lastModifiedBy"))
    size = item.get("size")
    is_folder = "folder" in item
    return DriveItem(
        id=item_id,
        name=_text(item.get("name")),
        parent_id=_text(parent.get("id")),
        parent_path=_text(parent.get("path")),
        etag=_text(item.get("eTag")),
        ctag=_text(item.get("cTag")),
        size=size if isinstance(size, int) and not is_folder else 0,
        quick_xor_hash=_text(hashes.get("quickXorHash")),
        is_folder=is_folder,
        deleted="deleted" in item,
        modified_at=_timestamp(modified) if modified else None,
        modified_by_app="application" in modified_by and _text(_object(modified_by.get("user")).get("email")) is None,
        web_url=_text(item.get("webUrl")),
    )

"""Microsoft Graph calls that find SharePoint sites, grant and revoke an app's access to one, and
ensure a folder in its default document library.

Under ``Sites.Selected`` an app reaches nothing until each site is granted to it, and the grant
is made with a token that can manage the site's permissions — here the administrator's, from the
selected-sites sign-in. Request shapes follow Graph's site permission and driveItem APIs.
"""

import urllib.parse
from dataclasses import dataclass

import httpx
from injector import singleton

from api.domains.agents.sharepoint_sites import site_graph_path

_GRAPH = "https://graph.microsoft.com/v1.0"
_TIMEOUT_SECONDS = 30
_FOLDER_CONFLICT_BEHAVIOR = "fail"


@dataclass(frozen=True)
class SiteSummary:
    id: str
    name: str
    web_url: str


@dataclass(frozen=True)
class FolderRef:
    item_id: str
    web_url: str


class SiteNotFound(Exception):
    """Graph knows no site at that URL, or the signed-in account can't see it."""


class SiteAccessRefused(Exception):
    """Graph refused to manage the site's permissions: the account is not an administrator."""


class SitesUnavailable(Exception):
    """Graph could not be reached, or answered with something unexpected."""


class SiteChangeRejected(SitesUnavailable):
    """Graph rejected the request itself (400 or 409). Still a ``SitesUnavailable``, so callers
    that undo an attempt on any Graph failure keep doing so."""


class SitesThrottled(SitesUnavailable):
    """Graph is limiting requests (429); waiting and trying again works."""


@singleton
class MicrosoftGraphSites:
    def resolve_site_id(self, token: str, site_url: str) -> str:
        """Graph's id for the site at a normalised site URL. Not found names the URL, not Graph's path."""
        try:
            payload = self._call("GET", f"/sites/{site_graph_path(site_url)}", token)
        except SiteNotFound, SiteChangeRejected:
            # A lookup Graph rejects is an address it can't use.
            raise SiteNotFound(site_url) from None
        site_id = payload.get("id") if isinstance(payload, dict) else None
        if not site_id:
            raise SitesUnavailable("site response without an id")
        return str(site_id)

    def search_sites(self, token: str, query: str) -> list[SiteSummary]:
        """Sites the signed-in account can see whose details match ``query``."""
        payload = self._call("GET", f"/sites?search={urllib.parse.quote(query, safe='')}", token)
        entries = payload.get("value") if isinstance(payload, dict) else None
        if not isinstance(entries, list):
            raise SitesUnavailable("search response without a value list")
        return [_site_summary(entry) for entry in entries if isinstance(entry, dict) and entry.get("id")]

    def get_site(self, token: str, site_id: str) -> SiteSummary:
        """The site with Graph id ``site_id``. Not found names that id, not Graph's path."""
        try:
            payload = self._call("GET", f"/sites/{site_id}", token)
        except SiteNotFound, SiteChangeRejected:
            raise SiteNotFound(site_id) from None
        if not isinstance(payload, dict) or not payload.get("id"):
            raise SitesUnavailable("site response without an id")
        return _site_summary(payload)

    def ensure_folder(self, token: str, *, site_id: str, name: str) -> FolderRef:
        """The folder ``name`` at the root of the site's default library, created when missing.
        One created by someone else in between is reused rather than reported as a conflict."""
        path = f"/sites/{site_id}/drive/root:/{urllib.parse.quote(name, safe='')}"
        try:
            return _folder_ref(self._call("GET", path, token))
        except SiteNotFound:
            pass
        body = {"name": name, "folder": {}, "@microsoft.graph.conflictBehavior": _FOLDER_CONFLICT_BEHAVIOR}
        try:
            return _folder_ref(self._call("POST", f"/sites/{site_id}/drive/root/children", token, body))
        except SiteChangeRejected:
            return _folder_ref(self._call("GET", path, token))

    def grant_site(self, token: str, *, site_id: str, app_id: str, display_name: str, role: str) -> str:
        """Grant the app ``role`` (``read`` or ``write``) on the site; returns the grant's id."""
        body = {
            "roles": [role],
            "grantedToIdentities": [{"application": {"id": app_id, "displayName": display_name}}],
        }
        payload = self._call("POST", f"/sites/{site_id}/permissions", token, body)
        permission_id = payload.get("id") if isinstance(payload, dict) else None
        if not permission_id:
            raise SitesUnavailable("permission response without an id")
        return str(permission_id)

    def update_site_role(self, token: str, *, site_id: str, permission_id: str, role: str) -> None:
        """Change an existing grant's role in place, so access never lapses in between."""
        self._call("PATCH", f"/sites/{site_id}/permissions/{permission_id}", token, {"roles": [role]})

    def revoke_site(self, token: str, *, site_id: str, permission_id: str) -> None:
        """Remove a grant. One already gone, or a site since deleted, is not an error."""
        try:
            self._call("DELETE", f"/sites/{site_id}/permissions/{permission_id}", token)
        except SiteNotFound:
            pass

    @staticmethod
    def _call(method: str, path: str, token: str, body: dict | None = None) -> object:
        try:
            response = httpx.request(
                method,
                f"{_GRAPH}{path}",
                headers={"Authorization": f"Bearer {token}"},
                json=body,
                timeout=_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            raise SitesUnavailable(type(exc).__name__) from exc
        if response.status_code == 404:
            raise SiteNotFound(path)
        if response.status_code in (401, 403):
            raise SiteAccessRefused(f"HTTP {response.status_code}")
        if response.status_code == 429:
            raise SitesThrottled("HTTP 429")
        if response.status_code in (400, 409):
            raise SiteChangeRejected(f"HTTP {response.status_code}")
        if response.status_code >= 300:
            raise SitesUnavailable(f"HTTP {response.status_code}")
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise SitesUnavailable(f"HTTP {response.status_code} without a JSON body") from exc


def _site_summary(payload: dict) -> SiteSummary:
    return SiteSummary(
        id=str(payload["id"]),
        name=str(payload.get("displayName") or payload.get("name") or ""),
        web_url=str(payload.get("webUrl") or ""),
    )


def _folder_ref(payload: object) -> FolderRef:
    item_id = payload.get("id") if isinstance(payload, dict) else None
    web_url = payload.get("webUrl") if isinstance(payload, dict) else None
    if not item_id or not web_url:
        raise SitesUnavailable("folder response without an id or link")
    return FolderRef(item_id=str(item_id), web_url=str(web_url))

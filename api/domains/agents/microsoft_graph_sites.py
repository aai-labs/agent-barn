"""Microsoft Graph calls that grant and revoke an app's access to one SharePoint site.

Under ``Sites.Selected`` an app reaches nothing until each site is granted to it, and the grant
is made with a token that can manage the site's permissions — here the administrator's, from the
selected-sites sign-in. Request shapes follow Graph's site permission API.
"""

import httpx
from injector import singleton

from api.domains.agents.sharepoint_sites import site_graph_path

_GRAPH = "https://graph.microsoft.com/v1.0"
_TIMEOUT_SECONDS = 30


class SiteNotFound(Exception):
    """Graph knows no site at that URL, or the signed-in account can't see it."""


class SiteAccessRefused(Exception):
    """Graph refused to manage the site's permissions: the account is not an administrator."""


class SitesUnavailable(Exception):
    """Graph could not be reached, or answered with something unexpected."""


@singleton
class MicrosoftGraphSites:
    def resolve_site_id(self, token: str, site_url: str) -> str:
        """Graph's id for the site at a normalised site URL."""
        payload = self._call("GET", f"/sites/{site_graph_path(site_url)}", token)
        site_id = payload.get("id") if isinstance(payload, dict) else None
        if not site_id:
            raise SitesUnavailable("site response without an id")
        return str(site_id)

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
        if response.status_code >= 300:
            raise SitesUnavailable(f"HTTP {response.status_code}")
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise SitesUnavailable(f"HTTP {response.status_code} without a JSON body") from exc

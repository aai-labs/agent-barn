"""Microsoft Graph scope derivation for the sharepoint provider.

Parallel to ``google_workspace_scopes`` but much smaller: SharePoint is a single
service, so the only axis is read-only vs read-write. The scopes are delegated: the
agent reaches what the person who signed in can open, no more.

Two Microsoft-specific quirks drive the shape here:

1. The token response's ``scope`` lists **resource** scopes only. ``offline_access``,
   ``openid``, ``profile`` and ``email`` are requested but are not echoed back, so
   validating granted scopes against them would fail for every healthy credential.
   The presence of a refresh token is the real evidence ``offline_access`` was granted.
2. Microsoft is not consistent about returning resource-qualified scope names — the
   same permission may come back as ``https://graph.microsoft.com/Sites.Read.All`` or
   bare ``Sites.Read.All``. Comparisons therefore happen on the bare permission name.
"""

GRAPH_SCOPE_PREFIX = "https://graph.microsoft.com/"

READ_PERMISSION = "Sites.Read.All"
WRITE_PERMISSION = "Sites.ReadWrite.All"

# Selected-sites mode. An administrator signs in with SITE_GRANT_PERMISSION, which can manage
# a site's permissions, to grant the Teams app SELECTED_SITES_PERMISSION site by site. The
# Teams app then gets app-only tokens for APP_ONLY_SCOPE, which carry the application
# permissions an administrator consented to on it.
SITE_GRANT_PERMISSION = "Sites.FullControl.All"
SELECTED_SITES_PERMISSION = "Sites.Selected"
APP_ONLY_SCOPE = f"{GRAPH_SCOPE_PREFIX}.default"

# Requested alongside the resource scope. Not echoed back in the token response, so these
# are never part of a granted-scope comparison.
OFFLINE_ACCESS_SCOPE = "offline_access"
IDENTITY_SCOPES: tuple[str, ...] = ("openid", "profile", "email")


def sharepoint_permission(read_only: bool) -> str:
    """The single Graph permission a SharePoint credential needs at this access level."""
    return READ_PERMISSION if read_only else WRITE_PERMISSION


def sharepoint_scopes(read_only: bool) -> tuple[str, ...]:
    """Scopes to request at authorize time, sorted for a deterministic authorize URL."""
    requested = {
        f"{GRAPH_SCOPE_PREFIX}{sharepoint_permission(read_only)}",
        OFFLINE_ACCESS_SCOPE,
        *IDENTITY_SCOPES,
    }
    return tuple(sorted(requested))


def site_grant_scopes() -> tuple[str, ...]:
    """Scopes for the administrator's grant sign-in, sorted for a deterministic authorize URL.

    No ``offline_access``: Microsoft then issues no refresh token, so the sign-in grants the
    sites and nothing able to manage them outlives it.
    """
    return tuple(sorted({f"{GRAPH_SCOPE_PREFIX}{SITE_GRANT_PERMISSION}", *IDENTITY_SCOPES}))


def granted_permissions(scopes: list[str]) -> set[str]:
    """Bare permission names from granted scopes, resource-qualified or not.

    ``Sites.ReadWrite.All`` implies ``Sites.Read.All``: being granted more than was asked
    for is not a reason to reject a credential.
    """
    granted = {scope.rsplit("/", 1)[-1] for scope in scopes if scope}
    if WRITE_PERMISSION in granted:
        granted.add(READ_PERMISSION)
    return granted


def missing_sharepoint_permissions(scopes: list[str], read_only: bool) -> list[str]:
    """Permissions the credential needs but was not granted. Empty means satisfied."""
    if not scopes:
        return []
    required = {sharepoint_permission(read_only)}
    return sorted(required - granted_permissions(scopes))

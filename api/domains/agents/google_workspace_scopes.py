from collections.abc import Iterable

GOOGLE_SCOPE_PREFIX = "https://www.googleapis.com/auth/"

# Per-service (full, read-only) scope sets mirror gog v0.37.0's own derivation
# (internal/googleauth/service.go: serviceInfoByService plus
# scopesForServiceWithOptions). The OAuth flow and stored-content validator both use
# this mapping so a credential cannot advertise services its consent does not cover.
WORKSPACE_SERVICE_SCOPES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "gmail": (
        (
            f"{GOOGLE_SCOPE_PREFIX}gmail.modify",
            f"{GOOGLE_SCOPE_PREFIX}gmail.settings.basic",
            f"{GOOGLE_SCOPE_PREFIX}gmail.settings.sharing",
        ),
        (f"{GOOGLE_SCOPE_PREFIX}gmail.readonly",),
    ),
    "calendar": (
        (f"{GOOGLE_SCOPE_PREFIX}calendar",),
        (f"{GOOGLE_SCOPE_PREFIX}calendar.readonly",),
    ),
    "drive": (
        (f"{GOOGLE_SCOPE_PREFIX}drive",),
        (f"{GOOGLE_SCOPE_PREFIX}drive.readonly",),
    ),
    # gog's sheets service pulls in Drive too (it exports/discovers through Drive).
    "sheets": (
        (f"{GOOGLE_SCOPE_PREFIX}drive", f"{GOOGLE_SCOPE_PREFIX}spreadsheets"),
        (f"{GOOGLE_SCOPE_PREFIX}drive.readonly", f"{GOOGLE_SCOPE_PREFIX}spreadsheets.readonly"),
    ),
}


def required_service_scopes(services: Iterable[str], read_only: bool) -> set[str]:
    """Return the service scopes required by a selected access level."""
    required: set[str] = set()
    for service in services:
        full, readonly = WORKSPACE_SERVICE_SCOPES[service]
        required.update(readonly if read_only else full)
    return required

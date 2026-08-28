import io
import json
import re
import uuid
import zipfile
from pathlib import Path

_ASSETS = Path(__file__).parent.parent.parent / "domains" / "communications" / "assets"
_COLOR_ICON = _ASSETS / "teams-color.png"
_OUTLINE_ICON = _ASSETS / "teams-outline.png"
_SCHEMA_URL = "https://developer.microsoft.com/json-schemas/teams/v1.17/MicrosoftTeams.schema.json"
_MANIFEST_VERSION = "1.17"
_PACKAGE_VERSION = "1.0.0"
_MANIFEST_NAMESPACE = uuid.UUID("6ba7b812-9dad-11d1-80b4-00c04fd430c8")
_SHORT_NAME_MAX = 30
_SHORT_DESCRIPTION_MAX = 80
_FULL_DESCRIPTION_MAX = 4000
_SLUG_PATTERN = re.compile(r"[^a-z0-9]+")


class TeamsManifestError(ValueError):
    """Raised when a Connection cannot produce a valid Teams app package."""


def build_app_package(
    *,
    connection_id: uuid.UUID,
    app_id: str,
    display_name: str,
    publisher_name: str,
    website_url: str,
    privacy_url: str,
    terms_url: str,
) -> tuple[str, bytes]:
    """Build a sideloadable Teams app package for one Connection."""
    if not app_id.strip():
        raise TeamsManifestError("The connection has no Microsoft App ID to build a package from")
    for label, url in (("website", website_url), ("privacy policy", privacy_url), ("terms of use", terms_url)):
        if not url.startswith("https://"):
            raise TeamsManifestError(f"The configured Teams {label} URL must be an https URL")

    short_name = display_name.strip()[:_SHORT_NAME_MAX] or "Agent"
    manifest = {
        "$schema": _SCHEMA_URL,
        "manifestVersion": _MANIFEST_VERSION,
        "version": _PACKAGE_VERSION,
        # Stable per Connection so re-downloading updates the existing app
        # rather than registering a second one in the tenant catalogue.
        "id": str(uuid.uuid5(_MANIFEST_NAMESPACE, str(connection_id))),
        "developer": {
            "name": publisher_name,
            "websiteUrl": website_url,
            "privacyUrl": privacy_url,
            "termsOfUseUrl": terms_url,
        },
        "name": {"short": short_name, "full": f"{short_name} on {publisher_name}"[:100]},
        "description": {
            "short": f"{short_name}, an AI teammate."[:_SHORT_DESCRIPTION_MAX],
            "full": (
                f"{short_name} is an AI teammate provided through {publisher_name}. "
                "Mention it in a channel or message it directly to get help with your work."
            )[:_FULL_DESCRIPTION_MAX],
        },
        "icons": {"color": "color.png", "outline": "outline.png"},
        "accentColor": "#5059C9",
        "bots": [
            {
                "botId": app_id,
                "scopes": ["personal", "team", "groupChat"],
                "supportsFiles": False,
                "isNotificationOnly": False,
            }
        ],
        "permissions": ["identity", "messageTeamMembers"],
        "validDomains": [],
    }

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, indent=2))
        archive.writestr("color.png", _COLOR_ICON.read_bytes())
        archive.writestr("outline.png", _OUTLINE_ICON.read_bytes())
    return f"{_slug(short_name)}-teams-app.zip", buffer.getvalue()


def _slug(value: str) -> str:
    return _SLUG_PATTERN.sub("-", value.lower()).strip("-") or "agent"

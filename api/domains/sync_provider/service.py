import html
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import jwt
from fastapi import HTTPException, status
from fastapi.responses import HTMLResponse
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.microsoft_identity import pkce_pair
from api.domains.agents.sharepoint_service import SharePointService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.service import JWT_ENCODING_ALGORITHM
from api.domains.file_sync.service import FileSyncBusy, FileSyncFolderRemoval
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import PermissionPolicy
from api.domains.sync_provider.models import (
    FOLDER_NAME,
    SyncLocationRead,
    SyncProviderCapability,
    SyncProviderConnection,
    SyncProviderConnectionRead,
    SyncProviderRead,
    SyncProviderStatus,
)
from api.domains.sync_provider.plugins.base import (
    LocationAccessRefused,
    LocationNotFound,
    ProviderThrottled,
    ProviderUnavailable,
    ProvisioningFailed,
    SignInIncomplete,
    SignInRefused,
    SyncLocation,
    SyncLocationGuard,
    SyncProviderError,
    SyncProviderPlugin,
)
from api.domains.sync_provider.plugins.registry import SyncProviderPluginRegistry
from api.domains.sync_provider.repository import SyncProviderConnectionConflict, SyncProviderRepository
from api.infrastructure.crypto import decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

MESSAGE_TYPE = "sync-provider-oauth"

_STATE_TYPE = "sync_provider_state"
_STATE_TTL_SECONDS = 600
_FAILURE_STATUS: dict[type[SyncProviderError], int] = {
    SignInRefused: status.HTTP_400_BAD_REQUEST,
    SignInIncomplete: status.HTTP_400_BAD_REQUEST,
    LocationNotFound: status.HTTP_400_BAD_REQUEST,
    LocationAccessRefused: status.HTTP_403_FORBIDDEN,
    ProviderThrottled: status.HTTP_503_SERVICE_UNAVAILABLE,
    ProviderUnavailable: status.HTTP_502_BAD_GATEWAY,
    ProvisioningFailed: status.HTTP_502_BAD_GATEWAY,
}
_LOCATION_GUARD_MESSAGES: dict[SyncLocationGuard, str] = {
    SyncLocationGuard.SHAREPOINT_AGENT_SITES: (
        "An Agent in this Organization already has SharePoint access to this site. Remove it there, or pick "
        "another site."
    ),
}

_READ_DENIED = "You don't have permission to view sync providers for this organization."
_MANAGE_DENIED = "You don't have permission to manage sync providers for this organization."
_SIGN_IN_FAILED = "Sign-in failed. You can close this window."
_SIGN_IN_COMPLETE = "Sign-in complete. You can close this window."
_SIGN_IN_EXPIRED = "This sign-in has expired. Please try again."
_SIGN_IN_INCOMPLETE = "The sign-in didn't complete. Please try again."
_SIGN_IN_NOT_YOURS = "This sign-in has expired or was started by someone else. Please connect again."
_SEARCH_TERM_NEEDED = "Type part of the location's name to search."
_NO_LOCATION_PICKER = "This sync provider has no locations to choose from."
_FILE_SYNC_BUSY = "File sync is busy with this connection. Try again in a moment."

SyncProviderPurpose = Literal["connect", "disconnect"]


@dataclass(frozen=True)
class SyncProviderState:
    organization_id: UUID
    # The person who started the flow; only they can complete it.
    user_id: UUID
    provider_key: str
    purpose: SyncProviderPurpose
    code_verifier: str


def redirect_uri(config: Config, provider_key: str) -> str:
    return f"{config.web_app_url}/api/v1/integrations/sync-provider/{provider_key}/callback"


def encode_state(config: Config, state: SyncProviderState, *, ttl_seconds: int = _STATE_TTL_SECONDS) -> str:
    payload = {
        "typ": _STATE_TYPE,
        "organization_id": str(state.organization_id),
        "user_id": str(state.user_id),
        "provider_key": state.provider_key,
        "purpose": state.purpose,
        # The state passes through the provider and the browser; the verifier proves the code
        # redemption is ours, so it travels encrypted.
        "verifier": encrypt_token(state.code_verifier, config.agent_token_encryption_key),
        "exp": int(time.time()) + ttl_seconds,
    }
    return jwt.encode(payload, config.secret_signing_key, algorithm=JWT_ENCODING_ALGORITHM)


def decode_state(token: str, config: Config) -> SyncProviderState | None:
    """The state this server signed for a sync provider, or None if forged, expired or another flow's."""
    try:
        payload = jwt.decode(token, config.secret_signing_key, algorithms=[JWT_ENCODING_ALGORITHM])
        if payload.get("typ") != _STATE_TYPE or payload.get("purpose") not in ("connect", "disconnect"):
            return None
        return SyncProviderState(
            organization_id=UUID(payload["organization_id"]),
            user_id=UUID(payload["user_id"]),
            provider_key=payload["provider_key"],
            purpose=payload["purpose"],
            code_verifier=decrypt_token(payload["verifier"], config.agent_token_encryption_key),
        )
    except Exception:
        return None


def callback_html(
    config: Config,
    display_name: str,
    *,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    approved: bool = False,
) -> HTMLResponse:
    """A page that posts the result to the window that opened the popup, then closes. An approver
    opening a forwarded link lands here too, so it reads sensibly on its own."""
    if error is not None:
        message: dict = {"type": MESSAGE_TYPE, "error": error}
        blurb = _SIGN_IN_FAILED
    elif approved:
        message = {"type": MESSAGE_TYPE, "adminConsent": True}
        blurb = (
            f"Agent Barn is approved for your organization. The person connecting can now connect {display_name}. "
            "You can close this window."
        )
    else:
        message = {"type": MESSAGE_TYPE, "code": code, "state": state}
        blurb = _SIGN_IN_COMPLETE

    # Escaping "<", ">" and "&" keeps the JSON inert inside the script block, so an error
    # from the unauthenticated query string cannot end it early.
    def _script_safe(value: object) -> str:
        return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")

    page = f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>{html.escape(display_name)} sign-in</title></head>
<body style="font-family: system-ui, -apple-system, sans-serif; padding: 24px; color: #333;">
<p>{blurb}</p>
<script>
  (function () {{
    var msg = {_script_safe(message)};
    if (window.opener) {{
      window.opener.postMessage(msg, {_script_safe(config.web_app_url)});
      window.close();
    }}
  }})();
</script>
</body>
</html>"""
    return HTMLResponse(content=page)


@inject
@singleton
@dataclass
class SyncProviderService:
    repository: SyncProviderRepository
    permission_policy: PermissionPolicy
    plugins: SyncProviderPluginRegistry
    sharepoint: SharePointService
    file_sync_folders: FileSyncFolderRemoval
    config: Config

    def providers(self, organization_id: UUID, context: CurrentUserContext) -> list[SyncProviderRead]:
        """Every provider shipped with Agent Barn, with its connection. One not set up on this server is
        listed as unavailable, with how to enable it."""
        self.permission_policy.require(context, organization_id, PermissionKey.ORGANIZATION_READ, detail=_READ_DENIED)
        return [self._read(organization_id, plugin) for plugin in self.plugins.all()]

    def authorize_url(
        self, organization_id: UUID, provider_key: str, purpose: SyncProviderPurpose, context: CurrentUserContext
    ) -> str:
        self._require_manage(organization_id, context)
        plugin = self._offered(provider_key)
        connection = self._fresh_open(organization_id, provider_key)
        active = connection is not None and connection.status == SyncProviderStatus.ACTIVE
        if purpose == "connect":
            if active:
                raise HTTPException(status.HTTP_409_CONFLICT, f"{plugin.display_name} is already connected.")
            self._refuse_while_blocked(organization_id, provider_key)
        if purpose == "disconnect" and not active:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{plugin.display_name} isn't connected.")
        verifier, challenge = pkce_pair()
        state = SyncProviderState(
            organization_id=organization_id,
            user_id=context.user.id,
            provider_key=provider_key,
            purpose=purpose,
            code_verifier=verifier,
        )
        return plugin.authorize_url(
            redirect_uri=redirect_uri(self.config, provider_key),
            state=encode_state(self.config, state),
            code_challenge=challenge,
        )

    def callback_page(self, provider_key: str, query: Mapping[str, str]) -> HTMLResponse:
        plugin = self._registered(provider_key)
        # A refused approval may also look like an approval, so the error is read first.
        error = query.get("error")
        if error:
            message = plugin.callback_error_message(error, query.get("error_description") or "")
            return callback_html(self.config, plugin.display_name, error=message)
        if plugin.is_approval_callback(query):
            return callback_html(self.config, plugin.display_name, approved=True)
        state = query.get("state")
        decoded = decode_state(state, self.config) if state else None
        if decoded is None or decoded.provider_key != provider_key:
            return callback_html(self.config, plugin.display_name, error=_SIGN_IN_EXPIRED)
        code = query.get("code")
        if not code:
            return callback_html(self.config, plugin.display_name, error=_SIGN_IN_INCOMPLETE)
        return callback_html(self.config, plugin.display_name, code=code, state=state)

    def complete_sign_in(
        self, organization_id: UUID, provider_key: str, code: str, state_token: str, context: CurrentUserContext
    ) -> SyncProviderRead:
        """Redeem the code and hold the delegated token on a pending connection until a location is
        chosen. A provider without a location picker is provisioned straight away."""
        self._require_manage(organization_id, context)
        plugin = self._offered(provider_key)
        state = self._verified_state(state_token, provider_key, "connect", organization_id, context)
        self._refuse_while_blocked(organization_id, provider_key)
        signed_in = self._call(lambda: plugin.complete_sign_in(**self._redemption(code, state)))
        self.repository.delete_expired_pending(organization_id)
        try:
            connection = self.repository.create_pending(
                organization_id,
                provider_key,
                schema_version=plugin.schema_version,
                account_id=signed_in.account_id,
                connected_by_user_id=context.user.id,
                credentials_encrypted=encrypt_token(signed_in.access_token, self.config.agent_token_encryption_key),
                pending_expires_at=datetime.now(UTC) + timedelta(seconds=signed_in.expires_in),
            )
        except SyncProviderConnectionConflict as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{plugin.display_name} is already connected.") from exc
        if SyncProviderCapability.LOCATION_PICKER not in plugin.capabilities:
            try:
                self._provision(plugin, connection, signed_in.access_token, None)
            except HTTPException:
                self.repository.delete_pending(organization_id, provider_key)
                raise
        return self._read(organization_id, plugin)

    def locations(
        self, organization_id: UUID, provider_key: str, search: str, context: CurrentUserContext
    ) -> list[SyncLocationRead]:
        """Locations the signed-in person can see that match ``search``."""
        self._require_manage(organization_id, context)
        plugin = self._picker(provider_key)
        query = search.strip()
        if not query:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, _SEARCH_TERM_NEEDED)
        _, token = self._signed_in(organization_id, plugin)
        found = self._call(lambda: plugin.search_locations(token, query))
        return [SyncLocationRead(id=location.id, name=location.name, web_url=location.web_url) for location in found]

    def choose_location(
        self, organization_id: UUID, provider_key: str, location_id: str, context: CurrentUserContext
    ) -> SyncProviderRead:
        """Read the chosen location from the provider, run its guard, provision, and activate."""
        self._require_manage(organization_id, context)
        plugin = self._picker(provider_key)
        connection, token = self._signed_in(organization_id, plugin)
        location = self._call(lambda: plugin.resolve_location(token, location_id))
        self._guard(plugin, organization_id, location)
        self._provision(plugin, connection, token, location)
        return self._read(organization_id, plugin)

    def disconnect(
        self, organization_id: UUID, provider_key: str, code: str, state_token: str, context: CurrentUserContext
    ) -> SyncProviderRead:
        """Delete the Agent folders with Agent Barn's own access, take that access back with the person's
        fresh sign-in, then close the connection. The root folder is left in place. The Sync Engine is held
        off the connection throughout, and rebuilds the folders if any step fails."""
        self._require_manage(organization_id, context)
        plugin = self._offered(provider_key)
        state = self._verified_state(state_token, provider_key, "disconnect", organization_id, context)
        connection = self.repository.get_open(organization_id, provider_key)
        if connection is None or connection.status != SyncProviderStatus.ACTIVE:
            raise HTTPException(status.HTTP_409_CONFLICT, f"{plugin.display_name} isn't connected.")
        signed_in = self._call(lambda: plugin.complete_sign_in(**self._redemption(code, state)))
        self._call(lambda: plugin.require_same_account(connection.account_id, signed_in))
        try:
            with self.file_sync_folders.holding(connection.id):
                self._call(lambda: self.file_sync_folders.remove_agent_folders(connection, plugin))
                self._call(
                    lambda: plugin.revoke(
                        signed_in.access_token,
                        location_id=connection.location_id,
                        provider_data=connection.provider_data,
                    )
                )
                self.repository.mark_disconnected(connection.id)
        except FileSyncBusy as exc:
            raise HTTPException(status.HTTP_409_CONFLICT, _FILE_SYNC_BUSY) from exc
        return self._read(organization_id, plugin)

    def abandon_pending(self, organization_id: UUID, provider_key: str, context: CurrentUserContext) -> None:
        """Forget an unfinished connection. An active connection is left alone; disconnect it instead."""
        self._require_manage(organization_id, context)
        self._offered(provider_key)
        self.repository.delete_pending(organization_id, provider_key)

    def _blocking_connection(self, organization_id: UUID, provider_key: str) -> SyncProviderConnection | None:
        """One connection at a time: another provider's live connection, which stops this one from
        connecting. Allowing several providers means removing this and indexing
        (organization_id, provider_key) instead of organization_id."""
        for connection in self.repository.list_open(organization_id):
            if connection.provider_key != provider_key and not _expired_pending(connection):
                return connection
        return None

    def _blocked_reason(self, organization_id: UUID, provider_key: str) -> str | None:
        blocking = self._blocking_connection(organization_id, provider_key)
        if blocking is None:
            return None
        name = self._display_name(blocking.provider_key)
        if blocking.status == SyncProviderStatus.PENDING:
            return f"Finish connecting {name}, or start over, first."
        return f"Disconnect {name} first."

    def _refuse_while_blocked(self, organization_id: UUID, provider_key: str) -> None:
        reason = self._blocked_reason(organization_id, provider_key)
        if reason is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, reason)

    def _read(self, organization_id: UUID, plugin: SyncProviderPlugin) -> SyncProviderRead:
        connection = self._fresh_open(organization_id, plugin.key)
        available = plugin.is_offered()
        approval_url = (
            plugin.approval_url(redirect_uri=redirect_uri(self.config, plugin.key))
            if available and SyncProviderCapability.ADMIN_APPROVAL in plugin.capabilities
            else None
        )
        blocked_reason = self._blocked_reason(organization_id, plugin.key) if available else None
        return SyncProviderRead(
            **plugin.descriptor.model_dump(),
            approval_url=approval_url,
            connection=None
            if connection is None
            else SyncProviderConnectionRead(
                status=connection.status,
                location_name=connection.location_name,
                location_url=connection.location_url,
                folder_web_url=connection.folder_web_url,
                connected_at=connection.connected_at,
            ),
            can_connect=available and connection is None and blocked_reason is None,
            blocked_reason=blocked_reason,
        )

    def _provision(
        self,
        plugin: SyncProviderPlugin,
        connection: SyncProviderConnection,
        token: str,
        location: SyncLocation | None,
    ) -> None:
        provisioned = self._call(
            lambda: plugin.provision(
                token, account_id=connection.account_id, location=location, folder_name=FOLDER_NAME
            )
        )
        activated = self.repository.activate(
            connection.id,
            location_id=location.id if location else None,
            location_name=location.name if location else None,
            location_url=location.web_url if location else None,
            folder_id=provisioned.folder.id,
            folder_web_url=provisioned.folder.web_url,
            provider_data=provisioned.provider_data,
        )
        if activated is None:
            plugin.undo_provision(
                token, location_id=location.id if location else None, provider_data=provisioned.provider_data
            )
            raise HTTPException(status.HTTP_409_CONFLICT, self._sign_in_needed(plugin))

    def _guard(self, plugin: SyncProviderPlugin, organization_id: UUID, location: SyncLocation) -> None:
        if plugin.location_guard is None:
            return
        guards: dict[SyncLocationGuard, Callable[[UUID], set[str]]] = {
            SyncLocationGuard.SHAREPOINT_AGENT_SITES: self.sharepoint.organization_site_ids,
        }
        if location.id.lower() in guards[plugin.location_guard](organization_id):
            raise HTTPException(status.HTTP_409_CONFLICT, _LOCATION_GUARD_MESSAGES[plugin.location_guard])

    def _verified_state(
        self,
        state_token: str,
        provider_key: str,
        purpose: SyncProviderPurpose,
        organization_id: UUID,
        context: CurrentUserContext,
    ) -> SyncProviderState:
        """The signed state, only if it was issued to this caller, for this Organization, provider and purpose."""
        state = decode_state(state_token, self.config)
        if (
            state is None
            or state.provider_key != provider_key
            or state.purpose != purpose
            or state.organization_id != organization_id
            or state.user_id != context.user.id
        ):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, _SIGN_IN_NOT_YOURS)
        return state

    def _redemption(self, code: str, state: SyncProviderState) -> dict[str, str]:
        return {
            "code": code,
            "code_verifier": state.code_verifier,
            "redirect_uri": redirect_uri(self.config, state.provider_key),
        }

    def _signed_in(self, organization_id: UUID, plugin: SyncProviderPlugin) -> tuple[SyncProviderConnection, str]:
        """The pending connection and its delegated token, while the sign-in is fresh."""
        connection = self.repository.get_open(organization_id, plugin.key)
        if (
            connection is None
            or connection.status != SyncProviderStatus.PENDING
            or connection.credentials_encrypted is None
            or _expired_pending(connection)
        ):
            raise HTTPException(status.HTTP_409_CONFLICT, self._sign_in_needed(plugin))
        return connection, decrypt_token(connection.credentials_encrypted, self.config.agent_token_encryption_key)

    def _fresh_open(self, organization_id: UUID, provider_key: str) -> SyncProviderConnection | None:
        connection = self.repository.get_open(organization_id, provider_key)
        return None if connection is None or _expired_pending(connection) else connection

    def _offered(self, provider_key: str) -> SyncProviderPlugin:
        plugin = self._registered(provider_key)
        if not plugin.is_offered():
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{plugin.display_name} isn't available on this server.")
        return plugin

    def _picker(self, provider_key: str) -> SyncProviderPlugin:
        plugin = self._offered(provider_key)
        if SyncProviderCapability.LOCATION_PICKER not in plugin.capabilities:
            raise HTTPException(status.HTTP_404_NOT_FOUND, _NO_LOCATION_PICKER)
        return plugin

    def _registered(self, provider_key: str) -> SyncProviderPlugin:
        try:
            return self.plugins.require(provider_key)
        except KeyError as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown sync provider.") from exc

    def _display_name(self, provider_key: str) -> str:
        try:
            return self.plugins.require(provider_key).display_name
        except KeyError:
            return provider_key

    def _require_manage(self, organization_id: UUID, context: CurrentUserContext) -> None:
        self.permission_policy.require(
            context, organization_id, PermissionKey.ORGANIZATION_UPDATE, detail=_MANAGE_DENIED
        )

    @staticmethod
    def _sign_in_needed(plugin: SyncProviderPlugin) -> str:
        return f"Your {plugin.display_name} sign-in has expired. Start connecting {plugin.display_name} again."

    @staticmethod
    def _call[T](action: Callable[[], T]) -> T:
        try:
            return action()
        except SyncProviderError as exc:
            code = next(
                (code for failure, code in _FAILURE_STATUS.items() if isinstance(exc, failure)),
                status.HTTP_502_BAD_GATEWAY,
            )
            raise HTTPException(code, exc.message) from exc


def _expired_pending(connection: SyncProviderConnection) -> bool:
    return (
        connection.status == SyncProviderStatus.PENDING
        and connection.pending_expires_at is not None
        and connection.pending_expires_at <= datetime.now(UTC)
    )

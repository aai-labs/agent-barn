"""Durable delegated Graph refresh and one-time imports from a stopped direct runtime."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
from injector import inject, singleton
from pydantic import BaseModel, Field

from api.core.config import Config
from api.domains.agents.microsoft_graph_scopes import (
    GRAPH_SCOPE_PREFIX,
    missing_sharepoint_permissions,
    sharepoint_permission,
)
from api.domains.agents.microsoft_identity import claims_from_id_token
from api.domains.agents.models import (
    AgentSecret,
    SecretProvider,
    SharePointContent,
    decrypt_content,
    encrypt_content,
)
from api.domains.credential_gateway.aai_store import sharepoint_refresh_token
from api.domains.credential_gateway.sharepoint_repository import (
    SharePointBrokerRepository,
    SharePointHandoffRefused,
    SharePointTransaction,
)
from api.domains.integrations.plugins.base import MintedToken, UpstreamAuthenticationError


class SharePointReconnectRequired(Exception):
    """The delegated grant or its handoff must be replaced by a fresh sign-in."""


class SharePointHandoff(BaseModel):
    store: str = Field(default="", max_length=262144, repr=False)
    key: str = Field(default="", max_length=128, repr=False)
    marker: str = Field(default="", max_length=128, repr=False)


@inject
@singleton
@dataclass
class SharePointBroker:
    repository: SharePointBrokerRepository
    config: Config

    @contextmanager
    def _grant(
        self, agent_id: UUID, organization_id: UUID, generation: UUID | None, *, handoff: bool = False
    ) -> Iterator[SharePointTransaction]:
        try:
            with self.repository.locked(agent_id, organization_id, generation, handoff=handoff) as transaction:
                yield transaction
        except SharePointReconnectRequired:
            self.repository.record_reconnect_required(agent_id, generation)
            raise

    def _content(self, secret: AgentSecret) -> SharePointContent:
        content = decrypt_content(
            SecretProvider.SHAREPOINT, secret.content or "", self.config.agent_token_encryption_key
        )
        if not isinstance(content, SharePointContent):
            raise SharePointHandoffRefused()
        return content

    def _refresh(self, content: SharePointContent, *, verify_identity: bool = False) -> MintedToken:
        # Tenant identifiers are URL-escaped just as in the interactive sign-in flow.
        from urllib.parse import quote

        try:
            response = httpx.post(
                f"https://login.microsoftonline.com/{quote(content.tenant_id, safe='')}/oauth2/v2.0/token",
                data={
                    "grant_type": "refresh_token",
                    "client_id": content.client_id,
                    "refresh_token": content.refresh_token,
                    "scope": f"{GRAPH_SCOPE_PREFIX}{sharepoint_permission(content.read_only)} offline_access"
                    + (" openid profile email" if verify_identity else ""),
                },
                timeout=30,
            )
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise UpstreamAuthenticationError("SharePoint token service unavailable") from exc
        if response.status_code != 200:
            if isinstance(payload, dict) and payload.get("error") in {"invalid_grant", "interaction_required"}:
                raise SharePointReconnectRequired()
            raise UpstreamAuthenticationError("SharePoint token service refused refresh")
        try:
            token = payload["access_token"]
            expires = int(payload["expires_in"])
            scopes = str(payload.get("scope", "")).split()
            rotated = payload.get("refresh_token", content.refresh_token)
            if (
                not isinstance(token, str)
                or not token
                or expires <= 300
                or not scopes
                or missing_sharepoint_permissions(scopes, content.read_only)
                or not isinstance(rotated, str)
                or not rotated
            ):
                raise ValueError()
        except (KeyError, TypeError, ValueError) as exc:
            raise UpstreamAuthenticationError("Invalid SharePoint token response") from exc
        if verify_identity:
            self._verify_imported_account(content, payload.get("id_token"))
        content.refresh_token = rotated
        content.scopes = scopes
        content.broker_access_token = token
        content.broker_expires_at = time.time() + expires
        return MintedToken(value=token, expires_in=expires, scopes=frozenset(scopes))

    def mint(self, agent_id: UUID, organization_id: UUID, generation: UUID | None) -> MintedToken:
        with self._grant(agent_id, organization_id, generation) as transaction:
            content = self._content(transaction.secret)
            if content.broker_access_token and (content.broker_expires_at or 0) > time.time() + 300:
                return MintedToken(
                    value=content.broker_access_token,
                    expires_in=int((content.broker_expires_at or 0) - time.time()),
                    scopes=frozenset(content.scopes),
                )
            minted = self._refresh(content)
            transaction.save(encrypt_content(content, self.config.agent_token_encryption_key))
            return minted

    def handoff(self, agent_id: UUID, organization_id: UUID, generation: UUID | None, data: SharePointHandoff) -> None:
        with self._grant(agent_id, organization_id, generation, handoff=True) as transaction:
            if transaction.binding.get("handoff_complete"):
                return  # Pod boot retry, never import a second grant.
            content = self._content(transaction.secret)
            expected_marker = content.sign_in_id + (f":{content.store_revision}" if content.store_revision else "")
            if data.marker == expected_marker:
                try:
                    content.refresh_token = sharepoint_refresh_token(data.store, data.key)
                except Exception as exc:
                    raise SharePointReconnectRequired() from exc
            elif data.marker and data.marker.split(":", 1)[0] == content.sign_in_id:
                # Same sign-in but unknown revision: retain the unproven PVC grant.
                raise SharePointReconnectRequired()
            # Stale markers belong to an older sign-in. A newer DB reconnect wins.
            self._refresh(content, verify_identity=data.marker == expected_marker)
            transaction.save(encrypt_content(content, self.config.agent_token_encryption_key), handoff_complete=True)

    def _verify_imported_account(self, content: SharePointContent, id_token: str | None) -> None:
        # Claims come from the authenticated Microsoft token endpoint, just as in
        # interactive sign-in. OIDC was already consented; no new Graph scope is needed.
        account = claims_from_id_token(id_token)
        if (
            not account.get("oid")
            or str(account.get("tid", "")).casefold() != content.tenant_id.casefold()
            or account.get("aud") != content.client_id
        ):
            raise SharePointReconnectRequired()
        if content.subject_id:
            matches = str(account["oid"]).casefold() == content.subject_id.casefold()
        else:
            matches = content.email.casefold() in {
                str(account.get(key) or "").casefold() for key in ("email", "preferred_username")
            }
        if not matches:
            raise SharePointReconnectRequired()
        content.subject_id = str(account["oid"])

    def prepare_direct(self, agent_id: UUID, organization_id: UUID) -> None:
        """After old-pod termination, force the next direct boot to import the latest DB grant."""
        with self.repository.locked(agent_id, organization_id, direct=True) as transaction:
            content = self._content(transaction.secret)
            content.store_revision = str(uuid4())
            content.broker_access_token = None
            content.broker_expires_at = None
            # Fence defensive replays in the same transaction as handing the grant back.
            transaction.save(encrypt_content(content, self.config.agent_token_encryption_key), handoff_complete=False)

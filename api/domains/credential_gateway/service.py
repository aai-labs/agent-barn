"""Gateway Token issuance, revocation, and resolution.

Issuance is driven by each provider's ``EgressMode``: a provider whose credential still
materializes into the pod (``DIRECT``) needs no gateway token, so nothing is issued for
it. Flipping a provider to ``GATEWAY_PROXY`` or ``TOKEN_BROKER`` starts issuance for that
provider with no change here.
"""

import base64
import binascii
import datetime
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.models import SecretContent, SecretProvider, decrypt_content
from api.domains.agents.repository import AgentRepository
from api.domains.credential_gateway.audit import GatewayAuditSink, ResolutionOutcome
from api.domains.credential_gateway.forwarding import (
    UpstreamForwarder,
    UpstreamResponse,
    UpstreamUnreachable,
    sanitize_request_headers,
)
from api.domains.credential_gateway.models import (
    TOKEN_PREFIX,
    GatewayToken,
    GatewayTokenResolution,
    IssuedGatewayToken,
    hash_token,
    issue_token_value,
)
from api.domains.credential_gateway.repository import GatewayTokenRepository
from api.domains.integrations.plugins.base import (
    EgressMode,
    MintedToken,
    OutboundRequest,
    UpstreamAuthenticationError,
)
from api.domains.integrations.plugins.registry import INTEGRATION_PLUGINS
from api.domains.shared_credentials.repository import SharedCredentialRepository


class GatewayTokenRejected(Exception):
    """A presented token is absent, malformed, unknown, or revoked."""

    def __init__(self, outcome: ResolutionOutcome) -> None:
        super().__init__(outcome.value)
        self.outcome = outcome


@inject
@singleton
@dataclass
class CredentialGatewayService:
    repository: GatewayTokenRepository
    audit: GatewayAuditSink
    config: Config
    agent_repository: AgentRepository
    shared_credential_repository: SharedCredentialRepository
    forwarder: UpstreamForwarder

    # --- issuance, called from agent start ---

    def providers_needing_a_token(self, providers: set[SecretProvider]) -> set[SecretProvider]:
        """Narrow an Agent's configured providers to those the gateway currently serves."""
        return {
            provider
            for provider in providers
            if INTEGRATION_PLUGINS.require(provider).egress_mode is not EgressMode.DIRECT
        }

    def issue_for_agent(
        self,
        agent_id: UUID,
        organization_id: UUID,
        providers: set[SecretProvider],
    ) -> list[IssuedGatewayToken]:
        """Issue one token per gateway-served provider, replacing any live ones.

        Called on every agent start, so it is also the rotation path: the previous
        token is revoked in the same operation and the pod receives the new value.
        Returns an empty list when no configured provider is served by the gateway.
        """
        needed = self.providers_needing_a_token(providers)
        # Always revoke the full set first: a provider removed from the Agent since the
        # last start must lose its token even though it is absent from `needed`.
        self.repository.revoke_for_agent(agent_id)

        issued: list[IssuedGatewayToken] = []
        for provider in sorted(needed, key=lambda p: p.value):
            value = issue_token_value()
            self.repository.save(
                GatewayToken(
                    organization_id=organization_id,
                    agent_id=agent_id,
                    provider=provider,
                    token_hash=hash_token(value),
                )
            )
            self.audit.record_lifecycle(
                "issued",
                provider=provider,
                agent_id=agent_id,
                organization_id=organization_id,
            )
            issued.append(IssuedGatewayToken(provider=provider, value=value))
        return issued

    def revoke_for_agent(
        self,
        agent_id: UUID,
        organization_id: UUID,
        providers: set[SecretProvider] | None = None,
    ) -> int:
        """Revoke an Agent's tokens on stop, or a provider's on credential removal."""
        live = self.repository.find_active_for_agent(agent_id)
        targeted = [t for t in live if providers is None or t.provider in providers]
        revoked = self.repository.revoke_for_agent(agent_id, providers=providers)
        for token in targeted:
            self.audit.record_lifecycle(
                "revoked",
                provider=token.provider,
                agent_id=agent_id,
                organization_id=organization_id,
            )
        return revoked

    # --- resolution, called per agent request ---

    def resolve(self, authorization: str | None) -> GatewayTokenResolution:
        """Identify the Agent and provider behind a presented gateway token.

        Raises ``GatewayTokenRejected`` for every failure mode; the caller maps that to
        one structured 403 so an unknown token and a revoked token are indistinguishable
        to the agent while staying distinct in the audit trail.
        """
        value = _gateway_token_value(authorization)
        if value is None:
            self.audit.record_resolution(ResolutionOutcome.MALFORMED)
            raise GatewayTokenRejected(ResolutionOutcome.MALFORMED)

        token = self.repository.find_active_by_hash(hash_token(value))
        if token is None:
            # A revoked row is not returned by the active lookup, so distinguishing the
            # two outcomes would cost a second query on the hot path. Revocation is
            # already recorded as a lifecycle event, which is where a withdrawn
            # credential still in use shows up.
            self.audit.record_resolution(ResolutionOutcome.UNKNOWN)
            raise GatewayTokenRejected(ResolutionOutcome.UNKNOWN)

        self.audit.record_resolution(
            ResolutionOutcome.RESOLVED,
            provider=token.provider,
            agent_id=token.agent_id,
            organization_id=token.organization_id,
        )
        self.repository.touch_last_used(token.id, datetime.datetime.now(datetime.UTC))
        return GatewayTokenResolution(
            agent_id=token.agent_id,
            organization_id=token.organization_id,
            provider=token.provider,
        )

    # --- forwarding, called per agent request ---

    def forward(self, authorization: str | None, request: ForwardRequest) -> UpstreamResponse:
        """Re-authorize one agent request with the real provider credential and send it.

        Resolution comes first, so an absent or revoked token never reaches a decrypt.
        """
        resolution = self.resolve(authorization)

        # The token names a provider and so does the path. A GitHub token must not be
        # usable against the Jira upstream, so a mismatch is refused rather than
        # resolved in favour of either one.
        if resolution.provider.value != request.provider_key:
            raise GatewayForwardRefused(f"token is for {resolution.provider.value}, not {request.provider_key}")

        plugin = INTEGRATION_PLUGINS.require(resolution.provider)
        if plugin.egress_mode is not EgressMode.GATEWAY_PROXY:
            # A live token for a provider whose mode changed since issuance (a deploy
            # landed between them). Refuse rather than forward unauthenticated.
            raise GatewayForwardRefused(f"{plugin.key} is not routed through the gateway")

        content = self._decrypt_credential(resolution.agent_id, resolution.organization_id, resolution.provider)
        if content is None:
            raise GatewayForwardRefused(f"no {plugin.key} credential for this agent")

        try:
            outbound = plugin.apply_upstream_auth(
                content,
                OutboundRequest(
                    method=request.method,
                    path=request.path,
                    headers=sanitize_request_headers(request.headers),
                    query=dict(request.params),
                ),
            )
            base = plugin.upstream_base_url(content).rstrip("/")
        except UpstreamAuthenticationError as exc:
            raise UpstreamUnreachable("provider authorization could not be established") from exc
        except ValueError as exc:
            raise GatewayForwardRefused(f"invalid upstream configuration for {plugin.key}") from exc
        url = f"{base}/{request.path.lstrip('/')}"
        return self.forwarder.send(
            outbound.method,
            url,
            headers=outbound.headers,
            params=outbound.query,
            content=request.body,
            sensitive_headers=outbound.sensitive_headers,
        )

    # --- token brokering, called once per agent process start ---

    def mint_upstream_token(self, authorization: str | None) -> MintedToken:
        """Mint a short-lived upstream credential for a ``TOKEN_BROKER`` provider.

        The pod uses the result directly against the provider, so unlike the proxy path
        the gateway is not on the request path afterwards. That is the trade this mode
        makes: the pod holds an expiring credential instead of none, in exchange for
        working with a CLI that cannot be redirected.
        """
        resolution = self.resolve(authorization)
        plugin = INTEGRATION_PLUGINS.require(resolution.provider)
        if plugin.egress_mode is not EgressMode.TOKEN_BROKER:
            raise GatewayForwardRefused(f"{plugin.key} does not broker upstream tokens")

        content = self._decrypt_credential(resolution.agent_id, resolution.organization_id, resolution.provider)
        if content is None:
            raise GatewayForwardRefused(f"no {plugin.key} credential for this agent")

        minted = plugin.mint_upstream_token(content)
        self.audit.record_lifecycle(
            "minted",
            provider=resolution.provider,
            agent_id=resolution.agent_id,
            organization_id=resolution.organization_id,
        )
        return minted

    def _decrypt_credential(
        self,
        agent_id: UUID,
        organization_id: UUID,
        provider: SecretProvider,
    ) -> SecretContent | None:
        """Load and decrypt one Agent Secret, following a Shared Credential when set."""
        secrets = [s for s in self.agent_repository.get_secrets_for_agent(agent_id) if s.provider == provider.value]
        if not secrets:
            return None
        secret = secrets[0]
        ciphertext = secret.content
        if secret.shared_credential_id is not None:
            shared = self.shared_credential_repository.get_by_ids_and_org(
                [secret.shared_credential_id], organization_id
            )
            if not shared:
                return None
            ciphertext = shared[0].content
        if ciphertext is None:
            return None
        return decrypt_content(provider, ciphertext, self.config.agent_token_encryption_key)


def _gateway_token_value(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, rest = authorization.partition(" ")
    if scheme.lower() == "bearer":
        value = rest.strip()
    elif scheme.lower() == "basic":
        try:
            decoded = base64.b64decode(rest.strip(), validate=True).decode("utf-8")
        except binascii.Error, UnicodeDecodeError:
            return None
        _, separator, value = decoded.partition(":")
        if not separator:
            return None
        value = value.strip()
    else:
        return None
    # The prefix check is a cheap reject for a credential meant for something else
    # (a LiteLLM key, a Communications key) so it never reaches a hash lookup.
    return value if value.startswith(TOKEN_PREFIX) else None


class GatewayForwardRefused(Exception):
    """The request cannot be forwarded: wrong provider, not gateway-routed, or no credential."""


@dataclass(frozen=True)
class ForwardRequest:
    """One agent request to re-authorize and send upstream."""

    provider_key: str
    path: str
    method: str
    headers: dict[str, str]
    params: dict[str, str]
    body: bytes

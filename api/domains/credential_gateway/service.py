"""Gateway Token issuance, revocation, and resolution.

Issuance is driven by each provider's ``EgressMode``: a provider whose credential still
materializes into the pod (``DIRECT``) needs no gateway token, so nothing is issued for
it. Flipping a provider to ``GATEWAY_PROXY`` or ``TOKEN_BROKER`` starts issuance for that
provider with no change here.
"""

import datetime
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.agents.models import SecretProvider
from api.domains.credential_gateway.audit import GatewayAuditSink, ResolutionOutcome
from api.domains.credential_gateway.models import (
    TOKEN_PREFIX,
    GatewayToken,
    GatewayTokenResolution,
    IssuedGatewayToken,
    hash_token,
    issue_token_value,
)
from api.domains.credential_gateway.repository import GatewayTokenRepository
from api.domains.integrations.plugins.base import EgressMode
from api.domains.integrations.plugins.registry import INTEGRATION_PLUGINS


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

    # --- issuance, called from agent start ---

    def providers_needing_a_token(self, providers: set[SecretProvider]) -> set[SecretProvider]:
        """Narrow an Agent's configured providers to those the gateway serves."""
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
        Returns an empty list when no configured provider is served by the gateway,
        which is the current state of every provider.
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
        value = _bearer_value(authorization)
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


def _bearer_value(authorization: str | None) -> str | None:
    if not authorization:
        return None
    scheme, _, rest = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return None
    value = rest.strip()
    # The prefix check is a cheap reject for a credential meant for something else
    # (a LiteLLM key, a Communications key) so it never reaches a hash lookup.
    return value if value.startswith(TOKEN_PREFIX) else None

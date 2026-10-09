"""Provider capability and desired-mode reads, independent of runtime generations."""

from dataclasses import dataclass
from typing import Literal

from api.domains.agents.models import AgentSecret, IntegrationIsolationRead, SecretProvider
from api.domains.integrations.capabilities import ISOLATION_CAPABILITIES
from api.domains.integrations.models import AgentIntegrationIsolation

_LEGACY_ISOLATED = frozenset(
    {
        SecretProvider.GITHUB,
        SecretProvider.JIRA,
        SecretProvider.CONFLUENCE,
        SecretProvider.BITBUCKET,
        SecretProvider.PIPEDRIVE,
        SecretProvider.FIRECRAWL,
        SecretProvider.GOOGLE_WORKSPACE,
    }
)


def legacy_isolation(provider: SecretProvider) -> bool:
    """Preserve routes for pre-policy credentials; never downgrade missing legacy rows."""
    return provider in _LEGACY_ISOLATED


def default_isolation(provider: SecretProvider) -> bool:
    """New bindings opt in to isolation explicitly."""
    return False


def isolation_read(provider: SecretProvider, isolated: bool | None) -> IntegrationIsolationRead:
    """Describe stored intent and current capabilities, never inferred runtime state."""
    capabilities = ISOLATION_CAPABILITIES[provider]
    modes: list[Literal["direct", "isolated"]] = []
    if capabilities.supports_direct:
        modes.append("direct")
    if capabilities.supports_isolated:
        modes.append("isolated")
    return IntegrationIsolationRead(
        desired=legacy_isolation(provider) if isolated is None else isolated,
        supported_modes=modes,
        direct_description=capabilities.direct_description,
        isolated_description=capabilities.isolated_description,
        switch_available=capabilities.supports_direct and capabilities.supports_isolated,
    )


@dataclass(frozen=True)
class IntegrationBinding:
    source: Literal["agent_secret", "shared_credential", "platform_default"]
    isolation: IntegrationIsolationRead


def resolve_binding(
    provider: SecretProvider,
    secret: AgentSecret | None,
    policy: AgentIntegrationIsolation | None,
    *,
    firecrawl_default_configured: bool = False,
) -> IntegrationBinding | None:
    """Derive credential ownership without copying source data into the policy row."""
    if secret is not None:
        if SecretProvider(secret.provider) != provider:
            raise ValueError("Credential and requested provider disagree")
        if policy is not None and (policy.provider != provider or policy.agent_id != secret.agent_id):
            raise ValueError("Policy and credential binding disagree")
        source = "shared_credential" if secret.shared_credential_id is not None else "agent_secret"
        return IntegrationBinding(source, isolation_read(provider, policy.isolated if policy else None))
    if provider == SecretProvider.FIRECRAWL and firecrawl_default_configured:
        # The operator source has an independent opt-in policy.
        return IntegrationBinding("platform_default", isolation_read(provider, policy.isolated if policy else False))
    return None

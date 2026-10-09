"""Read-only isolation catalogue, separate from runtime plugin definitions."""

from dataclasses import dataclass

from api.domains.agents.models import SecretProvider
from api.domains.integrations.plugins.aai_cli_support import AaiCliIntegration
from api.domains.integrations.plugins.base import EgressMode, IntegrationPlugin
from api.domains.integrations.plugins.registry import INTEGRATION_PLUGINS


@dataclass(frozen=True)
class IsolationCapabilities:
    direct_description: str
    isolated_description: str
    supports_direct: bool = True
    supports_isolated: bool = True


ISOLATION_CAPABILITIES = {
    SecretProvider.GITHUB: IsolationCapabilities(
        "This Agent receives the GitHub token and connects to GitHub directly.",
        "The GitHub token stays outside this Agent; Agent Barn authenticates requests.",
    ),
    SecretProvider.JIRA: IsolationCapabilities(
        "This Agent receives the Jira credential and connects to Jira directly.",
        "The Jira credential stays outside this Agent; Agent Barn authenticates requests.",
    ),
    SecretProvider.CONFLUENCE: IsolationCapabilities(
        "This Agent receives the Confluence credential and connects to Confluence directly.",
        "The Confluence credential stays outside this Agent; Agent Barn authenticates requests.",
    ),
    SecretProvider.BITBUCKET: IsolationCapabilities(
        "This Agent receives the Bitbucket credential and connects to Bitbucket directly.",
        "The Bitbucket credential stays outside this Agent; Agent Barn authenticates requests.",
    ),
    SecretProvider.PIPEDRIVE: IsolationCapabilities(
        "This Agent receives the Pipedrive API token and connects to Pipedrive directly.",
        "The Pipedrive API token stays outside this Agent; Agent Barn authenticates requests.",
    ),
    SecretProvider.GOOGLE_WORKSPACE: IsolationCapabilities(
        "This Agent receives the Google refresh token and OAuth client credentials and connects to Google directly.",
        "This Agent receives expiring Google access tokens only; the refresh token and OAuth client secret stay outside it.",
    ),
    SecretProvider.FIRECRAWL: IsolationCapabilities(
        "This Agent receives the Firecrawl API key and connects to Firecrawl directly.",
        "The stored Firecrawl API key stays outside this Agent; Agent Barn authenticates requests.",
    ),
    SecretProvider.SHAREPOINT: IsolationCapabilities(
        "Personal sign-in: this Agent receives the SharePoint refresh token. Selected sites: it uses Agent Barn to fetch app-only tokens; native Teams credentials remain in the Agent.",
        "SharePoint uses expiring Microsoft Graph access tokens; a personal refresh token stays outside the Agent. Selected sites retains native Teams app credentials in the Agent. Switching does not cancel previously received tokens.",
    ),
}


def validate_isolation_capabilities(plugin: IntegrationPlugin, capabilities: IsolationCapabilities) -> None:
    if not capabilities.supports_direct and not capabilities.supports_isolated:
        raise ValueError(f"Integration Plugin {plugin.key!r} supports no credential route")
    if not capabilities.direct_description.strip() or not capabilities.isolated_description.strip():
        raise ValueError(f"Integration Plugin {plugin.key!r} must describe both isolation choices")
    if capabilities.supports_isolated != (plugin.egress_mode != EgressMode.DIRECT):
        raise ValueError(f"Integration Plugin {plugin.key!r} isolation capability disagrees with its route")
    if plugin.egress_mode == EgressMode.DIRECT and not capabilities.supports_direct:
        raise ValueError(f"Integration Plugin {plugin.key!r} has no direct credential path")
    if (
        capabilities.supports_direct
        and isinstance(plugin, AaiCliIntegration)
        and type(plugin).aai_cli_profile_block is AaiCliIntegration.aai_cli_profile_block
    ):
        raise ValueError(f"Integration Plugin {plugin.key!r} declares direct support without a profile")


for _plugin in INTEGRATION_PLUGINS.all():
    validate_isolation_capabilities(_plugin, ISOLATION_CAPABILITIES[_plugin.provider])

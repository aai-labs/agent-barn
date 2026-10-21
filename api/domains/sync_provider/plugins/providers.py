from api.core.config import Config
from api.domains.agents.microsoft_graph_sites import MicrosoftGraphSites
from api.domains.agents.microsoft_identity import MicrosoftIdentityClient
from api.domains.sync_provider.plugins.base import SyncProviderPlugin
from api.domains.sync_provider.plugins.onedrive import OneDriveSyncProviderPlugin


def shipped_plugins(
    config: Config, identity: MicrosoftIdentityClient, graph_sites: MicrosoftGraphSites
) -> list[SyncProviderPlugin]:
    """Every Sync Provider Plugin shipped with Agent Barn; the registry and the contract tests share it."""
    return [OneDriveSyncProviderPlugin(config, identity, graph_sites)]

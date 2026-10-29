from api.core.config import Config
from api.domains.agents.microsoft_graph_files import MicrosoftGraphFiles
from api.domains.agents.microsoft_graph_sites import MicrosoftGraphSites
from api.domains.agents.microsoft_identity import MicrosoftAppTokens, MicrosoftIdentityClient
from api.domains.sync_provider.plugins.base import SyncProviderPlugin
from api.domains.sync_provider.plugins.onedrive import OneDriveSyncProviderPlugin


def shipped_plugins(
    config: Config,
    identity: MicrosoftIdentityClient,
    graph_sites: MicrosoftGraphSites,
    graph_files: MicrosoftGraphFiles,
    app_tokens: MicrosoftAppTokens,
) -> list[SyncProviderPlugin]:
    """Every Sync Provider Plugin shipped with Agent Barn; the registry and the contract tests share it."""
    return [OneDriveSyncProviderPlugin(config, identity, graph_sites, graph_files, app_tokens)]

"""Code-owned catalogue of the Integration Plugins shipped with Agent Barn.

Coherence is checked when the registry is constructed — that is, at import — so a
malformed plugin fails process startup rather than one agent's start. A single
parametrized test over ``INTEGRATION_PLUGINS`` then covers every provider's contract,
which is what stops the old scattered per-provider maps from silently reappearing.
"""

from __future__ import annotations

from collections.abc import Iterable

from api.domains.agents.models import SecretProvider
from api.domains.integrations.plugins.aai_cli_support import AaiCliIntegration
from api.domains.integrations.plugins.base import EgressMode, IntegrationPlugin
from api.domains.integrations.plugins.providers import AAI_CLI, GOG, NO_TOOL, SHIPPED_PLUGINS

#: Adapters that exist to materialize a provider's runtime artifacts. A plugin naming
#: anything else is a startup error rather than a silently tool-less provider.
KNOWN_RUNTIME_TOOLS = frozenset({AAI_CLI, GOG, NO_TOOL})


class IntegrationPluginRegistry:
    def __init__(self, plugins: Iterable[IntegrationPlugin]) -> None:
        by_provider: dict[SecretProvider, IntegrationPlugin] = {}
        for plugin in plugins:
            key = plugin.key.strip().lower()
            if not key or key != plugin.key:
                raise ValueError(f"Integration Plugin key must be canonical lowercase: {plugin.key!r}")
            if plugin.provider.value != key:
                raise ValueError(f"Integration Plugin key {key!r} does not match provider {plugin.provider.value!r}")
            if plugin.provider in by_provider:
                raise ValueError(f"Duplicate Integration Plugin provider: {key}")
            if plugin.schema_version < 1:
                raise ValueError(f"Integration Plugin schema version must be positive: {key}")
            if plugin.runtime_tool not in KNOWN_RUNTIME_TOOLS:
                raise ValueError(f"Integration Plugin {key!r} names unknown runtime tool {plugin.runtime_tool!r}")
            if plugin.runtime_tool == AAI_CLI and not isinstance(plugin, AaiCliIntegration):
                raise ValueError(f"Integration Plugin {key!r} runs on aai-cli but does not implement AaiCliIntegration")
            _check_egress_seam(plugin)
            by_provider[plugin.provider] = plugin

        missing = [p.value for p in SecretProvider if p not in by_provider]
        if missing:
            raise ValueError(f"No Integration Plugin registered for provider(s): {', '.join(missing)}")

        # Fixed SecretProvider order keeps every rendered artifact deterministic, which is
        # what the config.toml, setup.sh, and agents_md builders relied on before this seam.
        self._plugins = {provider: by_provider[provider] for provider in SecretProvider}

    def require(self, provider: SecretProvider) -> IntegrationPlugin:
        try:
            return self._plugins[provider]
        except KeyError as exc:
            raise KeyError(f"Unsupported integration provider: {provider}") from exc

    def all(self) -> tuple[IntegrationPlugin, ...]:
        """Every plugin in fixed provider order."""
        return tuple(self._plugins.values())

    def for_tool(self, runtime_tool: str) -> tuple[IntegrationPlugin, ...]:
        """Every plugin reached by one CLI, in fixed provider order."""
        return tuple(p for p in self._plugins.values() if p.runtime_tool == runtime_tool)


def _check_egress_seam(plugin: IntegrationPlugin) -> None:
    """A declared egress mode must be backed by the methods that mode needs."""
    if plugin.egress_mode == EgressMode.GATEWAY_PROXY:
        for method in ("upstream_base_url", "apply_upstream_auth"):
            if not _overrides(plugin, method):
                raise ValueError(
                    f"Integration Plugin {plugin.key!r} is {plugin.egress_mode.value} but never overrides {method}"
                )
    elif plugin.egress_mode == EgressMode.TOKEN_BROKER and not _overrides(plugin, "mint_upstream_token"):
        raise ValueError(
            f"Integration Plugin {plugin.key!r} is {plugin.egress_mode.value} but never overrides mint_upstream_token"
        )


def _overrides(plugin: IntegrationPlugin, method: str) -> bool:
    return getattr(type(plugin), method) is not getattr(IntegrationPlugin, method)


INTEGRATION_PLUGINS = IntegrationPluginRegistry(SHIPPED_PLUGINS)


def effective_egress_mode(plugin: IntegrationPlugin, gateway_enabled: bool) -> EgressMode:
    """What a provider actually does right now, as opposed to what it supports.

    A plugin's ``egress_mode`` owns the provider decision. The global switch exists only
    for operational rollback. Both Gateway Token issuance and runtime artifact builders
    resolve the mode here, so they cannot disagree about where a credential goes and a
    new provider needs no second registration in deployment configuration.
    """
    if plugin.egress_mode is EgressMode.DIRECT:
        return EgressMode.DIRECT
    return plugin.egress_mode if gateway_enabled else EgressMode.DIRECT

from collections.abc import Iterable

from api.domains.sync_provider.models import SyncProviderCapability, SyncProviderDescriptorRead
from api.domains.sync_provider.plugins.base import SyncLocationGuard, SyncProviderPlugin

CAPABILITY_METHODS: dict[SyncProviderCapability, tuple[str, ...]] = {
    SyncProviderCapability.LOCATION_PICKER: ("search_locations", "resolve_location"),
    SyncProviderCapability.ADMIN_APPROVAL: ("approval_url", "is_approval_callback"),
    SyncProviderCapability.FILE_SYNC: (
        "create_folder",
        "get_item",
        "get_item_by_path",
        "move_item",
        "delete_item",
        "changes",
        "list_files",
        "upload_target",
        "download_url",
        "write_empty_file",
    ),
}


class SyncProviderPluginRegistry:
    """Code-owned catalogue of the Sync Provider Plugins shipped with Agent Barn."""

    def __init__(self, plugins: Iterable[SyncProviderPlugin]) -> None:
        by_key: dict[str, SyncProviderPlugin] = {}
        for plugin in plugins:
            key = plugin.key.strip().lower()
            if not key or key != plugin.key:
                raise ValueError(f"Sync Provider Plugin key must be canonical lowercase: {plugin.key!r}")
            if key in by_key:
                raise ValueError(f"Duplicate Sync Provider Plugin key: {key}")
            if plugin.schema_version < 1:
                raise ValueError(f"Sync Provider Plugin schema version must be positive: {key}")
            if plugin.location_guard is not None and not isinstance(plugin.location_guard, SyncLocationGuard):
                raise ValueError(f"Sync Provider Plugin {key!r} names an unknown location guard")
            for capability in plugin.capabilities:
                for method in CAPABILITY_METHODS[capability]:
                    if not _overrides(plugin, method):
                        raise ValueError(
                            f"Sync Provider Plugin {key!r} declares {capability.value} but never overrides {method}"
                        )
            if SyncProviderCapability.LOCATION_PICKER in plugin.capabilities and not plugin.location_noun:
                raise ValueError(f"Sync Provider Plugin {key!r} declares location_picker but names no location_noun")
            by_key[key] = plugin
        self._plugins = by_key

    def require(self, key: str) -> SyncProviderPlugin:
        try:
            return self._plugins[key]
        except KeyError as exc:
            raise KeyError(f"Unsupported sync provider: {key}") from exc

    def all(self) -> list[SyncProviderPlugin]:
        """Every registered provider, offered or not, in key order."""
        return [self._plugins[key] for key in sorted(self._plugins)]

    def offered(self) -> list[SyncProviderPlugin]:
        """Providers an Organization may connect on this server, in key order."""
        return [self._plugins[key] for key in sorted(self._plugins) if self._plugins[key].is_offered()]

    def descriptors(self) -> list[SyncProviderDescriptorRead]:
        return [plugin.descriptor for plugin in self.offered()]


def _overrides(plugin: SyncProviderPlugin, method: str) -> bool:
    return getattr(type(plugin), method) is not getattr(SyncProviderPlugin, method)

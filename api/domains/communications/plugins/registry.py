from collections.abc import Iterable

from api.domains.communications.models import PlatformDescriptorRead
from api.domains.communications.plugins.base import PlatformPlugin


class PlatformPluginRegistry:
    """Code-owned catalogue of trusted Platform Plugins shipped with Agent Barn."""

    def __init__(self, plugins: Iterable[PlatformPlugin]) -> None:
        by_key: dict[str, PlatformPlugin] = {}
        for plugin in plugins:
            key = plugin.key.strip().lower()
            if not key or key != plugin.key:
                raise ValueError(f"Platform Plugin key must be canonical lowercase: {plugin.key!r}")
            if key in by_key:
                raise ValueError(f"Duplicate Platform Plugin key: {key}")
            if plugin.schema_version < 1:
                raise ValueError(f"Platform Plugin schema version must be positive: {key}")
            by_key[key] = plugin
        self._plugins = by_key

    def require(self, key: str) -> PlatformPlugin:
        try:
            return self._plugins[key]
        except KeyError as exc:
            raise KeyError(f"Unsupported communication platform: {key}") from exc

    def descriptors(self) -> list[PlatformDescriptorRead]:
        return [self._plugins[key].descriptor for key in sorted(self._plugins)]

from collections.abc import Callable

from api.core.config import get_config
from api.infrastructure.shared.cache import cached as _cached
from api.infrastructure.shared.cache import clear_cache as clear_directory_cache  # noqa: F401


def cached(key: str, fetch: Callable[[], list[dict]]) -> list[dict]:
    """Return cached Slack directory entries, refreshing via *fetch* on miss/expiry."""
    ttl = get_config().slack_directory_cache_ttl_seconds
    return _cached(key, fetch, ttl=ttl)

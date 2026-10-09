from collections.abc import Callable
from typing import Any, cast

from injector import Module, provider, singleton

from api.infrastructure.posthog.client import PostHogClient

_BLOCKED_HOST = "posthog.com"


def make_posthog_blocking_post(real_post: Callable) -> Callable:
    def _guarded_post(*args, **kwargs):
        url = str(args[0] if args else kwargs.get("url", ""))
        if _BLOCKED_HOST in url:
            raise RuntimeError(
                f"Test attempted to call {_BLOCKED_HOST}. Patch "
                "api.infrastructure.posthog.client.httpx.post or bind MockPostHogModule "
                "if this send is intentional."
            )
        return real_post(*args, **kwargs)

    return _guarded_post


class MockPostHogModule(Module):
    def __init__(self, error: Exception | None = None) -> None:
        self.batches: list[list[dict[str, Any]]] = []
        self.error = error

    @singleton
    @provider
    def provide_posthog_client(self) -> PostHogClient:
        parent = self

        class MockPostHogClient:
            def send_batch(self, messages: list[dict[str, Any]]) -> None:
                if parent.error is not None:
                    raise parent.error
                parent.batches.append(messages)

        return cast(PostHogClient, MockPostHogClient())

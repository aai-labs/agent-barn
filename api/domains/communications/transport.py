"""Fixed provider transport ownership for the shipped Platforms."""

from types import MappingProxyType
from typing import Literal

PlatformTransport = Literal["native", "gateway"]

PLATFORM_TRANSPORTS: MappingProxyType[str, PlatformTransport] = MappingProxyType(
    {
        "slack": "native",
        "discord": "native",
        "telegram": "native",
        "teams": "native",
        # The runtime's own Telegram adapter, behind Agent Barn's shared-bot relay and proxy.
        "agentbarn_telegram": "native",
        "web": "gateway",
        "email": "gateway",
    }
)
NATIVE_PLATFORM_KEYS = frozenset(key for key, transport in PLATFORM_TRANSPORTS.items() if transport == "native")
GATEWAY_PLATFORM_KEYS = frozenset(key for key, transport in PLATFORM_TRANSPORTS.items() if transport == "gateway")


def platform_transport(platform_key: str) -> PlatformTransport:
    return PLATFORM_TRANSPORTS[platform_key]


class NativeTransportUnsupported(RuntimeError):
    """A retired gateway operation targeting a runtime-owned Connection."""


def require_gateway_transport(platform_key: str) -> None:
    if platform_transport(platform_key) != "gateway":
        raise NativeTransportUnsupported("This Platform uses native transport; gateway delivery is unsupported")

"""Outbound HTTPS to a host the user chose, restricted to public addresses.

Refusing a private URL up front is not enough: a public name can resolve to a private
address, and can change its answer between a check and the connection. So a request is
pinned to the addresses that were checked, while TLS and ``Host`` keep the real name, and
every redirect hop is checked again.

Anything reachable from the API can be reached this way, so this is what stands between a
stored URL and the cluster's internal services.
"""

import ipaddress
import socket
from dataclasses import dataclass, field

import httpx


class NonPublicDestination(Exception):
    """The destination is not a public HTTPS address."""


def public_addresses(host: str, port: int = 443) -> list[str]:
    """Return every address ``host`` resolves to, or refuse if any of them is not public."""
    addresses = sorted({str(row[4][0]) for row in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    if not addresses:
        raise NonPublicDestination("Destination has no public address")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_reserved or getattr(ip, "ipv4_mapped", None):
            raise NonPublicDestination("Private, internal and special network destinations are unsupported")
    return addresses


@dataclass(frozen=True)
class PinnedRequest:
    """How to send a request to a checked address while still speaking to the real host."""

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    extensions: dict[str, str] = field(default_factory=dict)


def pin_to_public_address(url: str) -> PinnedRequest:
    """Resolve and check ``url``'s host, or raise ``NonPublicDestination``."""
    target = httpx.URL(url)
    if target.scheme != "https" or not target.host:
        raise NonPublicDestination("Destination must be an https URL")
    try:
        addresses = public_addresses(target.host, target.port or 443)
    except socket.gaierror as exc:
        raise NonPublicDestination("Destination could not be resolved") from exc
    host_header = f"{target.host}:{target.port}" if target.port else target.host
    return PinnedRequest(
        url=str(target.copy_with(host=addresses[0])),
        headers={"Host": host_header},
        extensions={"sni_hostname": target.host},
    )

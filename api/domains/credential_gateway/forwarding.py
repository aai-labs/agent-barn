"""Outbound leg of the credential gateway.

Kept behind an injectable seam so the forward path is testable without patching
``httpx`` globally, and so a future implementation (connection pooling per upstream,
circuit breaking) is a binding change rather than a rewrite.
"""

from dataclasses import dataclass, field

import httpx
from injector import singleton

#: Headers that describe one hop and must not be copied onto the next one.
HOP_BY_HOP_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    }
)

#: Request headers the gateway owns and never forwards from the agent. ``authorization``
#: carries the agent's gateway token and is replaced by the provider's real credential;
#: ``host`` and ``content-length`` are recomputed for the upstream request.
GATEWAY_OWNED_REQUEST_HEADERS = frozenset({"authorization", "host", "content-length"})

_TIMEOUT = 30
#: Bounded so a redirect loop cannot pin a gateway worker.
_MAX_REDIRECTS = 5


@dataclass(frozen=True)
class UpstreamResponse:
    status_code: int
    content: bytes
    headers: dict[str, str] = field(default_factory=dict)


class UpstreamUnreachable(Exception):
    """The upstream could not be reached. Distinct from an upstream error status."""


def sanitize_request_headers(headers: dict[str, str]) -> dict[str, str]:
    """Drop what the agent must not dictate before the plugin adds real auth."""
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in GATEWAY_OWNED_REQUEST_HEADERS and name.lower() not in HOP_BY_HOP_HEADERS
    }


def sanitize_response_headers(headers: dict[str, str]) -> dict[str, str]:
    """Strip hop-by-hop headers and any length/encoding the client would recompute."""
    return {
        name: value
        for name, value in headers.items()
        if name.lower() not in HOP_BY_HOP_HEADERS and name.lower() not in {"content-length", "content-encoding"}
    }


@singleton
class UpstreamForwarder:
    def send(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str],
        params: dict[str, str],
        content: bytes,
    ) -> UpstreamResponse:
        """Send one upstream request, following redirects with care.

        Redirects are followed here rather than handed back to the agent, because
        NetworkPolicy denies the pod any egress except this gateway — an agent told to
        follow a redirect to ``codeload.github.com`` simply cannot. Authorization is
        re-applied only while the redirect stays on the same host: carrying a provider
        credential onto a host the provider redirected us to would hand it to whoever
        controls that host.
        """
        try:
            with httpx.Client(timeout=_TIMEOUT, follow_redirects=False) as client:
                current_url = url
                current_headers = dict(headers)
                origin_host = httpx.URL(url).host
                for _ in range(_MAX_REDIRECTS + 1):
                    response = client.request(
                        method,
                        current_url,
                        headers=current_headers,
                        params=params or None,
                        content=content or None,
                    )
                    location = response.headers.get("location")
                    if not (response.is_redirect and location):
                        return UpstreamResponse(
                            status_code=response.status_code,
                            content=response.content,
                            headers=sanitize_response_headers(dict(response.headers)),
                        )
                    current_url = str(httpx.URL(current_url).join(location))
                    if httpx.URL(current_url).host != origin_host:
                        current_headers = {k: v for k, v in current_headers.items() if k.lower() != "authorization"}
                    # A redirect target carries its own query; resending ours would
                    # duplicate or contradict it.
                    params = {}
                raise UpstreamUnreachable(f"Exceeded {_MAX_REDIRECTS} redirects")
        except httpx.HTTPError as exc:
            raise UpstreamUnreachable(str(exc)) from exc

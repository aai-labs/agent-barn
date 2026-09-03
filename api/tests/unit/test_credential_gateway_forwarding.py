"""Header handling and redirect behavior on the gateway's outbound leg."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from hamcrest import assert_that, equal_to, is_, is_not

from api.domains.agents.models import GithubContent
from api.domains.credential_gateway.forwarding import (
    UpstreamForwarder,
    UpstreamUnreachable,
    sanitize_request_headers,
    sanitize_response_headers,
)
from api.domains.integrations.plugins.base import OutboundRequest
from api.domains.integrations.plugins.providers import GithubPlugin

_GITHUB = GithubContent(token="ghp_real_secret", owner="acme", repos=["r1"], org="acme-org")


# --- header sanitation ---


def test_the_agents_authorization_header_never_reaches_upstream():
    # It carries the gateway token; forwarding it would leak our own credential to the
    # provider and could collide with the real one the plugin is about to set.
    cleaned = sanitize_request_headers({"Authorization": "Bearer agt_x", "Accept": "application/json"})
    assert_that("Authorization" in cleaned, is_(False))
    assert_that(cleaned, equal_to({"Accept": "application/json"}))


def test_hop_by_hop_request_headers_are_dropped():
    cleaned = sanitize_request_headers({"Connection": "keep-alive", "TE": "trailers", "X-Trace": "abc"})
    assert_that(cleaned, equal_to({"X-Trace": "abc"}))


def test_host_and_content_length_are_recomputed_not_forwarded():
    cleaned = sanitize_request_headers({"Host": "gateway.local", "Content-Length": "12", "X-Keep": "y"})
    assert_that(cleaned, equal_to({"X-Keep": "y"}))


def test_response_length_and_encoding_headers_are_dropped():
    # The gateway hands back a decoded body of its own length; echoing the upstream's
    # values would describe a body the client never receives.
    cleaned = sanitize_response_headers(
        {"Content-Encoding": "gzip", "Content-Length": "999", "Transfer-Encoding": "chunked", "ETag": "W/x"}
    )
    assert_that(cleaned, equal_to({"ETag": "W/x"}))


# --- plugin auth substitution ---


def test_github_substitutes_the_real_token_and_pins_the_api_version():
    outbound = GithubPlugin().apply_upstream_auth(
        _GITHUB, OutboundRequest("GET", "/repos/acme/r1/pulls", headers={"Accept": "*/*"})
    )
    assert_that(outbound.headers["Authorization"], equal_to("Bearer ghp_real_secret"))
    assert_that(outbound.headers["Accept"], equal_to("application/vnd.github+json"))
    assert_that(outbound.headers["X-GitHub-Api-Version"], equal_to("2022-11-28"))


def test_github_upstream_is_the_public_api_host():
    assert_that(GithubPlugin().upstream_base_url(_GITHUB), equal_to("https://api.github.com"))


# --- redirects ---


def _response(status_code: int, *, location: str | None = None, content: bytes = b"") -> httpx.Response:
    headers = {"location": location} if location else {}
    return httpx.Response(status_code, headers=headers, content=content, request=httpx.Request("GET", "https://x/"))


def _client_returning(*responses):
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.request = MagicMock(side_effect=list(responses))
    return client


def test_a_same_host_redirect_keeps_the_provider_credential():
    client = _client_returning(
        _response(302, location="/repos/acme/r1/pulls/2"),
        _response(200, content=b"ok"),
    )
    with patch("httpx.Client", return_value=client):
        result = UpstreamForwarder().send(
            "GET",
            "https://api.github.com/repos/acme/r1/pulls/1",
            headers={"Authorization": "Bearer ghp_real_secret"},
            params={},
            content=b"",
        )
    assert_that(result.status_code, equal_to(200))
    second_call_headers = client.request.call_args_list[1].kwargs["headers"]
    assert_that(second_call_headers.get("Authorization"), equal_to("Bearer ghp_real_secret"))


def test_a_cross_host_redirect_drops_the_provider_credential():
    # GitHub redirects downloads to codeload/S3-style hosts. Carrying the PAT there
    # would hand a live credential to whoever controls that host.
    client = _client_returning(
        _response(302, location="https://codeload.github.com/acme/r1/tar.gz"),
        _response(200, content=b"tarball"),
    )
    with patch("httpx.Client", return_value=client):
        result = UpstreamForwarder().send(
            "GET",
            "https://api.github.com/repos/acme/r1/tarball",
            headers={"Authorization": "Bearer ghp_real_secret"},
            params={},
            content=b"",
        )
    assert_that(result.content, equal_to(b"tarball"))
    second_call_headers = client.request.call_args_list[1].kwargs["headers"]
    assert_that("Authorization" in second_call_headers, is_(False))


def test_a_redirect_loop_is_bounded_rather_than_pinning_a_worker():
    client = _client_returning(*[_response(302, location="/again") for _ in range(10)])
    with patch("httpx.Client", return_value=client):
        with pytest.raises(UpstreamUnreachable):
            UpstreamForwarder().send("GET", "https://api.github.com/a", headers={}, params={}, content=b"")


def test_a_transport_failure_becomes_upstream_unreachable():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.request = MagicMock(side_effect=httpx.ConnectError("boom"))
    with patch("httpx.Client", return_value=client):
        with pytest.raises(UpstreamUnreachable):
            UpstreamForwarder().send("GET", "https://api.github.com/a", headers={}, params={}, content=b"")


def test_an_upstream_error_status_is_returned_not_raised():
    # A 404 from GitHub is the agent's answer, not a gateway failure.
    client = _client_returning(_response(404, content=b'{"message":"Not Found"}'))
    with patch("httpx.Client", return_value=client):
        result = UpstreamForwarder().send("GET", "https://api.github.com/a", headers={}, params={}, content=b"")
    assert_that(result.status_code, equal_to(404))
    assert_that(result.content, is_not(equal_to(b"")))

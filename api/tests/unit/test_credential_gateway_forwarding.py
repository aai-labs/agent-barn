"""Header handling and redirect behavior on the gateway's outbound leg."""

from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from hamcrest import assert_that, equal_to, is_, is_not

from api.domains.agents.models import (
    BitbucketContent,
    ConfluenceContent,
    GithubContent,
    JiraContent,
    PipedriveContent,
)
from api.domains.credential_gateway.forwarding import (
    UpstreamForwarder,
    UpstreamUnreachable,
    sanitize_request_headers,
    sanitize_response_headers,
)
from api.domains.credential_gateway.routes import encoded_upstream_path
from api.domains.integrations.plugins.base import OutboundRequest
from api.domains.integrations.plugins.providers import (
    BitbucketPlugin,
    ConfluencePlugin,
    GithubPlugin,
    JiraPlugin,
    PipedrivePlugin,
)

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


def test_github_preserves_aai_cli_media_type_requests():
    outbound = GithubPlugin().apply_upstream_auth(
        _GITHUB,
        OutboundRequest("GET", "/repos/acme/r1/pulls/7", headers={"Accept": "application/vnd.github.v3.diff"}),
    )
    assert_that(outbound.headers["Accept"], equal_to("application/vnd.github.v3.diff"))


def test_github_upstream_is_the_public_api_host():
    assert_that(GithubPlugin().upstream_base_url(_GITHUB), equal_to("https://api.github.com"))


@pytest.mark.parametrize(
    ("plugin", "content", "expected_base", "expected_authorization"),
    [
        (
            JiraPlugin(),
            JiraContent(site_url="https://acme.atlassian.net", email="jira@example.com", api_token="jira-real"),
            "https://acme.atlassian.net",
            "Basic amlyYUBleGFtcGxlLmNvbTpqaXJhLXJlYWw=",
        ),
        (
            ConfluencePlugin(),
            ConfluenceContent(site_url="https://acme.atlassian.net", email="conf@example.com", api_token="conf-real"),
            "https://acme.atlassian.net",
            "Basic Y29uZkBleGFtcGxlLmNvbTpjb25mLXJlYWw=",
        ),
        (
            BitbucketPlugin(),
            BitbucketContent(workspace="acme", repos=["app"], email="bb@example.com", api_token="bb-real"),
            "https://api.bitbucket.org/2.0",
            "Basic YmJAZXhhbXBsZS5jb206YmItcmVhbA==",
        ),
    ],
)
def test_basic_auth_providers_apply_the_real_credential(plugin, content, expected_base, expected_authorization):
    outbound = plugin.apply_upstream_auth(content, OutboundRequest("GET", "/resource"))
    assert_that(plugin.upstream_base_url(content), equal_to(expected_base))
    assert_that(outbound.headers["Authorization"], equal_to(expected_authorization))


def test_scoped_atlassian_credentials_use_the_cloud_gateway_bases():
    jira = JiraContent(
        site_url="https://acme.atlassian.net",
        use_scoped_token=True,
        cloud_id="cloud-123",
        email="jira@example.com",
        api_token="jira-real",
    )
    confluence = ConfluenceContent(
        site_url="https://acme.atlassian.net",
        use_scoped_token=True,
        cloud_id="cloud-123",
        email="conf@example.com",
        api_token="conf-real",
    )
    assert_that(JiraPlugin().upstream_base_url(jira), equal_to("https://api.atlassian.com/ex/jira/cloud-123"))
    assert_that(
        ConfluencePlugin().upstream_base_url(confluence),
        equal_to("https://api.atlassian.com/ex/confluence/cloud-123"),
    )


@pytest.mark.parametrize(
    ("plugin", "content"),
    [
        (
            JiraPlugin(),
            JiraContent(site_url="http://169.254.169.254", email="jira@example.com", api_token="jira-real"),
        ),
    ],
)
def test_credential_owned_upstream_urls_cannot_target_untrusted_hosts(plugin, content):
    with pytest.raises(ValueError):
        plugin.upstream_base_url(content)


def test_pipedrive_applies_its_real_custom_header():
    content = PipedriveContent(api_token="pd-real", domain="acme")
    outbound = PipedrivePlugin().apply_upstream_auth(content, OutboundRequest("GET", "/v1/users/me"))
    assert_that(PipedrivePlugin().upstream_base_url(content), equal_to("https://acme.pipedrive.com"))
    assert_that(outbound.headers["x-api-token"], equal_to("pd-real"))


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


def test_a_cross_host_redirect_drops_a_provider_specific_credential_header():
    client = _client_returning(
        _response(302, location="https://downloads.example.test/export"),
        _response(200, content=b"export"),
    )
    with patch("httpx.Client", return_value=client):
        result = UpstreamForwarder().send(
            "GET",
            "https://acme.pipedrive.com/v1/export",
            headers={"x-api-token": "pd-real", "Accept": "application/json"},
            params={},
            content=b"",
            sensitive_headers=frozenset({"x-api-token"}),
        )
    assert_that(result.content, equal_to(b"export"))
    second_call_headers = client.request.call_args_list[1].kwargs["headers"]
    assert_that("x-api-token" in second_call_headers, is_(False))
    assert_that(second_call_headers["Accept"], equal_to("application/json"))


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


@pytest.mark.parametrize(
    "target",
    [
        "https://acme.pipedrive.com:8443/v1/export",
        "http://acme.pipedrive.com/v1/export",
    ],
)
def test_same_host_different_origin_strips_all_provider_credentials(target):
    client = _client_returning(_response(302, location=target), _response(200, content=b"export"))
    with patch("httpx.Client", return_value=client):
        UpstreamForwarder().send(
            "GET",
            "https://acme.pipedrive.com/v1/export",
            headers={"Authorization": "Bearer fixture", "X-API-Token": "fixture", "Accept": "application/json"},
            params={},
            content=b"",
            sensitive_headers=frozenset({"authorization", "x-api-token"}),
        )
    headers = client.request.call_args_list[1].kwargs["headers"]
    assert_that(headers, equal_to({"Accept": "application/json"}))


def test_explicit_default_port_retains_same_origin_credentials():
    client = _client_returning(_response(302, location="https://api.github.com:443/export"), _response(200))
    with patch("httpx.Client", return_value=client):
        UpstreamForwarder().send(
            "GET", "https://api.github.com/export", headers={"Authorization": "Bearer fixture"}, params={}, content=b""
        )
    assert_that(client.request.call_args_list[1].kwargs["headers"]["Authorization"], equal_to("Bearer fixture"))


# --- public-only forwarding, for providers whose host the user chooses ---


def _gateway_client(*responses: httpx.Response) -> MagicMock:
    client = MagicMock()
    client.__enter__.return_value = client
    client.request.side_effect = list(responses)
    return client


def _forward_public_only(client: MagicMock, url: str = "https://gitlab.example.com/api/v4/projects/group%2Fapp"):
    with patch("api.domains.credential_gateway.forwarding.httpx.Client", return_value=client):
        return UpstreamForwarder().send(
            "GET", url, headers={"Authorization": "Bearer real"}, params={}, content=b"", public_only=True
        )


def _resolving(answers: dict[str, str]):
    def resolve(host, port, **_):
        return [(2, 1, 6, "", (answers[host], port))]

    return patch("api.infrastructure.public_http.socket.getaddrinfo", side_effect=resolve)


def test_public_only_sends_to_the_checked_address_under_the_real_name():
    client = _gateway_client(httpx.Response(200, json={}))
    with _resolving({"gitlab.example.com": "8.8.8.8"}):
        _forward_public_only(client)
    args, kwargs = client.request.call_args
    assert_that(args[1], equal_to("https://8.8.8.8/api/v4/projects/group%2Fapp"))
    assert_that(kwargs["headers"]["Host"], equal_to("gitlab.example.com"))
    assert_that(kwargs["extensions"], equal_to({"sni_hostname": "gitlab.example.com"}))


def test_public_only_never_sends_to_a_private_address():
    client = _gateway_client()
    with _resolving({"gitlab.example.com": "10.0.0.5"}), pytest.raises(UpstreamUnreachable):
        _forward_public_only(client)
    client.request.assert_not_called()


def test_public_only_rechecks_a_redirect_target():
    # The first host is public, so only a check on the second hop can stop this reaching
    # an internal service.
    redirect = httpx.Response(302, headers={"location": "https://internal.example/admin"})
    client = _gateway_client(redirect)
    with (
        _resolving({"gitlab.example.com": "8.8.8.8", "internal.example": "10.0.0.5"}),
        pytest.raises(UpstreamUnreachable),
    ):
        _forward_public_only(client)
    assert_that(client.request.call_count, equal_to(1))


def test_public_only_refuses_a_redirect_down_to_plain_http():
    redirect = httpx.Response(302, headers={"location": "http://gitlab.example.com/api/v4/user"})
    client = _gateway_client(redirect)
    with _resolving({"gitlab.example.com": "8.8.8.8"}), pytest.raises(UpstreamUnreachable):
        _forward_public_only(client)


def test_a_same_origin_redirect_keeps_the_credential_and_the_pin():
    redirect = httpx.Response(302, headers={"location": "/api/v4/next"})
    client = _gateway_client(redirect, httpx.Response(200, json={}))
    with _resolving({"gitlab.example.com": "8.8.8.8"}):
        _forward_public_only(client)
    args, kwargs = client.request.call_args
    assert_that(args[1], equal_to("https://8.8.8.8/api/v4/next"))
    assert_that(kwargs["headers"]["Authorization"], equal_to("Bearer real"))


def test_forwarding_is_unpinned_unless_the_provider_asks():
    client = _gateway_client(httpx.Response(200, json={}))
    with (
        patch("api.domains.credential_gateway.forwarding.httpx.Client", return_value=client),
        patch("api.infrastructure.public_http.socket.getaddrinfo") as resolve,
    ):
        UpstreamForwarder().send("GET", "https://api.github.com/user", headers={}, params={}, content=b"")
    resolve.assert_not_called()
    assert_that(client.request.call_args.args[1], equal_to("https://api.github.com/user"))


# --- encoded paths ---


def _route_request(raw_path: bytes) -> MagicMock:
    request = MagicMock()
    request.scope = {"raw_path": raw_path}
    return request


def test_the_encoded_upstream_path_is_recovered_from_the_raw_request():
    request = _route_request(b"/gateway/v1/p/gitlab/projects/group%2Fapp/merge_requests/7")
    assert_that(
        encoded_upstream_path(request, "gitlab", "projects/group/app/merge_requests/7"),
        equal_to("projects/group%2Fapp/merge_requests/7"),
    )


def test_a_raw_path_that_does_not_match_the_route_is_ignored():
    request = _route_request(b"/gateway/v1/p/gitlab/projects/other")
    assert_that(encoded_upstream_path(request, "gitlab", "projects/group/app"), equal_to(None))


def test_a_missing_raw_path_is_ignored():
    request = MagicMock()
    request.scope = {}
    assert_that(encoded_upstream_path(request, "gitlab", "projects/1"), equal_to(None))


def test_a_real_request_keeps_the_encoded_slash_the_router_decodes():
    # Pins what the helper relies on: the router decoding %2F, and the ASGI scope not.
    app = FastAPI()

    @app.get("/gateway/v1/p/{provider_key}/{upstream_path:path}")
    def forward(provider_key: str, upstream_path: str, request: Request) -> dict[str, str | None]:
        return {
            "decoded": upstream_path,
            "encoded": encoded_upstream_path(request, provider_key, upstream_path),
        }

    response = TestClient(app).get("/gateway/v1/p/gitlab/projects/group%2Fsub%2Fapp/repository/files/a%20b%2Fc.rs/raw")

    assert_that(response.json()["decoded"], equal_to("projects/group/sub/app/repository/files/a b/c.rs/raw"))
    assert_that(
        response.json()["encoded"],
        equal_to("projects/group%2Fsub%2Fapp/repository/files/a%20b%2Fc.rs/raw"),
    )

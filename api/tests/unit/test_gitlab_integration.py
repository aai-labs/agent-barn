"""GitLab as an Integration: gitlab.com by default, or a self-hosted instance."""

import socket
from unittest.mock import MagicMock, patch

import httpx
import pytest
from hamcrest import assert_that, contains_string, equal_to, is_, is_not
from pydantic import ValidationError

from api.domains.agents.models import GitlabContent, SecretProvider
from api.domains.credential_gateway.forwarding import sanitize_response_headers
from api.domains.integrations.plugins.base import EgressMode, OutboundRequest
from api.domains.integrations.plugins.providers import GitlabPlugin
from api.domains.integrations.plugins.registry import INTEGRATION_PLUGINS
from api.infrastructure.integration_validators.gitlab import validate_gitlab

_PLUGIN = GitlabPlugin()
_SELF_HOSTED = GitlabContent(
    base_url="https://gitlab.example.com", token="glpat-real", repos=["group/sub/app", "group/lib"]
)


def _resolves_to(address: str):
    return patch(
        "api.infrastructure.public_http.socket.getaddrinfo",
        return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
    )


def _gitlab_answers(response: httpx.Response):
    client = MagicMock()
    client.__enter__.return_value = client
    client.request.return_value = response
    return client, patch("api.infrastructure.integration_validators.gitlab.httpx.Client", return_value=client)


# --- credential model ---


def test_the_instance_defaults_to_gitlab_com():
    assert_that(GitlabContent(token="t").base_url, equal_to("https://gitlab.com"))


def test_a_blank_instance_means_gitlab_com():
    assert_that(GitlabContent(base_url="  ", token="t").base_url, equal_to("https://gitlab.com"))


@pytest.mark.parametrize(
    ("given", "stored"),
    [
        ("https://gitlab.example.com/", "https://gitlab.example.com"),
        ("https://GitLab.Example.com", "https://gitlab.example.com"),
        ("  https://gitlab.example.com:8443  ", "https://gitlab.example.com:8443"),
    ],
)
def test_the_instance_is_reduced_to_an_https_origin(given, stored):
    assert_that(GitlabContent(base_url=given, token="t").base_url, equal_to(stored))


@pytest.mark.parametrize(
    "url",
    [
        "http://gitlab.example.com",
        "gitlab.example.com",
        "https://user:pass@gitlab.example.com",
        "https://gitlab.example.com/gitlab",
        "https://gitlab.example.com/api/v4",
        "https://gitlab.example.com?x=1",
        "https://gitlab.example.com#x",
        "https://localhost",
        "https://gitlab.localhost",
        "https://",
    ],
)
def test_anything_but_an_https_origin_is_rejected(url):
    with pytest.raises(ValidationError):
        GitlabContent(base_url=url, token="t")


def test_a_blank_token_is_rejected():
    with pytest.raises(ValidationError):
        GitlabContent(token="   ")


def test_a_legacy_singular_repo_still_reads():
    assert_that(GitlabContent.model_validate({"token": "t", "repo": "group/app"}).repos, equal_to(["group/app"]))


# --- live validation ---


def test_a_private_instance_is_refused_without_sending_the_token():
    client, http = _gitlab_answers(httpx.Response(200, json={"username": "x"}))
    with _resolves_to("10.0.0.5"), http:
        result = validate_gitlab(_SELF_HOSTED)
    assert_that(result.valid, is_(False))
    assert_that(result.error or "", contains_string("public"))
    client.request.assert_not_called()


def test_an_instance_that_does_not_resolve_is_refused():
    with patch("api.infrastructure.public_http.socket.getaddrinfo", side_effect=socket.gaierror):
        result = validate_gitlab(_SELF_HOSTED)
    assert_that(result.valid, is_(False))


def test_a_valid_token_reports_who_it_is_over_the_pinned_address():
    client, http = _gitlab_answers(httpx.Response(200, json={"username": "bot", "name": "Review Bot"}))
    with _resolves_to("8.8.8.8"), http:
        result = validate_gitlab(_SELF_HOSTED)
    assert_that(result.valid, is_(True))
    assert_that(result.identity, equal_to("Review Bot (@bot)"))
    args, kwargs = client.request.call_args_list[0]
    assert_that(args, equal_to(("GET", "https://8.8.8.8/api/v4/user")))
    assert_that(kwargs["headers"]["Host"], equal_to("gitlab.example.com"))
    assert_that(kwargs["headers"]["Authorization"], equal_to("Bearer glpat-real"))
    assert_that(kwargs["extensions"], equal_to({"sni_hostname": "gitlab.example.com"}))


def test_a_token_that_can_only_read_its_profile_is_refused():
    # GET /user accepts read_user, which can't reach a single project.
    client, http = _gitlab_answers(httpx.Response(200))
    client.request.side_effect = [
        httpx.Response(200, json={"username": "bot", "name": "Review Bot"}),
        httpx.Response(403, json={"error": "insufficient_scope"}),
    ]
    with _resolves_to("8.8.8.8"), http:
        result = validate_gitlab(_SELF_HOSTED)
    assert_that(result.valid, is_(False))
    assert_that(result.error or "", contains_string("read_api"))


def test_a_failed_project_check_fails_validation():
    client, http = _gitlab_answers(httpx.Response(200))
    client.request.side_effect = [
        httpx.Response(200, json={"username": "bot", "name": "Review Bot"}),
        httpx.Response(500, json={}),
    ]
    with _resolves_to("8.8.8.8"), http:
        result = validate_gitlab(_SELF_HOSTED)
    assert_that(result.valid, is_(False))
    assert_that(result.error or "", contains_string("500"))


def test_a_host_name_that_cannot_be_looked_up_fails_validation():
    with patch(
        "api.infrastructure.public_http.socket.getaddrinfo", side_effect=UnicodeEncodeError("idna", "x", 0, 1, "bad")
    ):
        result = validate_gitlab(_SELF_HOSTED)
    assert_that(result.valid, is_(False))


def test_redirects_are_not_followed():
    # A pinned client must not chase a Location to a host nobody checked.
    _, http = _gitlab_answers(httpx.Response(302, headers={"location": "https://internal.example/"}))
    with _resolves_to("8.8.8.8"), http as client_class:
        result = validate_gitlab(_SELF_HOSTED)
    assert_that(result.valid, is_(False))
    assert_that(client_class.call_args.kwargs["follow_redirects"], is_(False))


@pytest.mark.parametrize(
    ("status", "message"),
    [(401, "Invalid"), (403, "read_api"), (500, "500")],
)
def test_rejections_explain_themselves(status, message):
    _, http = _gitlab_answers(httpx.Response(status, json={}))
    with _resolves_to("8.8.8.8"), http:
        result = validate_gitlab(_SELF_HOSTED)
    assert_that(result.valid, is_(False))
    assert_that(result.error or "", contains_string(message))


def test_a_site_that_is_not_gitlab_fails_rather_than_passing():
    _, http = _gitlab_answers(httpx.Response(200, text="<html>hello</html>"))
    with _resolves_to("8.8.8.8"), http:
        result = validate_gitlab(_SELF_HOSTED)
    assert_that(result.valid, is_(False))


def test_network_failures_do_not_reveal_the_cause():
    # The URL is user-supplied, so the error must not become a port-scanning oracle.
    client, http = _gitlab_answers(httpx.Response(200))
    client.request.side_effect = httpx.ConnectError("connection refused to 8.8.8.8:8443")
    with _resolves_to("8.8.8.8"), http:
        result = validate_gitlab(_SELF_HOSTED)
    assert_that(result.valid, is_(False))
    assert_that(result.error or "", is_not(contains_string("refused")))


# --- plugin ---


def test_the_plugin_is_registered_and_gateway_routed_with_both_safeguards():
    assert_that(INTEGRATION_PLUGINS.require(SecretProvider.GITLAB).key, equal_to("gitlab"))
    assert_that(_PLUGIN.egress_mode, equal_to(EgressMode.GATEWAY_PROXY))
    assert_that(_PLUGIN.upstream_public_only, is_(True))
    assert_that(_PLUGIN.preserve_encoded_path, is_(True))
    assert_that(_PLUGIN.shared_credential_eligible, is_(True))


def test_the_upstream_is_the_instance_api_root():
    assert_that(_PLUGIN.upstream_base_url(_SELF_HOSTED), equal_to("https://gitlab.example.com/api/v4"))


def test_upstream_auth_is_the_real_bearer_token():
    outbound = _PLUGIN.apply_upstream_auth(_SELF_HOSTED, OutboundRequest("GET", "projects/1"))
    assert_that(outbound.headers["Authorization"], equal_to("Bearer glpat-real"))


def test_direct_profiles_carry_the_api_root_and_one_profile_per_project():
    block = _PLUGIN.aai_cli_profile_block(_SELF_HOSTED)
    assert_that(block, contains_string("[profiles.gitlab-work]"))
    assert_that(block, contains_string("[profiles.gitlab-work-2]"))
    assert_that(block, contains_string('provider = "gitlab"'))
    assert_that(block, contains_string('auth_type = "bearer_token"'))
    assert_that(block, contains_string('base_url = "https://gitlab.example.com/api/v4"'))
    assert_that(block, contains_string('repo = "group/sub/app"'))
    assert_that(block, contains_string('token_secret = "gitlab.token"'))


def test_gateway_profiles_never_hold_the_token_or_the_real_host():
    block = _PLUGIN.aai_cli_gateway_profile_block(
        _SELF_HOSTED, base_url="https://gateway.local/gateway/v1/p/gitlab", token_env="AAI_GATEWAY_TOKEN"
    )
    assert_that(block, contains_string('provider = "gitlab"'))
    assert_that(block, contains_string('base_url = "https://gateway.local/gateway/v1/p/gitlab"'))
    assert_that(block, contains_string('repo = "group/sub/app"'))
    assert_that(block, is_not(contains_string("glpat-real")))
    assert_that(block, is_not(contains_string("gitlab.example.com")))
    assert_that(block, is_not(contains_string("token_secret")))


def test_agents_are_told_the_gitlab_flag_not_the_github_one():
    unscoped = GitlabContent(token="t")
    assert_that(_PLUGIN.aai_cli_policy_line(unscoped), contains_string("--project"))
    assert_that(_PLUGIN.aai_cli_policy_line(unscoped), is_not(contains_string("--repo")))
    assert_that(_PLUGIN.aai_cli_context_line(unscoped), contains_string("--project"))
    assert_that(_PLUGIN.aai_cli_context_line(unscoped), is_not(contains_string("--repo")))


def test_agents_see_which_profile_is_which_project():
    assert_that(
        _PLUGIN.aai_cli_policy_line(_SELF_HOSTED),
        contains_string("`--profile gitlab-work-2` → group/lib"),
    )
    assert_that(_PLUGIN.aai_cli_context_line(_SELF_HOSTED), contains_string("gitlab.example.com"))


def test_pagination_headers_survive_the_gateway():
    headers = sanitize_response_headers({"x-next-page": "2", "x-total-pages": "3", "Content-Length": "9"})
    assert_that(headers, equal_to({"x-next-page": "2", "x-total-pages": "3"}))

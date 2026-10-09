"""The Graph calls that grant and revoke an app's access to one SharePoint site."""

import httpx
import pytest
from hamcrest import assert_that, equal_to

from api.domains.agents.microsoft_graph_sites import (
    MicrosoftGraphSites,
    SiteAccessRefused,
    SiteChangeRejected,
    SiteNotFound,
    SitesThrottled,
    SitesUnavailable,
)

_GRAPH = "https://graph.microsoft.com/v1.0"
_APP_ID = "5ff671c1-57c7-44ef-a7b5-8fe4f81227f9"


class _Recorder:
    def __init__(self, *responses: httpx.Response | Exception):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, method, url, headers, json=None, timeout=None):
        self.calls.append({"method": method, "url": url, "headers": headers, "json": json})
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def graph(monkeypatch):
    def install(*responses):
        recorder = _Recorder(*responses)
        monkeypatch.setattr(httpx, "request", recorder)
        return recorder

    return install


def test_a_site_is_looked_up_by_host_and_path(graph):
    recorder = graph(httpx.Response(200, json={"id": "contoso.sharepoint.com,aaa,bbb"}))

    site_id = MicrosoftGraphSites().resolve_site_id("admin-token", "https://contoso.sharepoint.com/sites/finance")

    assert_that(site_id, equal_to("contoso.sharepoint.com,aaa,bbb"))
    assert_that(recorder.calls[0]["method"], equal_to("GET"))
    assert_that(recorder.calls[0]["url"], equal_to(f"{_GRAPH}/sites/contoso.sharepoint.com:/sites/finance"))
    assert_that(recorder.calls[0]["headers"], equal_to({"Authorization": "Bearer admin-token"}))


def test_an_unknown_site_is_reported_by_its_address(graph):
    graph(httpx.Response(404, json={"error": {"code": "itemNotFound"}}))

    with pytest.raises(SiteNotFound) as exc:
        MicrosoftGraphSites().resolve_site_id("admin-token", "https://contoso.sharepoint.com/sites/nope")

    # The address people typed, never Graph's own path.
    assert_that(str(exc.value), equal_to("https://contoso.sharepoint.com/sites/nope"))


def test_granting_names_the_app_and_the_role(graph):
    recorder = graph(httpx.Response(201, json={"id": "perm-1", "roles": ["write"]}))

    permission_id = MicrosoftGraphSites().grant_site(
        "admin-token", site_id="site-1", app_id=_APP_ID, display_name="Agent Barn", role="write"
    )

    assert_that(permission_id, equal_to("perm-1"))
    call = recorder.calls[0]
    assert_that(call["method"], equal_to("POST"))
    assert_that(call["url"], equal_to(f"{_GRAPH}/sites/site-1/permissions"))
    assert_that(
        call["json"],
        equal_to(
            {
                "roles": ["write"],
                "grantedToIdentities": [{"application": {"id": _APP_ID, "displayName": "Agent Barn"}}],
            }
        ),
    )


def test_a_grant_refused_by_microsoft_is_reported_as_refused(graph):
    # What a non-administrator gets: their token can't manage site permissions.
    graph(httpx.Response(403, json={"error": {"code": "accessDenied"}}))

    with pytest.raises(SiteAccessRefused):
        MicrosoftGraphSites().grant_site("t", site_id="site-1", app_id=_APP_ID, display_name="x", role="read")


def test_changing_a_grants_role_updates_it_in_place(graph):
    recorder = graph(httpx.Response(200, json={"id": "perm-1", "roles": ["read"]}))

    MicrosoftGraphSites().update_site_role("admin-token", site_id="site-1", permission_id="perm-1", role="read")

    call = recorder.calls[0]
    assert_that(call["method"], equal_to("PATCH"))
    assert_that(call["url"], equal_to(f"{_GRAPH}/sites/site-1/permissions/perm-1"))
    assert_that(call["json"], equal_to({"roles": ["read"]}))


def test_revoking_deletes_the_grant(graph):
    recorder = graph(httpx.Response(204))

    MicrosoftGraphSites().revoke_site("admin-token", site_id="site-1", permission_id="perm-1")

    assert_that(recorder.calls[0]["method"], equal_to("DELETE"))
    assert_that(recorder.calls[0]["url"], equal_to(f"{_GRAPH}/sites/site-1/permissions/perm-1"))


def test_revoking_a_grant_that_is_already_gone_succeeds(graph):
    graph(httpx.Response(404, json={"error": {"code": "itemNotFound"}}))

    MicrosoftGraphSites().revoke_site("admin-token", site_id="site-1", permission_id="perm-1")


@pytest.mark.parametrize("failure", [httpx.ConnectError("boom"), httpx.Response(503, json={})])
def test_an_unreachable_graph_is_reported_as_unavailable(graph, failure):
    graph(failure)

    with pytest.raises(SitesUnavailable):
        MicrosoftGraphSites().resolve_site_id("t", "https://contoso.sharepoint.com/sites/finance")


@pytest.mark.parametrize("status_code", [400, 409])
def test_a_change_microsoft_rejects_is_reported_as_rejected(graph, status_code):
    graph(httpx.Response(status_code, json={"error": {"code": "invalidRequest"}}))

    with pytest.raises(SiteChangeRejected):
        MicrosoftGraphSites().grant_site("t", site_id="site-1", app_id=_APP_ID, display_name="x", role="read")


def test_an_address_microsoft_cant_use_is_reported_as_not_found(graph):
    graph(httpx.Response(400, json={"error": {"code": "invalidRequest"}}))

    with pytest.raises(SiteNotFound) as exc:
        MicrosoftGraphSites().resolve_site_id("t", "https://contoso.sharepoint.com/sites/finance")

    assert_that(str(exc.value), equal_to("https://contoso.sharepoint.com/sites/finance"))


def test_throttling_is_reported_as_throttled(graph):
    graph(httpx.Response(429, headers={"Retry-After": "30"}, json={}))

    with pytest.raises(SitesThrottled):
        MicrosoftGraphSites().update_site_role("t", site_id="site-1", permission_id="perm-1", role="read")


def test_rejected_and_throttled_still_count_as_unavailable_for_rollback(graph):
    # Callers that undo an attempt on any Graph failure keep catching SitesUnavailable.
    assert_that(issubclass(SiteChangeRejected, SitesUnavailable), equal_to(True))
    assert_that(issubclass(SitesThrottled, SitesUnavailable), equal_to(True))

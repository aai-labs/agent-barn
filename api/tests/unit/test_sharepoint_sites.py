import pytest

from api.domains.agents.sharepoint_sites import normalize_site_url, site_graph_path


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://Contoso.SharePoint.com/sites/Finance", "https://contoso.sharepoint.com/sites/Finance"),
        (
            "https://contoso.sharepoint.com/sites/finance/Shared%20Documents/Forms/AllItems.aspx",
            "https://contoso.sharepoint.com/sites/finance",
        ),
        ("https://contoso.sharepoint.com/TEAMS/ops/", "https://contoso.sharepoint.com/teams/ops"),
        ("  https://contoso.sharepoint.com/  ", "https://contoso.sharepoint.com"),
    ],
)
def test_site_urls_are_reduced_to_the_site_root(raw, expected):
    assert normalize_site_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "http://contoso.sharepoint.com/sites/finance",
        "https://contoso.example.com/sites/finance",
        "https://contoso.sharepoint.com/sites/",
        "not a url",
    ],
)
def test_anything_but_a_sharepoint_online_site_is_refused(raw):
    with pytest.raises(ValueError):
        normalize_site_url(raw)


def test_graph_addresses_a_site_by_host_and_path():
    assert site_graph_path("https://contoso.sharepoint.com/sites/Q3 plan") == "contoso.sharepoint.com:/sites/Q3%20plan"


def test_graph_addresses_the_root_site_by_host_alone():
    assert site_graph_path("https://contoso.sharepoint.com") == "contoso.sharepoint.com"

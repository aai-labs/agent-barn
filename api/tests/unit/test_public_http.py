"""Pinning an outbound request to an address that was checked to be public."""

import socket
from unittest.mock import patch

import pytest
from hamcrest import assert_that, equal_to

from api.infrastructure.public_http import NonPublicDestination, pin_to_public_address, public_addresses


def _resolves_to(*addresses: str):
    rows = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443)) for address in addresses]
    return patch("api.infrastructure.public_http.socket.getaddrinfo", return_value=rows)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",  # cloud metadata
        "100.64.0.1",  # carrier-grade NAT
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fd00::1",
        "fe80::1",
        "::ffff:10.0.0.1",
    ],
)
def test_non_public_addresses_are_refused(address):
    with _resolves_to(address), pytest.raises(NonPublicDestination):
        public_addresses("gitlab.example.com")


def test_one_private_answer_among_public_ones_refuses_the_host():
    # A resolver is free to return them in any order, so picking "the public one" would
    # still let the client reach the private address.
    with _resolves_to("8.8.8.8", "10.0.0.5"), pytest.raises(NonPublicDestination):
        public_addresses("gitlab.example.com")


def test_a_host_that_does_not_resolve_is_refused():
    with (
        patch("api.infrastructure.public_http.socket.getaddrinfo", side_effect=socket.gaierror),
        pytest.raises(NonPublicDestination),
    ):
        pin_to_public_address("https://nope.example/api/v4/user")


def test_plain_http_is_refused_before_resolving():
    with (
        patch("api.infrastructure.public_http.socket.getaddrinfo") as resolve,
        pytest.raises(NonPublicDestination),
    ):
        pin_to_public_address("http://gitlab.example.com/api/v4/user")
    resolve.assert_not_called()


def test_the_connection_is_pinned_while_tls_and_host_keep_the_name():
    with _resolves_to("8.8.8.8"):
        pinned = pin_to_public_address("https://gitlab.example.com/api/v4/projects/group%2Fapp?x=1")
    assert_that(pinned.url, equal_to("https://8.8.8.8/api/v4/projects/group%2Fapp?x=1"))
    assert_that(pinned.headers, equal_to({"Host": "gitlab.example.com"}))
    assert_that(pinned.extensions, equal_to({"sni_hostname": "gitlab.example.com"}))


def test_a_custom_port_stays_in_the_url_and_the_host_header():
    with _resolves_to("8.8.8.8"):
        pinned = pin_to_public_address("https://gitlab.example.com:8443/api/v4/user")
    assert_that(pinned.url, equal_to("https://8.8.8.8:8443/api/v4/user"))
    assert_that(pinned.headers, equal_to({"Host": "gitlab.example.com:8443"}))


def test_an_ipv6_answer_is_pinned_in_brackets():
    with _resolves_to("2606:4700:4700::1111"):
        pinned = pin_to_public_address("https://gitlab.example.com/api/v4/user")
    assert_that(pinned.url, equal_to("https://[2606:4700:4700::1111]/api/v4/user"))


def test_a_dual_stack_host_is_pinned_to_ipv4():
    # A pod without IPv6 can't reach an AAAA answer, and only one address is tried.
    with _resolves_to("2606:4700:4700::1111", "8.8.8.8"):
        pinned = pin_to_public_address("https://gitlab.example.com/api/v4/user")
    assert_that(pinned.url, equal_to("https://8.8.8.8/api/v4/user"))


@pytest.mark.parametrize("url", ["https://a..b/api/v4/user", f"https://{'a' * 64}.example.com/", "https://[bad/"])
def test_a_host_that_cannot_be_looked_up_is_refused(url):
    with pytest.raises(NonPublicDestination):
        pin_to_public_address(url)

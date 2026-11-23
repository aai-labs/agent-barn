from typing import Any

import pytest
from hamcrest import assert_that, empty, equal_to

from api.domains.anomalies.destinations import destination_hosts

# Argument shapes are taken from the tool definitions at the runtime versions the
# images pin (openclaw 2026.8.2, hermes v2026.8.19) and from recorded tool calls.


@pytest.mark.parametrize(
    ("tool_name", "arguments", "expected"),
    [
        # openclaw web_fetch: `url` string
        ("web_fetch", {"url": "https://Docs.Example.com/page?q=1", "extractMode": "markdown"}, {"docs.example.com"}),
        # hermes web_extract: `urls` list of strings
        (
            "web_extract",
            {"urls": ["https://a.example.com/x", "http://b.example.org:8080/y"], "char_limit": 4000},
            {"a.example.com", "b.example.org"},
        ),
        # openclaw browser: `targetUrl` on open/navigate, `url` as the fallback the handler reads
        ("browser", {"action": "open", "targetUrl": "https://shop.example.com/"}, {"shop.example.com"}),
        ("browser", {"action": "navigate", "url": "https://shop.example.com/cart"}, {"shop.example.com"}),
        (
            "browser",
            {"action": "navigate", "targetUrl": "https://first.example.com", "url": "https://second.example.com"},
            {"first.example.com"},
        ),
        # hermes browser_navigate: `url` string
        ("browser_navigate", {"url": "https://news.example.net/today"}, {"news.example.net"}),
        # userinfo and port never reach the stored host
        ("web_fetch", {"url": "https://user:secret@api.example.com:8443/v1"}, {"api.example.com"}),
        # IPv6 literal
        ("web_fetch", {"url": "http://[2001:db8::1]:8080/"}, {"2001:db8::1"}),
    ],
)
def test_page_fetch_and_browser_tools_yield_hosts(tool_name: str, arguments: dict[str, Any], expected: set[str]):
    assert_that(destination_hosts(tool_name, arguments), equal_to(expected))


@pytest.mark.parametrize(
    ("tool_name", "arguments"),
    [
        # browser actions that do not load a URL; `url` here is the wait act's argument
        ("browser", {"action": "act", "url": "https://elsewhere.example.com"}),
        ("browser", {"action": "snapshot"}),
        # search carries a query, never a destination
        ("web_search", {"query": "https://example.com"}),
        # hermes browser_exec runs code; any URL inside it is not parsed
        ("browser_exec", {"code": "page.goto('https://example.com')"}),
        # malformed or hostile shapes
        ("web_fetch", {"url": 42}),
        ("web_fetch", {"url": "not a url"}),
        ("web_fetch", {"url": "file:///etc/passwd"}),
        ("web_fetch", {"url": "https://$HOST/path"}),
        ("web_extract", {"urls": "https://example.com"}),
        ("web_extract", {"urls": [None, 7]}),
        ("web_fetch", "https://example.com"),
        ("unknown_tool", {"url": "https://example.com"}),
    ],
)
def test_calls_without_a_parseable_destination_yield_nothing(tool_name: str, arguments: Any):
    assert_that(destination_hosts(tool_name, arguments), empty())


@pytest.mark.parametrize("tool_name", ["exec", "terminal"])
@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("curl -s https://api.example.com/v1/items", {"api.example.com"}),
        ("curl -H 'Accept: application/json' -o out.json https://api.example.com/x", {"api.example.com"}),
        ("wget -qO- http://files.example.org/a.tar.gz | tar xz", {"files.example.org"}),
        ("/usr/bin/curl --url https://abs.example.com", {"abs.example.com"}),
        ("TOKEN=x curl https://env.example.com", {"env.example.com"}),
        (
            "cd /tmp && curl https://one.example.com; wget https://two.example.com",
            {"one.example.com", "two.example.com"},
        ),
        ("curl https://a.example.com https://b.example.com", {"a.example.com", "b.example.com"}),
        # a URL that is not an argument to curl or wget is not a destination
        ("echo https://not-fetched.example.com", set()),
        ("git clone https://git.example.com/repo.git", set()),
        # the request URL given to an option, not as an argument of its own
        ("curl --url=https://inline.example.com", {"inline.example.com"}),
        ("curl -- https://after-dashes.example.com", {"after-dashes.example.com"}),
        # option values are not destinations, even when they look like URLs
        ("curl --referer https://referrer.example https://actual.example", {"actual.example"}),
        ("curl --referer=https://referrer.example https://actual.example", {"actual.example"}),
        ("curl -e https://referrer.example https://actual.example", {"actual.example"}),
        ("curl -sSLe https://referrer.example https://actual.example", {"actual.example"}),
        ("curl -x http://proxy.example:3128 https://actual.example", {"actual.example"}),
        ("curl -d https://posted.example https://actual.example", {"actual.example"}),
        ("curl -H 'Origin: https://origin.example' https://actual.example", {"actual.example"}),
        # curl's -O takes no value (it names the file after the URL); wget's does
        ("curl -O https://remote-name.example/file.zip", {"remote-name.example"}),
        ("wget -O https://named.example https://actual.example", {"actual.example"}),
        ("wget --referer https://referrer.example https://actual.example", {"actual.example"}),
        # scheme-less hosts are not taken: option values like `-o out.json` look the same
        ("curl example.com", set()),
        # unbalanced quoting cannot be tokenized
        ("curl 'https://broken.example.com", set()),
    ],
)
def test_curl_and_wget_in_shell_commands_yield_hosts(tool_name: str, command: str, expected: set[str]):
    assert_that(destination_hosts(tool_name, {"command": command}), equal_to(expected))


def test_wrapped_hermes_commands_are_unwrapped():
    command = (
        "AGENTBARN_TOOL_SESSION=s AGENTBARN_TOOL_INVOCATION=i sh -c 'curl -fsS https://wrapped.example.com/health'"
    )

    assert_that(destination_hosts("terminal", {"command": command}), equal_to({"wrapped.example.com"}))


def test_shell_tools_without_a_command_yield_nothing():
    assert_that(destination_hosts("exec", {"workdir": "/tmp"}), empty())

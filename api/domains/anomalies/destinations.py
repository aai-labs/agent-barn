"""The hosts an Agent's tool calls reach, read from the tool call arguments.

Field names come from the tool definitions at the runtime versions the images pin
(openclaw 2026.8.2, hermes v2026.8.19). Only the host is returned: arguments can hold
customer data, so nothing else from them is kept.

Not covered, and so never a destination here:
- hermes `browser_exec` and `execute_code`, whose URLs sit inside code. Hermes after
  the pinned version drops `browser_navigate` for `browser_exec`, so a Hermes image
  bump stops browser destinations being seen.
- traffic from inside scripts and libraries
- scheme-less URLs in shell commands (`curl example.com`), which cannot be told
  apart from option values such as `-o out.json`
- the value of a curl or wget option missing from the lists below, when it looks
  like a URL: it is taken as a request URL
"""

import re
from typing import Any
from urllib.parse import urlsplit

from api.domains.business_value.service import is_shell_tool, shell_invocations

WEB_SCHEMES = frozenset({"http", "https"})
# The options of each fetcher that take a value, as the next argument or (for a short
# option) the rest of its cluster. Their values are never the request URL, even when
# they look like one (`--referer https://…`, `-x http://proxy:3128`, `-d https://…`).
# The two disagree on some letters: curl's `-O` takes no value, wget's does.
FETCHER_VALUE_OPTIONS = {
    "curl": frozenset(
        [
            "-A",
            "-b",
            "-c",
            "-C",
            "-d",
            "-D",
            "-E",
            "-e",
            "-F",
            "-H",
            "-K",
            "-m",
            "-o",
            "-P",
            "-Q",
            "-r",
            "-T",
            "-t",
            "-u",
            "-U",
            "-w",
            "-x",
            "-X",
            "-y",
            "-Y",
            "-z",
            "--aws-sigv4",
            "--cacert",
            "--capath",
            "--cert",
            "--config",
            "--connect-timeout",
            "--connect-to",
            "--cookie",
            "--cookie-jar",
            "--data",
            "--data-ascii",
            "--data-binary",
            "--data-raw",
            "--data-urlencode",
            "--doh-url",
            "--form",
            "--form-string",
            "--header",
            "--interface",
            "--json",
            "--key",
            "--max-time",
            "--noproxy",
            "--oauth2-bearer",
            "--output",
            "--output-dir",
            "--preproxy",
            "--proxy",
            "--proxy-header",
            "--proxy-user",
            "--range",
            "--referer",
            "--request",
            "--resolve",
            "--retry",
            "--upload-file",
            "--url-query",
            "--user",
            "--user-agent",
            "--variable",
            "--write-out",
        ]
    ),
    "wget": frozenset(
        [
            "-a",
            "-A",
            "-B",
            "-D",
            "-e",
            "-i",
            "-I",
            "-l",
            "-o",
            "-O",
            "-P",
            "-Q",
            "-R",
            "-t",
            "-T",
            "-U",
            "-w",
            "-X",
            "--accept",
            "--append-output",
            "--base",
            "--bind-address",
            "--body-data",
            "--ca-certificate",
            "--certificate",
            "--directory-prefix",
            "--domains",
            "--execute",
            "--header",
            "--http-password",
            "--http-user",
            "--input-file",
            "--level",
            "--load-cookies",
            "--method",
            "--output-document",
            "--output-file",
            "--password",
            "--post-data",
            "--post-file",
            "--private-key",
            "--proxy-password",
            "--proxy-user",
            "--quota",
            "--referer",
            "--reject",
            "--save-cookies",
            "--timeout",
            "--tries",
            "--user",
            "--user-agent",
            "--wait",
        ]
    ),
}
# curl's option for a request URL given as an option rather than an argument.
URL_OPTION = "--url"
OPENCLAW_BROWSER_LOADS = frozenset({"open", "navigate"})
HOST = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)*[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$|^[0-9a-f:.]+$")


def destination_hosts(tool_name: str, arguments: Any) -> set[str]:
    if not isinstance(arguments, dict):
        return set()
    return {host for url in _urls(tool_name, arguments) if (host := _host(url)) is not None}


def _urls(tool_name: str, arguments: dict[str, Any]) -> list[Any]:
    if tool_name in {"web_fetch", "browser_navigate"}:
        return [arguments.get("url")]
    if tool_name == "web_extract":
        urls = arguments.get("urls")
        return urls if isinstance(urls, list) else []
    if tool_name == "browser":
        if arguments.get("action") not in OPENCLAW_BROWSER_LOADS:
            return []
        return [arguments.get("targetUrl") or arguments.get("url")]
    if is_shell_tool(tool_name):
        command = arguments.get("command")
        if not isinstance(command, str):
            return []
        return [
            url
            for fetcher, value_options in FETCHER_VALUE_OPTIONS.items()
            for arguments in shell_invocations(command, frozenset({fetcher}))
            for url in _request_urls(arguments, value_options)
        ]
    return []


def _request_urls(arguments: list[str], value_options: frozenset[str]) -> list[str]:
    """A fetcher's request URL candidates: its arguments that are not options or
    option values, and `--url`'s value."""
    urls: list[str] = []
    tokens = iter(arguments)
    for token in tokens:
        if token == "--":
            urls.extend(tokens)
        elif token.startswith("--"):
            name, inline, value = token.partition("=")
            if name == URL_OPTION:
                urls.append(value if inline else next(tokens, ""))
            elif not inline and name in value_options:
                next(tokens, None)
        elif token.startswith("-") and len(token) > 1:
            # A cluster of short options (`-sSLe ref`): the first that takes a value
            # takes the rest of the cluster, or the next argument if nothing is left.
            for index, letter in enumerate(token[1:], start=2):
                if f"-{letter}" in value_options:
                    if index == len(token):
                        next(tokens, None)
                    break
        else:
            urls.append(token)
    return urls


def _host(url: Any) -> str | None:
    if not isinstance(url, str):
        return None
    try:
        parts = urlsplit(url.strip())
        host = parts.hostname
    except ValueError:
        return None
    if parts.scheme.lower() not in WEB_SCHEMES or not host or not HOST.match(host):
        return None
    return host

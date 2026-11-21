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
  apart from option values such as `-o out.json` without cataloguing every flag
"""

import re
from typing import Any
from urllib.parse import urlsplit

from api.domains.business_value.service import is_shell_tool, shell_invocations

WEB_SCHEMES = frozenset({"http", "https"})
SHELL_FETCHERS = frozenset({"curl", "wget"})
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
        return [token for invocation in shell_invocations(command, SHELL_FETCHERS) for token in invocation]
    return []


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

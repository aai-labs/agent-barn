"""Shared, stdlib-only request engine, also mounted into both Agent runtimes."""

import base64
import http.client
import ipaddress
import json
import re
import socket
import ssl
from urllib.parse import unquote, urlencode, urlsplit

MAX_BYTES = 1024 * 1024
BLOCKED_HEADERS = frozenset(
    {
        "host",
        "authorization",
        "proxy-authorization",
        "connection",
        "content-length",
        "transfer-encoding",
        "upgrade",
        "te",
        "trailer",
        "keep-alive",
        "proxy-connection",
    }
)


class RequestRefused(ValueError):
    pass


def parse_url(value: str, *, base: bool = False):
    """Accept one unambiguous HTTPS URL; paths deliberately exclude escapes."""
    if not isinstance(value, str) or not value or re.search(r"[\s\\\x00-\x1f\x7f]", value):
        raise RequestRefused("An absolute HTTPS URL is required")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise RequestRefused("Invalid URL") from None
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or (base and parsed.query)
        or port not in (None, 443)
        or parsed.hostname.endswith(".")
    ):
        raise RequestRefused("Use a public HTTPS URL on port 443 without credentials or fragments")
    if not re.fullmatch(r"[a-zA-Z0-9.-]+", parsed.hostname):
        raise RequestRefused("Use an ASCII DNS hostname or public IPv4 address")
    path = parsed.path or "/"
    decoded = unquote(path, errors="strict")
    if (
        re.search(r"%(?![0-9a-fA-F]{2})", path)
        or "%" in decoded
        or "\\" in decoded
        or len(path.split("/")) != len(decoded.split("/"))
        or "//" in decoded
        or any(part in {".", ".."} for part in decoded.split("/"))
        or any(ord(c) < 32 or ord(c) == 127 for c in decoded)
    ):
        raise RequestRefused("Escaped, duplicate-slash and dot-segment paths are unsupported")
    return parsed


def check_scope(base_url: str, url: str) -> None:
    base = parse_url(base_url, base=True)
    target = parse_url(url)
    root = unquote(base.path).rstrip("/")
    target_path = unquote(target.path)
    if base.hostname != target.hostname or (root and target_path != root and not target_path.startswith(root + "/")):
        raise RequestRefused("URL is outside the configured origin and base path")


def public_addresses(host: str) -> list[str]:
    addresses = sorted({str(row[4][0]) for row in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)})
    if not addresses:
        raise RequestRefused("Destination has no public address")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_reserved or getattr(ip, "ipv4_mapped", None):
            raise RequestRefused("Private, internal and special network destinations are unsupported")
    return addresses


def header_value(value: str) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) > 126 for c in value):
        raise RequestRefused("Header values must be nonempty printable ASCII")
    return value


def header_name(name: str) -> str:
    if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) or name.lower() in BLOCKED_HEADERS:
        raise RequestRefused("Invalid or reserved header name")
    return name


def credential_headers(config: dict) -> tuple[dict[str, str], list[str]]:
    headers: dict[str, str] = {}
    sensitive: list[str] = []
    auth = config.get("auth", {})
    kind = auth.get("type", "none")
    if kind == "bearer":
        headers["authorization"] = "Bearer " + header_value(auth["token"])
        sensitive.append(auth["token"])
    elif kind == "api_key":
        name = auth["header_name"]
        if name.lower() != "authorization":
            header_name(name)
        headers[name.lower()] = header_value(auth["token"])
        sensitive.append(auth["token"])
    elif kind == "basic":
        user = header_value(auth["username"])
        password = header_value(auth["password"])
        if ":" in user:
            raise RequestRefused("Basic auth username cannot contain a colon")
        encoded = base64.b64encode(f"{user}:{password}".encode()).decode()
        headers["authorization"] = "Basic " + encoded
        sensitive.extend([password, encoded])
    elif kind != "none":
        raise RequestRefused("Unsupported authentication type")
    for item in config.get("headers", []):
        name = header_name(item["name"]).lower()
        if name in headers:
            raise RequestRefused("Duplicate configured header")
        headers[name] = header_value(item["value"])
        if item.get("secret"):
            sensitive.append(item["value"])
    sensitive.extend(headers[name] for name in headers if name == "authorization")
    return headers, sensitive


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, address: str):
        super().__init__(host, timeout=30, context=ssl.create_default_context())
        self.address = address
        self.tls_context = ssl.create_default_context()

    def connect(self):
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self.tls_context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def execute(config: dict, request: dict) -> dict:
    """Attach credentials only after scope validation and pin the validated DNS address."""
    url = request.get("url", "")
    check_scope(config["base_url"], url)
    parsed = parse_url(url)
    method = request.get("method", "GET").upper()
    if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"}:
        raise RequestRefused("Unsupported HTTP method")
    headers, sensitive = credential_headers(config)
    for item in request.get("headers", []):
        name = header_name(item["name"]).lower()
        if name in headers:
            raise RequestRefused("Configured headers cannot be overridden")
        headers[name] = header_value(item["value"])
    query = request.get("query", {})
    if not isinstance(query, dict):
        raise RequestRefused("Query must be an object")
    path = parsed.path or "/"
    combined_query = "&".join(part for part in [parsed.query, urlencode(query, doseq=True)] if part)
    if combined_query:
        path += "?" + combined_query
    body = request.get("body")
    if body is not None:
        if isinstance(body, str):
            body = body.encode()
        else:
            body = json.dumps(body).encode()
            headers.setdefault("content-type", "application/json")
        if len(body) > MAX_BYTES:
            raise RequestRefused("Request body exceeds 1 MiB")
    addresses = public_addresses(parsed.hostname)
    connection = PinnedHTTPSConnection(parsed.hostname, addresses[0])
    try:
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise RequestRefused("Redirects are not followed; use a URL within the configured scope")
        content = response.read(MAX_BYTES + 1)
        if len(content) > MAX_BYTES:
            raise RequestRefused("Response exceeds 1 MiB")
        text = content.decode("utf-8", errors="replace")
        for value in sorted(set(sensitive), key=len, reverse=True):
            text = text.replace(value, "[REDACTED]")
        try:
            result = json.loads(text)
        except ValueError:
            result = text
        return {"status": response.status, "body": result}
    finally:
        connection.close()

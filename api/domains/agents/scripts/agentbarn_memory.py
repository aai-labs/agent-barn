"""Explicit Organization Memory writer, shared by both Agent runtimes."""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from urllib.parse import urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Save a durable fact to Organization Memory.")
    parser.add_argument("command", choices=["remember-organization"])
    parser.parse_args()
    url = os.environ.get("MEMORY_URL", "").rstrip("/")
    key = os.environ.get("MEMORY_API_KEY", "")
    parts = urlsplit(url)
    if (
        not key
        or parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.username
        or parts.query
        or parts.fragment
    ):
        print("Agent Memory is not configured. Enable memory and restart this Agent.", file=sys.stderr)
        return 1
    raw = sys.stdin.read(100001)
    content = raw.strip()
    if not content or len(raw) > 100000:
        print("Provide between 1 and 100000 characters on standard input.", file=sys.stderr)
        return 1
    request = urllib.request.Request(
        url + "/organization-memory",
        data=json.dumps({"content": content}).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=20) as response:
            if response.status != 202 or json.loads(response.read(1024)).get("status") != "accepted":
                raise ValueError("Unexpected response")
    except urllib.error.HTTPError as exc:
        message = {
            403: "Organization Memory write access is required. Ask an Organization Owner or Admin to grant it.",
            401: "Agent Memory credential is unavailable or expired. Restart this Agent.",
            429: "Organization Memory save was refused by the Organization spend limit.",
        }.get(exc.code, "Organization Memory save could not be confirmed.")
        print(message, file=sys.stderr)
        return 1
    except (OSError, ValueError):
        print("Organization Memory save could not be confirmed.", file=sys.stderr)
        return 1
    print("Organization Memory save accepted. Processing is asynchronous.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Explicit memory search and Organization Memory saves for both Agent runtimes."""

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


def fail(message: str, *, recall: bool) -> int:
    if recall:
        print(json.dumps({"status": "unavailable"}))
    print(message, file=sys.stderr)
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Search accessible memory or save an Organization fact.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("remember-organization")
    search = commands.add_parser("recall")
    search.add_argument("--thorough", action="store_true", help="Use a larger budget for a focused retry.")
    args = parser.parse_args()
    recall = args.command == "recall"
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
        return fail("Agent Memory is not configured. Enable memory and restart this Agent.", recall=recall)
    limit = 20000 if recall else 100000
    raw = sys.stdin.read(limit + 1)
    content = raw.strip()
    if not content or len(raw) > limit:
        return fail(f"Provide between 1 and {limit} characters on standard input.", recall=recall)
    if recall:
        path = "/v1/default/banks/agentbarn/memories/recall"
        payload = {
            "query": content,
            "budget": "high" if args.thorough else "mid",
            "max_tokens": 8192 if args.thorough else 4096,
            "types": ["world", "experience", "observation"],
        }
    else:
        path, payload = "/organization-memory", {"content": content}
    request = urllib.request.Request(
        url + path,
        data=json.dumps(payload).encode(),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
        method="POST",
    )
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        with opener.open(request, timeout=20) as response:
            if recall:
                raw_response = response.read(1_000_001)
                if len(raw_response) > 1_000_000:
                    raise ValueError("Recall response too large")
                data = json.loads(raw_response)
                if response.status != 200 or not isinstance(data, dict) or not isinstance(data.get("results"), list):
                    raise ValueError("Unexpected recall response")
                memories = []
                for item in data["results"]:
                    if not isinstance(item, dict) or not isinstance(item.get("text"), str) or not item["text"].strip():
                        raise ValueError("Unexpected memory")
                    memories.append(item["text"])
                print(json.dumps({"status": "found" if memories else "not_found", "memories": memories}))
                return 0
            if response.status != 202 or json.loads(response.read(1024)).get("status") != "accepted":
                raise ValueError("Unexpected response")
    except urllib.error.HTTPError as exc:
        if recall:
            return fail("Agent Memory search is unavailable. No absence of a fact was established.", recall=True)
        message = {
            403: "Organization Memory write access is required. Ask an Organization Owner or Admin to grant it.",
            401: "Agent Memory credential is unavailable or expired. Restart this Agent.",
            429: "Organization Memory save was refused by the Organization spend limit.",
        }.get(exc.code, "Organization Memory save could not be confirmed.")
        return fail(message, recall=False)
    except (OSError, ValueError):
        return fail(
            "Agent Memory search is unavailable." if recall else "Organization Memory save could not be confirmed.",
            recall=recall,
        )
    print("Organization Memory save accepted. Processing is asynchronous.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

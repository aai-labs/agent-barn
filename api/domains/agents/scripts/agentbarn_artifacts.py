"""Shared artifact CLI for Hermes and OpenClaw. Uses only the scoped Agent service capability."""

import argparse
import hashlib
import json
import mimetypes
import os
import stat
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, urlsplit


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish, list, download or share private Agent files.")
    commands = parser.add_subparsers(dest="command", required=True)
    upload = commands.add_parser("upload")
    upload.add_argument("path")
    upload.add_argument("--attempt-id")
    listing = commands.add_parser("list")
    listing.add_argument("--page", type=int, default=1)
    for command in ("link", "retrieve"):
        sub = commands.add_parser(command)
        sub.add_argument("artifact_id")
        if command == "retrieve":
            sub.add_argument("destination")
        else:
            sub.add_argument("--seconds", type=int, default=900)
    args = parser.parse_args()
    base, token = os.environ.get("ARTIFACT_URL", "").rstrip("/"), os.environ.get("ARTIFACT_API_KEY", "")
    parts = urlsplit(base)
    if (
        not token
        or parts.scheme not in {"http", "https"}
        or not parts.netloc
        or parts.username
        or parts.query
        or parts.fragment
    ):
        print("Artifact storage is not configured. Text-only operation is available.", file=sys.stderr)
        return 1
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())

    def request(path, method="GET", body=None, extra=None):
        headers = {"Authorization": "Bearer " + token, **(extra or {})}
        req = urllib.request.Request(base + path, data=body, headers=headers, method=method)
        with opener.open(req, timeout=120) as response:
            return json.loads(response.read(2_000_000))

    try:
        if args.command == "upload":
            path = Path(args.path)
            roots = [
                Path(item).resolve()
                for item in os.environ.get("ARTIFACT_UPLOAD_ROOTS", str(Path.cwd())).split(":")
                if item
            ]
            resolved = path.resolve(strict=True)
            if not any(resolved.is_relative_to(root) for root in roots):
                raise ValueError("Upload file must be inside the configured workspace roots")
            # Resolve workspace paths, then reject final-component races and non-regular files.
            fd = os.open(resolved, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, "rb") as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                    raise ValueError("Upload requires a regular file")
                limit = int(os.environ.get("ARTIFACT_MAX_BYTES", str(25 * 1024 * 1024)))
                content = stream.read(limit + 1)
            if len(content) > limit:
                raise ValueError("File exceeds the configured upload limit")
            headers = {"Content-Type": "application/json"}
            query = "?" + urlencode({"attempt_id": args.attempt_id}) if args.attempt_id else ""
            artifact = request(
                "/artifacts" + query,
                "POST",
                json.dumps(
                    {
                        "filename": resolved.name,
                        "content_type": mimetypes.guess_type(resolved.name)[0] or "application/octet-stream",
                        "size": len(content),
                        "checksum": hashlib.sha256(content).hexdigest(),
                    }
                ).encode(),
                headers,
            )
            headers["Content-Type"] = "application/octet-stream"
            artifact = request("/artifacts/" + artifact["id"] + "/content", "PUT", content, headers)
            print(json.dumps(request("/artifacts/" + artifact["id"] + "/download-link")))
        elif args.command == "list":
            print(json.dumps(request("/artifacts?" + urlencode({"page": args.page}))))
        else:
            from uuid import UUID

            artifact_id = str(UUID(args.artifact_id))
            link = request(
                "/artifacts/" + artifact_id + "/download-link?" + urlencode({"seconds": getattr(args, "seconds", 900)})
            )
            if args.command == "link":
                print(json.dumps(link))
            else:
                # Signed S3 URL carries its own authority; never forward the service bearer.
                with opener.open(link["url"], timeout=120) as response:
                    content = response.read(link["artifact"]["size"] + 1)
                artifact = link["artifact"]
                if len(content) != artifact["size"] or hashlib.sha256(content).hexdigest() != artifact["checksum"]:
                    raise ValueError("Downloaded bytes failed integrity verification")
                with open(args.destination, "xb") as target:
                    target.write(content)
                print(
                    json.dumps({"artifact_id": artifact_id, "checksum": artifact["checksum"], "path": args.destination})
                )
    except urllib.error.HTTPError as exc:
        print(
            f"Artifact operation failed (HTTP {exc.code}). Check access, file limits and storage availability.",
            file=sys.stderr,
        )
        return 1
    except (OSError, ValueError, KeyError) as exc:
        # Do not echo credentials, signed links or HTTP response bodies on errors.
        print(
            "Artifact operation failed ("
            + type(exc).__name__
            + "). Check access, file limits and storage availability.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

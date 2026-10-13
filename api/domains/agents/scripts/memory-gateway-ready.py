"""Allow the API to persist the new Agent credential before plugin initialization."""

import os
import time
import urllib.error
import urllib.request


def main() -> int:
    request = urllib.request.Request(
        os.environ["MEMORY_URL"].rstrip("/") + "/health",
        headers={"Authorization": "Bearer " + os.environ["MEMORY_API_KEY"]},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            with opener.open(request, timeout=2) as response:
                if response.status == 200:
                    return 0
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(0.25)
    print("[memory] Gateway not ready; continuing with native memory available.", flush=True)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

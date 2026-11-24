from collections.abc import AsyncIterator, Iterator
from contextlib import suppress

import anyio
import anyio.to_thread

# A followed log blocks on the cluster between lines, so each open log view holds a
# thread for as long as it stays open. These threads come from their own limiter, not
# the request thread pool that every sync route shares, so open log views cannot
# starve the rest of the API. Past this many, a new view waits for one to close.
LOG_STREAM_THREADS = anyio.CapacityLimiter(100)

_END = object()


async def log_stream_events(lines: Iterator[str | None]) -> AsyncIterator[str]:
    """Server-sent events for a followed log: one ``data:`` event per line.

    ``None`` from ``lines`` marks an idle interval and becomes a comment, which keeps
    proxies from closing a quiet stream and makes the server find a closed tab when the
    write fails, rather than holding its thread until the pod logs again.
    """
    try:
        while True:
            line = await anyio.to_thread.run_sync(next, lines, _END, limiter=LOG_STREAM_THREADS)
            if line is _END:
                return
            yield ": keepalive\n\n" if line is None else f"data: {line}\n\n"
    finally:
        close = getattr(lines, "close", None)
        if close is not None:
            with suppress(ValueError):  # a generator still reading in its thread
                close()

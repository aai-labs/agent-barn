import asyncio

from hamcrest import assert_that, equal_to

from api.domains.agents import log_stream
from api.tests.core.givenpy import then, when


def _collect(lines):
    async def run():
        return [event async for event in log_stream.log_stream_events(lines)]

    return asyncio.run(run())


def test_log_lines_become_events_and_idle_intervals_keepalives():
    borrowed: list[int] = []
    closed: list[bool] = []

    def lines():
        try:
            for line in ("first", None, "second"):
                borrowed.append(log_stream.LOG_STREAM_THREADS.borrowed_tokens)
                yield line
        finally:
            closed.append(True)

    with when("a followed log yields lines with an idle interval between them"):
        events = _collect(lines())

        with then("each line is a data event and the idle interval a comment"):
            assert_that(events, equal_to(["data: first\n\n", ": keepalive\n\n", "data: second\n\n"]))
        with then("the blocking reads run on the log stream threads, not the shared pool"):
            assert_that(borrowed, equal_to([1, 1, 1]))
        with then("the log is closed when the stream ends"):
            assert_that(closed, equal_to([True]))


def test_a_stream_with_nothing_to_follow_ends_at_once():
    with when("the Agent is not running, so there is no log to follow"):
        events = _collect(iter(()))

        with then("the stream ends without events"):
            assert_that(events, equal_to([]))

import threading
from collections.abc import Callable
from datetime import datetime

from hamcrest import assert_that, equal_to

from api.sync_engine_main import run


class _Engine:
    def __init__(
        self, stop: threading.Event, passes: int, failing: set[int] | None = None, reports_progress: bool = False
    ):
        self.stop = stop
        self.reports_progress = reports_progress
        self.passes = passes
        self.failing = failing or set()
        self.calls: list[datetime] = []

    def run_pass(self, now: datetime, progress: Callable[[], None] | None = None) -> None:
        self.calls.append(now)
        if self.reports_progress and progress is not None:
            progress()
        if len(self.calls) >= self.passes:
            self.stop.set()
        if len(self.calls) in self.failing:
            raise RuntimeError("database unreachable")


def test_passes_repeat_until_stopped_and_each_success_refreshes_the_heartbeat(tmp_path):
    stop = threading.Event()
    engine = _Engine(stop, passes=3)
    heartbeat = tmp_path / "heartbeat"

    run(engine, stop=stop, interval_seconds=0, heartbeat=heartbeat)

    assert_that(len(engine.calls), equal_to(3))
    assert_that(heartbeat.exists(), equal_to(True))


def test_a_failing_pass_is_survived_and_does_not_refresh_the_heartbeat(tmp_path):
    stop = threading.Event()
    engine = _Engine(stop, passes=2, failing={1, 2})
    heartbeat = tmp_path / "heartbeat"

    run(engine, stop=stop, interval_seconds=0, heartbeat=heartbeat)

    assert_that(len(engine.calls), equal_to(2))
    assert_that(heartbeat.exists(), equal_to(False))


def test_a_stop_during_the_wait_ends_the_loop_without_another_pass(tmp_path):
    stop = threading.Event()
    engine = _Engine(stop, passes=99)
    timer = threading.Timer(0.2, stop.set)
    timer.start()

    run(engine, stop=stop, interval_seconds=60, heartbeat=tmp_path / "heartbeat")

    assert_that(len(engine.calls), equal_to(1))


def test_a_long_pass_keeps_the_heartbeat_fresh_while_it_works_even_if_it_then_fails(tmp_path):
    stop = threading.Event()
    engine = _Engine(stop, passes=1, failing={1}, reports_progress=True)
    heartbeat = tmp_path / "heartbeat"

    run(engine, stop=stop, interval_seconds=0, heartbeat=heartbeat)

    assert_that(heartbeat.exists(), equal_to(True))

"""The observer's state.db poll must never cost the Hermes gateway its lock on state.db.

Hermes reads the first bytes of state.db as a plain file whenever it opens a SessionDB() and
none of its own connections is open. Closing that file cancels every POSIX lock the process
holds on state.db, including the ones SQLite took for any connection Hermes does not know
about. A gateway that has lost its lock looks fine, but the next process to close state.db
believes it is the last one and deletes the WAL under the running gateway, which corrupts the
database. Only the runtime image can show whether Hermes sees the observer's connection.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
from hamcrest import assert_that, equal_to, greater_than_or_equal_to, is_

from api.tests.core.givenpy import given, then, when

_DRIVER = Path(__file__).parent / "fixtures/hermes_observer_state_db_driver.py"
_PLUGIN = Path(__file__).parents[1] / "domains/agents/scripts/hermes/plugins/agentbarn-observer/__init__.py"


def _hermes_image_is_selected():
    def step(context) -> None:
        context.image = os.environ.get("HERMES_TEST_IMAGE")
        if not context.image:
            pytest.fail("HERMES_TEST_IMAGE must name an already-built Hermes image")

    return step


def _poll_while_a_turn_starts(image: str) -> dict:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--mount",
            f"type=bind,src={_PLUGIN},dst=/plugin.py,readonly",
            "--mount",
            f"type=bind,src={_DRIVER},dst=/driver.py,readonly",
            "--entrypoint",
            "/opt/hermes/.venv/bin/python",
            image,
            "/driver.py",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert_that(result.returncode, equal_to(0), result.stdout + result.stderr)
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_a_turn_starting_during_an_observer_poll_keeps_the_lock_on_state_db():
    with given([_hermes_image_is_selected()]) as context:
        with when("a Hermes turn starts while the observer is reading state.db"):
            report = _poll_while_a_turn_starts(context.image)

        with then("the turn opened its session store during the observer's query"):
            assert_that(report["overlapped"], is_(True))

        with then("the observer still mirrors the delivered reply"):
            assert_that(report["mirrored"], equal_to(1))

        with then("the process still holds its lock on state.db"):
            assert_that(report["locks_held_on_state_db"], greater_than_or_equal_to(1))

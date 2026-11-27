"""Cron sessions must leave state.db after 7 days, a day per transaction.

Every scheduled run opens a Hermes session; one Agent's crons filled its 1 GiB volume with
them. A prune's WAL grows with what one transaction deletes, so clearing weeks of backlog in
one call can itself fill a nearly full volume. Only the runtime image has the real SessionDB.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest
from hamcrest import assert_that, equal_to, is_

from api.tests.core.givenpy import given, then, when

_DRIVER = Path(__file__).parent / "fixtures/hermes_session_prune_driver.py"
_SCRIPT = Path(__file__).parents[1] / "domains/agents/scripts/hermes/session-prune.py"


def _hermes_image_is_selected():
    def step(context) -> None:
        context.image = os.environ.get("HERMES_TEST_IMAGE")
        if not context.image:
            pytest.fail("HERMES_TEST_IMAGE must name an already-built Hermes image")

    return step


def _prune_a_month_of_cron_sessions(image: str) -> dict:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--pull=never",
            "--network=none",
            "--mount",
            f"type=bind,src={_SCRIPT},dst=/session-prune.py,readonly",
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


def test_cron_sessions_older_than_seven_days_are_pruned_a_day_at_a_time():
    with given([_hermes_image_is_selected()]) as context:
        with when("an Agent with a month of cron sessions prunes"):
            report = _prune_a_month_of_cron_sessions(context.image)

        with then("only the last 7 days of ended cron sessions remain"):
            assert_that(report["kept_cron_days"], equal_to(list(range(7))))

        with then("a cron run still in progress is kept"):
            assert_that(report["running_cron_kept"], is_(True))

        with then("sessions from other sources are left to Hermes' own retention"):
            assert_that(report["old_api_session_kept"], is_(True))

        with then("no single transaction deletes more than one day of sessions"):
            assert_that(report["largest_single_prune"], equal_to(4))

        with then("the search index drops the pruned messages too"):
            assert_that(report["index_matches_messages"], is_(True))

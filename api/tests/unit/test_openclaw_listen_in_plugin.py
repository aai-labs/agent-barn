import json
import shutil
import subprocess
from pathlib import Path

import pytest
from hamcrest import assert_that, equal_to, has_entries

_PLUGIN = Path(__file__).parents[2] / "domains" / "agents" / "scripts" / "openclaw" / "plugins" / "agentbarn-listen-in"
_DRIVER = Path(__file__).parents[1] / "fixtures" / "openclaw_hook_driver.mjs"
_SESSION = "agent:main:discord:channel:c1"


def _run(steps: list[dict], tmp_path: Path) -> list:
    node = shutil.which("node")
    assert node is not None, "node is required to exercise the OpenClaw plugin"
    steps_path = tmp_path / "steps.json"
    steps_path.write_text(json.dumps(steps))
    done = subprocess.run(
        [node, str(_DRIVER), str(_PLUGIN / "index.js"), str(steps_path)],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def _dispatch(kind: str, session: str = _SESSION) -> dict:
    return {"hook": "reply_dispatch", "event": {"sessionKey": session, "ctx": {"InboundEventKind": kind}}}


def _run_start(session: str = _SESSION, trigger: str = "user") -> dict:
    return {"hook": "before_agent_run", "ctx": {"sessionKey": session, "trigger": trigger}}


def _tool(name: str, session: str = _SESSION) -> dict:
    return {"hook": "before_tool_call", "event": {"toolName": name}, "ctx": {"sessionKey": session}}


@pytest.mark.parametrize("tool", ["exec", "write", "apply_patch", "cron", "sessions_history", "ask_user"])
def test_an_unmentioned_turn_cannot_use_other_tools(tool: str, tmp_path: Path) -> None:
    results = _run([_dispatch("room_event"), _run_start(), _tool(tool)], tmp_path)

    assert_that(results[2], has_entries(block=True))


@pytest.mark.parametrize("tool", ["message", "web_search", "web_fetch", "x_search"])
def test_an_unmentioned_turn_can_post_and_look_things_up(tool: str, tmp_path: Path) -> None:
    results = _run([_dispatch("room_event"), _run_start(), _tool(tool)], tmp_path)

    assert_that(results[2], equal_to(None))


def test_a_mention_keeps_every_tool(tmp_path: Path) -> None:
    results = _run([_dispatch("user_request"), _run_start(), _tool("exec")], tmp_path)

    assert_that(results[2], equal_to(None))


def test_the_guard_never_claims_the_reply(tmp_path: Path) -> None:
    results = _run([_dispatch("room_event"), _dispatch("user_request")], tmp_path)

    assert_that(results, equal_to([None, None]))


def test_queued_messages_each_keep_their_own_classification(tmp_path: Path) -> None:
    results = _run(
        [
            _dispatch("user_request"),
            _dispatch("room_event"),
            _run_start(),
            _tool("exec"),
            _run_start(),
            _tool("exec"),
        ],
        tmp_path,
    )

    assert_that(results[3], equal_to(None))
    assert_that(results[5], has_entries(block=True))


def test_a_later_message_does_not_change_the_running_turn(tmp_path: Path) -> None:
    results = _run([_dispatch("user_request"), _run_start(), _dispatch("room_event"), _tool("exec")], tmp_path)

    assert_that(results[3], equal_to(None))


def test_sessions_do_not_share_a_classification(tmp_path: Path) -> None:
    other = "agent:main:discord:channel:c2"
    results = _run(
        [
            _dispatch("room_event"),
            _run_start(),
            _dispatch("user_request", other),
            _run_start(other),
            _tool("exec"),
            _tool("exec", other),
        ],
        tmp_path,
    )

    assert_that(results[4], has_entries(block=True))
    assert_that(results[5], equal_to(None))


def test_a_scheduled_run_is_not_limited(tmp_path: Path) -> None:
    results = _run(
        [
            _dispatch("room_event"),
            _run_start(),
            _run_start(trigger="cron"),
            _tool("exec", "agent:main:cron:job"),
        ],
        tmp_path,
    )

    assert_that(results[3], equal_to(None))


def test_a_scheduled_run_does_not_consume_a_queued_message(tmp_path: Path) -> None:
    results = _run([_dispatch("room_event"), _run_start(trigger="cron"), _run_start(), _tool("exec")], tmp_path)

    assert_that(results[3], has_entries(block=True))

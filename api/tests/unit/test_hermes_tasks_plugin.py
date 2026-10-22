"""The Hermes agentbarn-tasks plugin: a typed Task tool, open Tasks each turn, and reminders."""

import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_entries, is_, not_none

_PLUGIN = Path(__file__).parents[2] / "domains/agents/scripts/hermes/plugins/agentbarn-tasks/__init__.py"
_FAKE_COMMAND = Path(__file__).parents[1] / "fixtures/agent_tasks/fake_task_command.py"
_ENV = {
    "AGENT_ID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "INGEST_URL": "http://localhost:8001/ingest/v1",
    "INGEST_API_KEY": "test-key-123",
}
_TASK_ID = "0199f1d2-0000-7000-8000-0000000000aa"


class _Plugin:
    """The loaded plugin, its registered hooks and tool, and the calls its command received."""

    def __init__(self, tmp_path: Path, open_tasks: list[dict] | None = None):
        self.log = tmp_path / "calls.jsonl"
        self.workspace = tmp_path / "workspace"
        self.workspace.mkdir()
        spec = importlib.util.spec_from_file_location("agentbarn_tasks_plugin", _PLUGIN)
        assert spec is not None and spec.loader is not None
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        wrapper = tmp_path / "agentbarn-task"
        wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{_FAKE_COMMAND}" "$@"\n')
        wrapper.chmod(0o755)
        self.env = {
            **_ENV,
            "AGENTBARN_TASK_COMMAND": str(wrapper),
            "TERMINAL_CWD": str(self.workspace),
            "FAKE_TASK_LOG": str(self.log),
            "FAKE_TASK_LIST": json.dumps(open_tasks or []),
            "PATH": os.environ["PATH"],
        }
        self.hooks: dict = {}
        self.tools: dict = {}
        self.ctx = MagicMock()
        self.ctx.register_hook.side_effect = lambda name, fn: self.hooks.update({name: fn})
        self.ctx.register_tool.side_effect = lambda **tool: self.tools.update({tool["name"]: tool})
        with patch.dict(os.environ, self.env, clear=True):
            self.module.register(self.ctx)

    def calls(self) -> list[dict]:
        return [json.loads(line) for line in self.log.read_text().splitlines()] if self.log.exists() else []

    def tool(self, **args) -> dict:
        with patch.dict(os.environ, self.env, clear=True):
            return json.loads(self.tools["agentbarn_task"]["handler"](args, task_id="t", session_id="s1"))

    def tool_call(
        self,
        call_id: str,
        session_id: str = "s1",
        turn_id: str = "turn-1",
        tool_name: str = "terminal",
        command: str = "ls",
        args: dict | None = None,
        result: str = '{"output": "done"}',
    ):
        if args is None:
            args = {"command": command} if tool_name == "terminal" else {"action": "list"}
        kwargs = {
            "tool_name": tool_name,
            "args": args,
            "result": result,
            "session_id": session_id,
            "turn_id": turn_id,
            "tool_call_id": call_id,
            "duration_ms": 10,
            "status": "ok",
        }
        with patch.dict(os.environ, self.env, clear=True):
            self.hooks["post_tool_call"](**kwargs)
            return self.hooks["transform_tool_result"](**kwargs)

    def finish(self, session_id: str = "s1", attempt: int = 0):
        """Hermes asking whether a turn that edited files may finish."""
        return self.hooks["pre_verify"](
            session_id=session_id,
            platform="slack",
            model="m",
            coding=False,
            attempt=attempt,
            final_response="Done.",
            changed_paths=["/workspace/states.csv"],
        )

    def end_turn(self, session_id: str = "s1", turn_id: str = "turn-1", completed: bool = True):
        with patch.dict(os.environ, self.env, clear=True):
            self.hooks["on_session_end"](
                session_id=session_id, turn_id=turn_id, completed=completed, failed=False, interrupted=False
            )

    def start_turn(self, session_id: str = "s1", user_message: str = "Please summarise the October invoices"):
        with patch.dict(os.environ, self.env, clear=True):
            return self.hooks["pre_llm_call"](
                session_id=session_id,
                turn_id="next",
                user_message=user_message,
                conversation_history=[],
                is_first_turn=False,
                platform="slack",
            )


def _context(returned) -> str:
    return returned["context"] if isinstance(returned, dict) else (returned or "")


# --- registration ---


def test_nothing_is_registered_without_the_ingest_credentials():
    ctx = MagicMock()
    spec = importlib.util.spec_from_file_location("agentbarn_tasks_plugin", _PLUGIN)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    with patch.dict(os.environ, {}, clear=True):
        module.register(ctx)

    ctx.register_hook.assert_not_called()
    ctx.register_tool.assert_not_called()


def test_the_task_tool_and_turn_hooks_are_registered(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    assert_that(
        sorted(plugin.hooks),
        equal_to(["on_session_end", "post_tool_call", "pre_llm_call", "pre_verify", "transform_tool_result"]),
    )
    tool = plugin.tools["agentbarn_task"]
    assert_that(tool["schema"]["name"], equal_to("agentbarn_task"))
    actions = tool["schema"]["parameters"]["properties"]["action"]["enum"]
    assert_that(sorted(actions), equal_to(["attach", "create", "list", "note", "remove_file", "show", "status"]))
    statuses = tool["schema"]["parameters"]["properties"]["status"]["enum"]
    assert_that(statuses, equal_to(["open", "in_progress", "done", "failed"]))


# --- the tool ---


def test_create_runs_the_task_command(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    result = plugin.tool(action="create", title="Reconcile invoices", description="For October")

    assert_that(result, has_entries(id=_TASK_ID))
    assert_that(
        plugin.calls()[-1]["argv"],
        equal_to(
            ["create", "--title", "Reconcile invoices", "--description", "For October", "--status", "in_progress"]
        ),
    )


@pytest.mark.parametrize(
    ("args", "argv", "stdin"),
    [
        ({"action": "status", "task_id": _TASK_ID, "status": "done"}, ["status", _TASK_ID, "done"], ""),
        ({"action": "note", "task_id": _TASK_ID, "body": "Matched 40 of 42"}, ["note", _TASK_ID], "Matched 40 of 42"),
        ({"action": "list", "status": "open"}, ["list", "--status", "open"], ""),
        ({"action": "show", "task_id": _TASK_ID}, ["show", _TASK_ID], ""),
        (
            {
                "action": "attach",
                "task_id": _TASK_ID,
                "path": "out/report.csv",
                "name": "October.csv",
                "content_type": "text/csv",
            },
            ["attach", _TASK_ID, "out/report.csv", "--name", "October.csv", "--content-type", "text/csv", "--replace"],
            "",
        ),
    ],
)
def test_each_action_maps_onto_the_task_command(tmp_path: Path, args: dict, argv: list[str], stdin: str):
    plugin = _Plugin(tmp_path)

    plugin.tool(**args)

    call = plugin.calls()[-1]
    assert_that((call["argv"], call["stdin"]), equal_to((argv, stdin)))


def test_files_are_found_relative_to_the_agents_workspace(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    plugin.tool(action="attach", task_id=_TASK_ID, path="report.csv")

    assert_that(os.path.realpath(plugin.calls()[-1]["cwd"]), equal_to(os.path.realpath(plugin.workspace)))


def test_a_refusal_is_returned_to_the_model_as_an_error(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    result = plugin.tool(action="create", title="fail")

    assert_that(result, has_entries(error=contains_string("not allowed")))


def test_a_missing_required_argument_is_returned_without_running_the_command(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    result = plugin.tool(action="status", task_id=_TASK_ID)

    assert_that((result.get("error") is not None, plugin.calls()), equal_to((True, [])))


# --- reminders ---


def test_a_turn_doing_real_work_without_a_task_is_reminded_once(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    results = [plugin.tool_call(f"call-{n}") for n in range(1, 5)]

    assert_that((results[0], results[1], results[3]), equal_to((None, None, None)))
    assert_that(results[2], contains_string("agentbarn_task"))
    assert_that(results[2], contains_string('{"output": "done"}'))


def test_a_turn_that_records_a_task_is_not_reminded(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    plugin.tool_call("call-1", tool_name="agentbarn_task")
    results = [plugin.tool_call(f"call-{n}") for n in range(2, 6)]

    assert_that(results, equal_to([None] * 4))


def test_using_the_task_command_from_the_terminal_counts_as_recording(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    plugin.tool_call("call-1", command="agentbarn-task create --title Report")
    results = [plugin.tool_call(f"call-{n}") for n in range(2, 6)]

    assert_that(results, equal_to([None] * 4))


def test_a_short_turn_is_not_reminded(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    plugin.tool_call("call-1")
    plugin.tool_call("call-2")
    plugin.end_turn()

    assert_that("did work without recording" in _context(plugin.start_turn()), is_(False))


def test_counting_is_per_session(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    plugin.tool_call("call-1", session_id="s1")
    plugin.tool_call("call-2", session_id="s2")
    result = plugin.tool_call("call-3", session_id="s1")

    assert_that(result, equal_to(None))


def test_a_turn_that_ends_without_a_task_is_reminded_on_the_next_turn_of_that_session(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    for n in range(1, 4):
        plugin.tool_call(f"call-{n}")

    plugin.end_turn()

    assert_that("did work without recording" in _context(plugin.start_turn("s2")), is_(False))
    assert_that(_context(plugin.start_turn("s1")), contains_string("did work without recording it as a Task"))
    assert_that("did work without recording" in _context(plugin.start_turn("s1")), is_(False))


# --- open Tasks each turn ---


def test_each_turn_starts_with_the_agents_open_tasks(tmp_path: Path):
    plugin = _Plugin(
        tmp_path,
        open_tasks=[
            {"id": "task-1", "title": "Reconcile invoices", "status": "in_progress"},
            {"id": "task-2", "title": "Draft summary", "status": "open"},
            {"id": "task-3", "title": "Old work", "status": "done"},
        ],
    )

    context = _context(plugin.start_turn())

    assert_that(context, contains_string("task-1 [in_progress] Reconcile invoices"))
    assert_that(context, contains_string("task-2 [open] Draft summary"))
    assert_that(context, contains_string("task-3 [done] Old work"))


def test_open_tasks_are_cached_between_turns_until_a_task_changes(tmp_path: Path):
    plugin = _Plugin(tmp_path, open_tasks=[{"id": "task-1", "title": "Report", "status": "open"}])

    plugin.start_turn()
    plugin.start_turn()
    lists_before = sum(call["argv"][0] == "list" for call in plugin.calls())
    plugin.tool(action="status", task_id="task-1", status="done")
    plugin.start_turn()
    lists_after = sum(call["argv"][0] == "list" for call in plugin.calls())

    assert_that((lists_before, lists_after), equal_to((3, 6)))


def test_an_unavailable_task_service_does_not_break_the_turn(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.env["AGENTBARN_TASK_COMMAND"] = "/nonexistent/agentbarn-task"

    context = _context(plugin.start_turn())
    assert_that(("Your open Tasks" in context, "agentbarn_task" in context), equal_to((False, True)))


def test_the_tool_answer_is_always_json(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    raw = plugin.tools["agentbarn_task"]["handler"]({"action": "unknown"}, task_id="t")

    assert_that(json.loads(raw), not_none())


# --- turns that produce files ---


def test_a_turn_that_writes_a_file_counts_as_real_work(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    result = plugin.tool_call("call-1", tool_name="write_file")

    assert_that(result, contains_string("agentbarn_task"))


def test_a_turn_that_wrote_files_without_a_task_must_continue_once_before_finishing(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.tool_call("call-1", tool_name="write_file")

    first, second = plugin.finish(), plugin.finish(attempt=1)

    assert_that(first, has_entries(action="continue", message=contains_string("agentbarn_task")))
    assert_that(second, equal_to(None))


def test_a_turn_that_wrote_files_and_recorded_a_task_may_finish(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.tool_call("call-1", tool_name="write_file")
    plugin.tool_call("call-2", tool_name="agentbarn_task")

    assert_that(plugin.finish(), equal_to(None))


def test_finishing_is_judged_on_the_sessions_current_turn(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.tool_call("call-1", session_id="s2", tool_name="write_file")

    assert_that(plugin.finish("s1"), equal_to(None))


def test_a_turn_that_wrote_a_file_without_a_task_is_reminded_next_turn(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.tool_call("call-1", tool_name="patch")

    plugin.end_turn()

    assert_that(_context(plugin.start_turn()), contains_string("did work without recording it as a Task"))


# --- files produced but not attached ---


def _wrote(plugin: _Plugin, call_id: str = "call-1", name: str = "states.csv") -> str:
    path = plugin.workspace / name
    path.write_text("a,b\n")
    plugin.tool_call(call_id, tool_name="write_file", args={"path": str(path), "content": "a,b"})
    return str(path)


def _created_task(plugin: _Plugin, call_id: str = "call-2", task_id: str = _TASK_ID):
    return plugin.tool_call(
        call_id,
        tool_name="agentbarn_task",
        args={"action": "create", "title": "States"},
        result=json.dumps({"id": task_id, "status": "in_progress"}),
    )


def _attaches(plugin: _Plugin) -> list[list[str]]:
    return [call["argv"] for call in plugin.calls() if call["argv"][0] == "attach"]


def test_files_the_turn_wrote_are_attached_to_its_task_when_it_ends(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    states = _wrote(plugin)
    chart = _wrote(plugin, "call-3", "chart.png")
    _created_task(plugin)

    plugin.end_turn()

    assert_that(
        _attaches(plugin),
        equal_to(sorted([["attach", _TASK_ID, chart, "--replace"], ["attach", _TASK_ID, states, "--replace"]])),
    )


def test_files_go_to_a_task_the_turn_touched_by_id(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    states = _wrote(plugin)
    plugin.tool_call(
        "call-2", tool_name="agentbarn_task", args={"action": "status", "task_id": "task-9", "status": "done"}
    )

    plugin.end_turn()

    assert_that(_attaches(plugin), equal_to([["attach", "task-9", states, "--replace"]]))


def test_a_file_the_agent_attached_is_not_attached_again(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _wrote(plugin)
    _created_task(plugin)
    plugin.tool_call(
        "call-3", tool_name="agentbarn_task", args={"action": "attach", "task_id": _TASK_ID, "path": "states.csv"}
    )

    plugin.end_turn()

    assert_that(_attaches(plugin), equal_to([]))


def test_a_file_that_no_longer_exists_is_not_attached(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    Path(_wrote(plugin)).unlink()
    _created_task(plugin)

    plugin.end_turn()

    assert_that(_attaches(plugin), equal_to([]))


def test_files_are_not_attached_when_the_turn_touched_several_tasks(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _wrote(plugin)
    _created_task(plugin, "call-2", "task-1")
    _created_task(plugin, "call-3", "task-2")

    plugin.end_turn()

    assert_that(_attaches(plugin), equal_to([]))
    assert_that(_context(plugin.start_turn()), contains_string("states.csv"))


def test_a_file_that_could_not_be_attached_is_named_on_the_next_turn(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _wrote(plugin)
    _created_task(plugin)
    plugin.env["AGENTBARN_TASK_COMMAND"] = "/nonexistent/agentbarn-task"

    plugin.end_turn()

    assert_that(_context(plugin.start_turn()), contains_string("states.csv"))


def test_nothing_about_attaching_is_said_within_the_turn_or_after_an_automatic_attach(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _wrote(plugin)
    within = _created_task(plugin)
    held = plugin.finish()

    plugin.end_turn()

    assert_that((within, held), equal_to((None, None)))
    assert_that("states.csv" in _context(plugin.start_turn()), is_(False))


def test_a_turn_that_attached_what_it_wrote_may_finish(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _wrote(plugin)
    _created_task(plugin)
    plugin.tool_call(
        "call-3", tool_name="agentbarn_task", args={"action": "attach", "task_id": "t", "path": "states.csv"}
    )

    assert_that(plugin.finish(), equal_to(None))


# --- the boot run ---


def test_the_boot_run_is_never_reminded(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    results = [plugin.tool_call(f"call-{n}", session_id="agentbarn-boot") for n in range(1, 5)]
    _wrote_in_boot = plugin.tool_call(
        "call-5", session_id="agentbarn-boot", tool_name="write_file", args={"path": "/workspace/BOOT.md"}
    )
    held = plugin.finish("agentbarn-boot")
    plugin.end_turn("agentbarn-boot")

    assert_that((results, _wrote_in_boot, held), equal_to(([None] * 4, None, None)))
    assert_that(plugin.start_turn("agentbarn-boot"), equal_to(None))


def test_the_catch_up_reminder_asks_for_quiet_bookkeeping(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.tool_call("call-1", tool_name="write_file", args={"path": "/workspace/a.csv"})
    plugin.end_turn()

    assert_that(_context(plugin.start_turn()), contains_string("answer the user's message as normal"))


# --- starting a Task in progress, and the request line ---


def test_create_passes_a_starting_status(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    plugin.tool(action="create", title="Report", status="in_progress")

    assert_that(plugin.calls()[-1]["argv"], equal_to(["create", "--title", "Report", "--status", "in_progress"]))


def test_each_request_carries_the_task_line(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    context = _context(plugin.start_turn())

    assert_that(context, contains_string("create a Task with agentbarn_task before you start"))
    assert_that(context, contains_string("Don't mention Tasks in your reply"))


def test_remove_file_maps_onto_the_task_command(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    plugin.tool(action="remove_file", task_id=_TASK_ID, file_id="0199f1d2-0000-7000-8000-0000000000ff")

    assert_that(plugin.calls()[-1]["argv"], equal_to(["remove-file", _TASK_ID, "0199f1d2-0000-7000-8000-0000000000ff"]))


def test_remove_file_needs_a_file_id(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    result = plugin.tool(action="remove_file", task_id=_TASK_ID)

    assert_that((result.get("error") is not None, plugin.calls()), equal_to((True, [])))


# --- closing the turn's Task, notes in the same call, and small talk ---


def _statuses(plugin: _Plugin) -> list[list[str]]:
    return [call["argv"] for call in plugin.calls() if call["argv"][0] == "status"]


def test_create_and_status_carry_a_note_in_the_same_call(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    plugin.tool(action="create", title="Report", body="Started from the October export")
    created = plugin.calls()[-1]["argv"]
    plugin.tool(action="status", task_id=_TASK_ID, status="failed", body="The export was empty")

    assert_that(
        created,
        equal_to(
            ["create", "--title", "Report", "--status", "in_progress", "--note", "Started from the October export"]
        ),
    )
    assert_that(plugin.calls()[-1]["argv"], equal_to(["status", _TASK_ID, "failed", "--note", "The export was empty"]))


def test_a_task_left_in_progress_is_marked_done_when_the_turn_ends(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _created_task(plugin)

    plugin.end_turn()

    assert_that(_statuses(plugin), equal_to([["status", _TASK_ID, "done"]]))


@pytest.mark.parametrize("status", ["failed", "open", "done"])
def test_a_status_the_agent_set_itself_is_kept(tmp_path: Path, status: str):
    plugin = _Plugin(tmp_path)
    _created_task(plugin)
    plugin.tool_call(
        "call-3", tool_name="agentbarn_task", args={"action": "status", "task_id": _TASK_ID, "status": status}
    )

    plugin.end_turn()

    assert_that(_statuses(plugin), equal_to([]))


def test_a_task_the_turn_only_noted_on_is_not_closed(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.tool_call(
        "call-1", tool_name="agentbarn_task", args={"action": "note", "task_id": _TASK_ID, "body": "Waiting on Dana"}
    )

    plugin.end_turn()

    assert_that(_statuses(plugin), equal_to([]))


def test_a_task_is_not_closed_when_the_turn_did_not_complete(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _created_task(plugin)

    plugin.end_turn(completed=False)

    assert_that(_statuses(plugin), equal_to([]))


def test_every_task_left_in_progress_is_closed(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _created_task(plugin, "call-1", "task-1")
    _created_task(plugin, "call-2", "task-2")

    plugin.end_turn()

    assert_that(sorted(_statuses(plugin)), equal_to([["status", "task-1", "done"], ["status", "task-2", "done"]]))


def test_files_are_attached_before_the_task_is_closed(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    states = _wrote(plugin)
    _created_task(plugin)

    plugin.end_turn()

    assert_that(
        [call["argv"] for call in plugin.calls() if call["argv"][0] in {"attach", "status"}],
        equal_to([["attach", _TASK_ID, states, "--replace"], ["status", _TASK_ID, "done"]]),
    )


def test_closing_a_task_refreshes_the_open_tasks_shown(tmp_path: Path):
    plugin = _Plugin(tmp_path, open_tasks=[{"id": _TASK_ID, "status": "in_progress", "title": "States"}])
    plugin.start_turn()
    _created_task(plugin)

    plugin.end_turn()
    plugin.start_turn()

    assert_that(len([call for call in plugin.calls() if call["argv"][0] == "list"]), equal_to(6))


@pytest.mark.parametrize("message", ["Thanks!", "Thanks, that's great.", "That's all for now, thanks!", "Good morning"])
def test_small_talk_does_not_carry_the_task_line(tmp_path: Path, message: str):
    plugin = _Plugin(tmp_path)

    assert_that("agentbarn_task before you start" in _context(plugin.start_turn(user_message=message)), is_(False))


@pytest.mark.parametrize(
    "message",
    ["Ok", "Yes please", "Please summarise the October invoices", "Thanks, now rename states.csv"],
)
def test_requests_and_approvals_carry_the_task_line(tmp_path: Path, message: str):
    plugin = _Plugin(tmp_path)

    assert_that(_context(plugin.start_turn(user_message=message)), contains_string("agentbarn_task before you start"))


# --- files and Tasks across turns ---


def test_only_the_three_latest_done_tasks_are_shown(tmp_path: Path):
    done = [{"id": f"task-{n}", "title": f"Job {n}", "status": "done"} for n in range(1, 6)]
    plugin = _Plugin(tmp_path, open_tasks=done)

    context = _context(plugin.start_turn())

    assert_that([f"task-{n} [done]" in context for n in range(1, 6)], equal_to([True, True, True, False, False]))


def test_files_a_turn_could_not_attach_go_to_the_task_a_later_turn_works_on(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    states = _wrote(plugin)
    plugin.end_turn()

    plugin.tool_call(
        "call-2",
        turn_id="turn-2",
        tool_name="agentbarn_task",
        args={"action": "create", "title": "States"},
        result=json.dumps({"id": "task-2", "status": "in_progress"}),
    )
    plugin.end_turn(turn_id="turn-2")

    assert_that(_attaches(plugin), equal_to([["attach", "task-2", states, "--replace"]]))


def test_files_carried_over_do_not_count_as_work_in_the_later_turn(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _wrote(plugin)
    plugin.end_turn()
    plugin.start_turn()

    reminded = plugin.tool_call("call-2", turn_id="turn-2")

    assert_that(reminded, equal_to(None))


def test_a_carried_over_file_is_dropped_after_two_more_turns_without_a_task(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _wrote(plugin)
    plugin.end_turn()
    for turn_id in ("turn-2", "turn-3"):
        plugin.tool_call(f"call-{turn_id}", turn_id=turn_id, command="date")
        plugin.end_turn(turn_id=turn_id)

    plugin.tool_call(
        "call-4",
        turn_id="turn-4",
        tool_name="agentbarn_task",
        args={"action": "create", "title": "Unrelated"},
        result=json.dumps({"id": "task-4", "status": "in_progress"}),
    )
    plugin.end_turn(turn_id="turn-4")

    assert_that(_attaches(plugin), equal_to([]))

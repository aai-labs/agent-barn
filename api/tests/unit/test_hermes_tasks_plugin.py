"""The Hermes agentbarn-tasks plugin: a typed Task tool, open Tasks each turn, and reminders."""

import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_entries, has_items, is_, not_none

_PLUGIN = Path(__file__).parents[2] / "domains/agents/scripts/hermes/plugins/agentbarn-tasks/__init__.py"
_FAKE_COMMAND = Path(__file__).parents[1] / "fixtures/agent_tasks/fake_task_command.py"
_ENV = {
    "AGENT_ID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "INGEST_URL": "http://localhost:8001/ingest/v1",
    "INGEST_API_KEY": "test-key-123",
}
_TASK_ID = "0199f1d2-0000-7000-8000-0000000000aa"
_SESSIONS_KEPT = 500


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

    def start_turn(
        self,
        session_id: str = "s1",
        user_message: str = "Please summarise the October invoices",
        turn_id: str = "next",
        parent_session_id: str = "",
    ):
        with patch.dict(os.environ, self.env, clear=True):
            return self.hooks["pre_llm_call"](
                session_id=session_id,
                turn_id=turn_id,
                user_message=user_message,
                parent_session_id=parent_session_id,
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
        equal_to(
            [
                "on_session_end",
                "post_llm_call",
                "post_tool_call",
                "pre_llm_call",
                "pre_verify",
                "transform_tool_result",
            ]
        ),
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
        equal_to(["create", "--title=Reconcile invoices", "--description=For October", "--status=in_progress"]),
    )


@pytest.mark.parametrize(
    ("args", "argv", "stdin"),
    [
        ({"action": "status", "task_id": _TASK_ID, "status": "done"}, ["status", _TASK_ID, "done"], ""),
        ({"action": "note", "task_id": _TASK_ID, "body": "Matched 40 of 42"}, ["note", _TASK_ID], "Matched 40 of 42"),
        ({"action": "list", "status": "open"}, ["list", "--status=open"], ""),
        ({"action": "show", "task_id": _TASK_ID}, ["show", _TASK_ID], ""),
        (
            {
                "action": "attach",
                "task_id": _TASK_ID,
                "path": "out/report.csv",
                "name": "October.csv",
                "content_type": "text/csv",
            },
            ["attach", _TASK_ID, "out/report.csv", "--name=October.csv", "--content-type=text/csv", "--replace"],
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

    _created_task(plugin, "call-1")
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


# --- open Tasks each turn ---


def test_an_unfinished_tasks_latest_note_is_shown_with_it(tmp_path: Path):
    plugin = _Plugin(
        tmp_path,
        open_tasks=[
            {
                "id": "task-1",
                "title": "Weekly greetings",
                "status": "in_progress",
                "latest_note": "Greeting 5\nof 7 sent",
            },
            {"id": "task-2", "title": "Draft summary", "status": "open", "latest_note": None},
            {"id": "task-3", "title": "Old work", "status": "done", "latest_note": "All sent"},
            {"id": "task-4", "title": "Long", "status": "open", "latest_note": "x" * 400},
        ],
    )

    context = _context(plugin.start_turn())

    assert_that(context, contains_string('task-1 [in_progress] Weekly greetings (latest note: "Greeting 5 of 7 sent")'))
    assert_that(context, contains_string("task-2 [open] Draft summary\n"))
    assert_that(context, contains_string("task-3 [done] Old work\n"))
    assert_that(context, contains_string('task-4 [open] Long (latest note: "' + "x" * 200 + '…")'))


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
    assert_that(context, contains_string("only when the request is the same piece of work"))
    assert_that(context, contains_string("A new request gets its own Task, even while another is in progress"))


def test_open_tasks_are_cached_between_turns_until_a_task_changes(tmp_path: Path):
    plugin = _Plugin(tmp_path, open_tasks=[{"id": "task-1", "title": "Report", "status": "open"}])

    plugin.start_turn()
    plugin.start_turn()
    lists_before = sum(call["argv"][0] == "list" for call in plugin.calls())
    plugin.tool(action="status", task_id="task-1", status="done")
    plugin.start_turn()
    lists_after = sum(call["argv"][0] == "list" for call in plugin.calls())

    assert_that((lists_before, lists_after), equal_to((1, 2)))


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
    _created_task(plugin)

    assert_that(plugin.finish(), equal_to(None))


def test_finishing_is_judged_on_the_sessions_current_turn(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.tool_call("call-1", session_id="s2", tool_name="write_file")

    assert_that(plugin.finish("s1"), equal_to(None))


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


def test_a_file_over_the_limit_is_named_on_the_next_turn(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.env["ARTIFACT_MAX_BYTES"] = "1"
    _wrote(plugin)
    _created_task(plugin)

    plugin.end_turn()

    assert_that((_attaches(plugin), "states.csv" in _context(plugin.start_turn())), equal_to(([], True)))


@pytest.mark.parametrize("name", [".env", ".env.production", "service-account.json", "id_rsa", "server.pem"])
def test_a_credential_file_is_not_attached_automatically(tmp_path: Path, name: str):
    plugin = _Plugin(tmp_path)
    _wrote(plugin, name=name)
    _created_task(plugin)

    plugin.end_turn()

    assert_that((_attaches(plugin), name in _context(plugin.start_turn())), equal_to(([], False)))


def test_files_with_the_same_name_in_different_folders_are_both_attached(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    (plugin.workspace / "a").mkdir()
    (plugin.workspace / "b").mkdir()
    first = _wrote(plugin, "call-1", "a/report.md")
    second = _wrote(plugin, "call-3", "b/report.md")
    _created_task(plugin)

    plugin.end_turn()

    assert_that(_attaches(plugin), equal_to([["attach", _TASK_ID, first], ["attach", _TASK_ID, second]]))


def test_a_failed_file_write_is_not_a_produced_file(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.tool_call(
        "call-1",
        tool_name="write_file",
        args={"path": "states.csv", "content": "a,b"},
        result=json.dumps({"error": "Permission denied"}),
    )

    plugin.end_turn()

    assert_that(_creates(plugin), equal_to([]))


@pytest.mark.parametrize(
    ("command", "result"),
    [
        ("agentbarn-task create --title=States", {"output": "refused", "exit_code": 1, "error": None}),
        ("grep 'agentbarn-task create' notes.md", {"output": "agentbarn-task create", "exit_code": 0, "error": None}),
    ],
)
def test_a_task_command_that_failed_or_was_only_mentioned_does_not_count(tmp_path: Path, command: str, result: dict):
    plugin = _Plugin(tmp_path)
    _wrote(plugin)
    plugin.tool_call("call-2", command=command, result=json.dumps(result))

    plugin.end_turn()

    assert_that(len(_creates(plugin)), equal_to(1))


def test_files_a_patch_created_are_attached(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    notes = plugin.workspace / "notes.md"
    notes.write_text("hi\n")
    plugin.tool_call(
        "call-1",
        tool_name="patch",
        args={"mode": "patch", "patch": "*** Begin Patch\n*** Add File: notes.md\n+hi\n*** End Patch"},
        result=json.dumps({"success": True, "files_created": [str(notes)], "files_modified": []}),
    )
    _created_task(plugin)

    plugin.end_turn()

    assert_that(_attaches(plugin), equal_to([["attach", _TASK_ID, str(notes), "--replace"]]))


def test_a_file_the_agent_published_is_attached(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    (plugin.workspace / "states.csv").write_text("a,b\n")
    plugin.tool_call(
        "call-1",
        command="cd /workspace && /usr/local/bin/agentbarn-artifacts upload states.csv",
        result=json.dumps({"output": "{}", "exit_code": 0, "error": None}),
    )
    _created_task(plugin)

    plugin.end_turn()

    assert_that(_attaches(plugin), equal_to([["attach", _TASK_ID, str(plugin.workspace / "states.csv"), "--replace"]]))


def test_a_failed_publish_is_not_attached(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    (plugin.workspace / "states.csv").write_text("a,b\n")
    plugin.tool_call(
        "call-1",
        command="agentbarn-artifacts upload states.csv",
        result=json.dumps({"output": "refused", "exit_code": 1, "error": None}),
    )
    _created_task(plugin)

    plugin.end_turn()

    assert_that(_attaches(plugin), equal_to([]))


def test_the_task_command_run_by_its_full_path_counts_as_recording(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _wrote(plugin)
    plugin.tool_call(
        "call-2",
        command="/usr/local/bin/agentbarn-task create --title=States",
        result=json.dumps({"output": "{}", "exit_code": 0, "error": None}),
    )

    plugin.end_turn()

    assert_that(_creates(plugin), equal_to([]))


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


# --- starting a Task in progress, and the request line ---


def test_create_passes_a_starting_status(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    plugin.tool(action="create", title="Report", status="in_progress")

    assert_that(plugin.calls()[-1]["argv"], equal_to(["create", "--title=Report", "--status=in_progress"]))


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
        equal_to(["create", "--title=Report", "--status=in_progress", "--note=Started from the October export"]),
    )
    assert_that(plugin.calls()[-1]["argv"], equal_to(["status", _TASK_ID, "failed", "--note=The export was empty"]))


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


def test_a_task_left_in_progress_is_reopened_when_the_turn_did_not_complete(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    states = _wrote(plugin)
    _created_task(plugin)

    plugin.end_turn(completed=False)

    assert_that(_statuses(plugin), equal_to([["status", _TASK_ID, "open"]]))
    assert_that(_attaches(plugin), equal_to([["attach", _TASK_ID, states, "--replace"]]))


def test_every_task_left_in_progress_is_closed(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _created_task(plugin, "call-1", "task-1")
    _created_task(plugin, "call-2", "task-2")

    plugin.end_turn()

    assert_that(sorted(_statuses(plugin)), equal_to([["status", "task-1", "done"], ["status", "task-2", "done"]]))


def _kept_task(plugin: _Plugin, call_id: str = "call-2", action: str = "create", keep=True):
    args = {"action": action, "keep": keep, "status": "in_progress"}
    args |= {"title": "States"} if action == "create" else {"task_id": _TASK_ID}
    return plugin.tool_call(
        call_id, tool_name="agentbarn_task", args=args, result=json.dumps({"id": _TASK_ID, "status": "in_progress"})
    )


@pytest.mark.parametrize("action", ["create", "status"])
def test_a_task_the_agent_keeps_stays_in_progress_when_the_turn_ends(tmp_path: Path, action: str):
    plugin = _Plugin(tmp_path)
    _kept_task(plugin, action=action)

    plugin.end_turn()

    assert_that(_statuses(plugin), equal_to([]))


def test_keep_given_as_text_is_honoured(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _kept_task(plugin, keep="true")

    plugin.end_turn()

    assert_that(_statuses(plugin), equal_to([]))


def test_a_task_reopened_without_keep_is_marked_done_when_the_turn_ends(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.tool_call(
        "call-1", tool_name="agentbarn_task", args={"action": "status", "task_id": _TASK_ID, "status": "in_progress"}
    )

    plugin.end_turn()

    assert_that(_statuses(plugin), equal_to([["status", _TASK_ID, "done"]]))


def test_the_last_status_call_in_a_turn_wins_over_keep(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _kept_task(plugin)
    plugin.tool_call(
        "call-3", tool_name="agentbarn_task", args={"action": "status", "task_id": _TASK_ID, "status": "in_progress"}
    )

    plugin.end_turn()

    assert_that(_statuses(plugin), equal_to([["status", _TASK_ID, "done"]]))


def test_a_kept_task_is_reopened_when_the_turn_did_not_complete(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    _kept_task(plugin)

    plugin.end_turn(completed=False)

    assert_that(_statuses(plugin), equal_to([["status", _TASK_ID, "open"]]))


def test_keep_is_not_passed_to_the_task_command(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    plugin.tool(action="create", title="Report", keep=True)
    created = plugin.calls()[-1]["argv"]
    plugin.tool(action="status", task_id=_TASK_ID, status="in_progress", keep=True)

    assert_that(created, equal_to(["create", "--title=Report", "--status=in_progress"]))
    assert_that(plugin.calls()[-1]["argv"], equal_to(["status", _TASK_ID, "in_progress"]))


def test_the_tool_offers_keep(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    schema = plugin.tools["agentbarn_task"]["schema"]

    assert_that(schema["parameters"]["properties"]["keep"]["type"], equal_to("boolean"))
    assert_that(schema["description"], contains_string("keep"))


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

    assert_that(len([call for call in plugin.calls() if call["argv"][0] == "list"]), equal_to(2))


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


# --- work the Agent left unrecorded ---


def _creates(plugin: _Plugin) -> list[list[str]]:
    return [call["argv"] for call in plugin.calls() if call["argv"][0] == "create"]


def _option(argv: list[str], name: str) -> str:
    return next(arg.split("=", 1)[1] for arg in argv if arg.startswith(f"--{name}="))


def test_work_left_unrecorded_is_recorded_automatically_when_the_turn_ends(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.start_turn(user_message="Please summarise the October invoices")
    for n in range(1, 4):
        plugin.tool_call(f"call-{n}")

    plugin.end_turn()

    assert_that(
        _creates(plugin),
        equal_to(
            [
                [
                    "create",
                    "--title=Please summarise the October invoices",
                    "--status=done",
                    "--origin=automatic",
                    "--description=Please summarise the October invoices",
                ]
            ]
        ),
    )


def test_the_automatic_task_gets_the_files_the_turn_wrote(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.start_turn(user_message="Write the states CSV")
    states = _wrote(plugin)

    plugin.end_turn()

    assert_that(_attaches(plugin), equal_to([["attach", _TASK_ID, states, "--replace"]]))


def test_a_long_request_is_shortened_for_the_automatic_title(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    request = "Please " + "compare these regional sales figures " * 10
    plugin.start_turn(user_message=request)
    _wrote(plugin)

    plugin.end_turn()

    title = _option(_creates(plugin)[0], "title")
    assert_that((len(title), title.endswith("…")), equal_to((120, True)))


@pytest.mark.parametrize("completed", [True, False])
def test_nothing_is_recorded_automatically_for_a_short_or_unfinished_turn(tmp_path: Path, completed: bool):
    plugin = _Plugin(tmp_path)
    plugin.start_turn()
    plugin.tool_call("call-1")
    if not completed:
        _wrote(plugin, "call-2")

    plugin.end_turn(completed=completed)

    assert_that(_creates(plugin), equal_to([]))


def test_a_turn_the_agent_recorded_is_not_recorded_again(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.start_turn()
    _wrote(plugin)
    _created_task(plugin)

    plugin.end_turn()

    assert_that(_creates(plugin), equal_to([]))


def test_the_next_turn_carries_no_catch_up_reminder(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.start_turn()
    _wrote(plugin)
    plugin.end_turn()

    assert_that("did work without recording" in _context(plugin.start_turn()), is_(False))


def test_review_and_subagent_runs_are_left_alone(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.start_turn(user_message="Write the states CSV")

    context = plugin.start_turn(
        user_message="Review the conversation above", turn_id="review-1", parent_session_id="s1"
    )
    reminders = [plugin.tool_call(f"call-{n}", turn_id="review-1") for n in range(1, 5)]
    plugin.end_turn(turn_id="review-1")

    assert_that((context, reminders, _creates(plugin)), equal_to((None, [None] * 4, [])))


# --- only a Task the turn actually wrote counts as recording it ---


def test_reading_tasks_does_not_count_as_recording(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.start_turn()
    plugin.tool_call("call-0", tool_name="agentbarn_task", args={"action": "list"}, result='{"items": []}')

    reminders = [plugin.tool_call(f"call-{n}") for n in range(1, 4)]
    plugin.end_turn()

    assert_that(reminders[2], contains_string("agentbarn_task"))
    assert_that(len(_creates(plugin)), equal_to(1))


def test_a_task_call_that_failed_does_not_count_as_recording(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.start_turn(user_message="Write the states CSV")
    states = _wrote(plugin)
    plugin.tool_call(
        "call-2",
        tool_name="agentbarn_task",
        args={"action": "status", "task_id": "task-gone", "status": "in_progress"},
        result=json.dumps({"error": "Task not found."}),
    )

    plugin.end_turn()

    assert_that(len(_creates(plugin)), equal_to(1))
    assert_that(_attaches(plugin), equal_to([["attach", _TASK_ID, states, "--replace"]]))
    assert_that([argv for argv in _statuses(plugin) if "task-gone" in argv], equal_to([]))


@pytest.mark.parametrize("command", ["agentbarn-task --help", "agentbarn-task list", "agentbarn-task show abc"])
def test_reading_tasks_from_the_terminal_does_not_count_as_recording(tmp_path: Path, command: str):
    plugin = _Plugin(tmp_path)

    plugin.tool_call("call-0", command=command)
    reminders = [plugin.tool_call(f"call-{n}") for n in range(1, 4)]

    assert_that(any(reminders), is_(True))


# --- listing Tasks each turn stays cheap and bounded ---


def test_open_and_finished_tasks_come_from_one_list_call(tmp_path: Path):
    plugin = _Plugin(tmp_path)

    plugin.start_turn()

    assert_that([call["argv"] for call in plugin.calls()], equal_to([["list", "--page-size=100"]]))


def test_a_failed_listing_is_not_retried_on_every_turn(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.env["FAKE_TASK_LIST_FAIL"] = "1"

    plugin.start_turn()
    plugin.start_turn()

    assert_that(len(plugin.calls()), equal_to(1))


def test_a_slow_listing_does_not_hold_up_the_turn(tmp_path: Path):
    plugin = _Plugin(tmp_path, open_tasks=[{"id": "task-1", "title": "Report", "status": "open"}])
    plugin.env["FAKE_TASK_LIST_SLEEP"] = "60"

    started = time.monotonic()
    context = _context(plugin.start_turn())

    assert_that((time.monotonic() - started < 25, "task-1" in context), equal_to((True, False)))


# --- the automatic Task does not keep secrets from the request ---


_SECRET_REQUESTS = [
    ("Deploy it with ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8 tonight", "ghp_A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"),
    ("Call the API using sk-ant-api03-abcdefghijklmnop1234567890", "abcdefghijklmnop1234567890"),
    ("Log in, the password: hunter2! is on the wiki", "hunter2!"),
    ("Back up postgres://admin:s3cretpw@db.internal/app tonight", "s3cretpw"),
    ("Rotate AKIAIOSFODNN7EXAMPLE this week", "AKIAIOSFODNN7EXAMPLE"),
    (
        "Check Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        "dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    ),
    ("Use token=Zx8kQ2mN7pL4vR9tY3wB6cD1fG5hJ0sA to fetch", "Zx8kQ2mN7pL4vR9tY3wB6cD1fG5hJ0sA"),
    ("Set DB_PASSWORD=hunter2 in production", "hunter2"),
    ("Export GITHUB_TOKEN=abc123 before the run", "abc123"),
    ("Add aws_secret_access_key=wJalrXUtnFEMI to the profile", "wJalrXUtnFEMI"),
    ('Write {"password": "hunter2"} into the config', "hunter2"),
]


@pytest.mark.parametrize(("request_text", "secret"), _SECRET_REQUESTS)
def test_secrets_in_the_request_are_redacted_from_the_automatic_task(tmp_path: Path, request_text: str, secret: str):
    plugin = _Plugin(tmp_path)
    plugin.start_turn(user_message=request_text)
    _wrote(plugin)

    plugin.end_turn()

    [create] = _creates(plugin)
    title, description = _option(create, "title"), _option(create, "description")
    assert_that((secret in title, secret in description), equal_to((False, False)))
    assert_that(description, contains_string("[redacted]"))


def test_a_request_that_looks_like_an_option_is_still_recorded(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.start_turn(user_message="-v")
    _wrote(plugin)

    plugin.end_turn()

    assert_that(_option(_creates(plugin)[0], "title"), equal_to("-v"))


# --- what the plugin remembers stays bounded ---


def test_only_the_latest_sessions_requests_are_kept(tmp_path: Path):
    plugin = _Plugin(tmp_path)
    plugin.start_turn(session_id="first", user_message="Write the states CSV")
    for n in range(_SESSIONS_KEPT):
        plugin.start_turn(session_id=f"later-{n}", user_message="Hello there, do something")
    plugin.tool_call("call-9", session_id="first", tool_name="write_file", args={"path": "states.csv"})

    plugin.end_turn(session_id="first", turn_id="turn-1")

    assert_that(_option(_creates(plugin)[0], "title"), equal_to("Work recorded automatically"))


# --- schedules: a Task follows the schedule it was created for ---

_JOB_ID = "a1b2c3d4e5f6"
_CRON_SESSION = f"cron_{_JOB_ID}_20261117_101500"
_GREETING = "Post a greeting every minute, 7 times. It is done after 7 greetings."


def _scheduling(tmp_path: Path, intent: str | None = "runs") -> _Plugin:
    plugin = _Plugin(tmp_path)
    plugin.home = tmp_path / "home"
    (plugin.home / "cron").mkdir(parents=True)
    plugin.env["HERMES_HOME"] = str(plugin.home)
    if intent:
        plugin.env["FAKE_SCHEDULE_INTENT"] = intent
    return plugin


def _jobs(plugin: _Plugin, *jobs: dict) -> None:
    (plugin.home / "cron" / "jobs.json").write_text(json.dumps({"jobs": list(jobs)}))


def _job(completed: int = 0, times: int | None = 7, kind: str = "interval", state: str = "scheduled") -> dict:
    return {
        "id": _JOB_ID,
        "name": "greeting",
        "schedule": {"kind": kind},
        "repeat": {"times": times, "completed": completed},
        "state": state,
        "enabled": state == "scheduled",
    }


def _links(plugin: _Plugin) -> dict:
    path = plugin.home / "agentbarn-task-schedules.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _linked(plugin: _Plugin, task_id: str = _TASK_ID) -> None:
    (plugin.home / "agentbarn-task-schedules.json").write_text(json.dumps({_JOB_ID: {"task_id": task_id}}))


def _schedule_created(plugin: _Plugin, call_id: str = "call-s", schedule: str = "every 1m", repeat: int | None = 7):
    args = {"action": "create", "schedule": schedule, "prompt": "Post a greeting", "name": "greeting"}
    if repeat is not None:
        args["repeat"] = repeat
    result = {"success": True, "job_id": _JOB_ID, "name": "greeting", "schedule": schedule}
    return plugin.tool_call(call_id, tool_name="cronjob", args=args, result=json.dumps(result))


def _task_recorded(plugin: _Plugin, status: str = "done", keep: bool = False):
    args = {"action": "create", "title": "Greetings for a week", "status": status}
    if keep:
        args["keep"] = True
    return plugin.tool_call(
        "call-t", tool_name="agentbarn_task", args=args, result=json.dumps({"id": _TASK_ID, "status": status})
    )


def _argvs(plugin: _Plugin, command: str) -> list[list[str]]:
    return [call["argv"] for call in plugin.calls() if call["argv"][0] == command]


def test_a_task_whose_job_is_the_runs_stays_in_progress_and_follows_the_schedule(tmp_path: Path):
    plugin = _scheduling(tmp_path, intent="runs")
    plugin.start_turn(user_message=_GREETING, turn_id="turn-1")
    _schedule_created(plugin)
    _task_recorded(plugin, status="done")

    plugin.end_turn()

    asked = json.loads(next(call["stdin"] for call in plugin.calls() if call["argv"][0] == "schedule-intent"))
    assert_that(
        asked,
        has_entries(
            request=_GREETING,
            schedule=has_entries(recurrence="every 1m", run_limit=7),
            task=has_entries(title="Greetings for a week", status="done"),
        ),
    )
    assert_that(_statuses(plugin), equal_to([["status", _TASK_ID, "in_progress"]]))
    assert_that(_links(plugin), equal_to({_JOB_ID: {"task_id": _TASK_ID}}))


def test_a_task_whose_job_was_setting_up_the_schedule_is_done_even_if_the_agent_kept_it(tmp_path: Path):
    plugin = _scheduling(tmp_path, intent="setup")
    plugin.start_turn(user_message="Remind me every morning to check the build", turn_id="turn-1")
    _schedule_created(plugin, schedule="0 9 * * *", repeat=None)
    _task_recorded(plugin, status="in_progress", keep=True)

    plugin.end_turn()

    assert_that(_statuses(plugin), equal_to([["status", _TASK_ID, "done"]]))
    assert_that(_links(plugin), equal_to({}))


@pytest.mark.parametrize(
    ("keep", "linked", "statuses"), [(True, True, []), (False, False, [["status", _TASK_ID, "done"]])]
)
def test_without_a_decision_the_agents_own_choice_stands(tmp_path: Path, keep: bool, linked: bool, statuses: list):
    plugin = _scheduling(tmp_path, intent=None)
    plugin.start_turn(user_message=_GREETING, turn_id="turn-1")
    _schedule_created(plugin)
    _task_recorded(plugin, status="in_progress", keep=keep)

    plugin.end_turn()

    assert_that(_statuses(plugin), equal_to(statuses))
    assert_that(bool(_links(plugin)), equal_to(linked))


def test_a_schedule_whose_runs_are_the_job_gets_a_task_when_the_agent_recorded_none(tmp_path: Path):
    plugin = _scheduling(tmp_path, intent="runs")
    plugin.start_turn(user_message=_GREETING, turn_id="turn-1")
    _schedule_created(plugin)

    plugin.end_turn()

    created = _argvs(plugin, "create")
    assert_that(len(created), equal_to(1))
    assert_that(created[0], has_items("--status=in_progress", "--origin=automatic"))
    assert_that(_links(plugin), equal_to({_JOB_ID: {"task_id": _TASK_ID}}))


def test_a_standing_schedule_with_no_task_recorded_gets_none(tmp_path: Path):
    plugin = _scheduling(tmp_path, intent="setup")
    plugin.start_turn(user_message="Remind me every morning to check the build", turn_id="turn-1")
    _schedule_created(plugin, schedule="0 9 * * *", repeat=None)

    plugin.end_turn()

    assert_that(_argvs(plugin, "create"), equal_to([]))


def _scheduled_run(plugin: _Plugin, reply: str = "Good morning, team!", tools: int = 0, completed: bool = True):
    plugin.start_turn(session_id=_CRON_SESSION, user_message="Post a greeting", turn_id="run-1")
    for index in range(tools):
        plugin.tool_call(f"work-{index}", session_id=_CRON_SESSION, turn_id="run-1")
    with patch.dict(os.environ, plugin.env, clear=True):
        plugin.hooks["post_llm_call"](
            session_id=_CRON_SESSION, turn_id="run-1", user_message="Post a greeting", assistant_response=reply
        )
    plugin.end_turn(session_id=_CRON_SESSION, turn_id="run-1", completed=completed)


def test_a_scheduled_run_is_noted_on_its_task_without_the_agent_doing_anything(tmp_path: Path):
    plugin = _scheduling(tmp_path)
    _linked(plugin)
    _jobs(plugin, _job(completed=2))

    _scheduled_run(plugin, tools=4)

    notes = [call for call in plugin.calls() if call["argv"][:2] == ["note", _TASK_ID]]
    assert_that(len(notes), equal_to(1))
    assert_that(notes[0]["stdin"], equal_to("Run 3 of 7: Good morning, team!"))
    assert_that(_statuses(plugin), equal_to([]))
    assert_that(_argvs(plugin, "create"), equal_to([]))


def test_the_last_scheduled_run_marks_the_task_done_and_ends_the_link(tmp_path: Path):
    plugin = _scheduling(tmp_path)
    _linked(plugin)
    _jobs(plugin, _job(completed=6))

    _scheduled_run(plugin)

    assert_that(plugin.calls()[-2]["stdin"], equal_to("Run 7 of 7: Good morning, team!"))
    assert_that(_statuses(plugin), equal_to([["status", _TASK_ID, "done"]]))
    assert_that(_links(plugin), equal_to({}))


def test_a_one_off_schedule_finishes_its_task_when_it_has_run(tmp_path: Path):
    plugin = _scheduling(tmp_path)
    _linked(plugin)
    _jobs(plugin, _job(completed=1, times=1, kind="once"))

    _scheduled_run(plugin)

    assert_that(_statuses(plugin), equal_to([["status", _TASK_ID, "done"]]))


def test_a_schedule_with_no_end_keeps_its_task_in_progress(tmp_path: Path):
    plugin = _scheduling(tmp_path)
    _linked(plugin)
    _jobs(plugin, _job(completed=41, times=None))

    _scheduled_run(plugin)

    assert_that(next(call["stdin"] for call in plugin.calls() if call["argv"][0] == "note"), contains_string("Run 42:"))
    assert_that(_statuses(plugin), equal_to([]))
    assert_that(bool(_links(plugin)), equal_to(True))


def test_a_task_the_agent_closed_during_an_earlier_run_is_put_back_in_progress(tmp_path: Path):
    plugin = _scheduling(tmp_path)
    _linked(plugin)
    _jobs(plugin, _job(completed=2))
    plugin.start_turn(session_id=_CRON_SESSION, user_message="Post a greeting", turn_id="run-1")
    plugin.tool_call(
        "call-1",
        session_id=_CRON_SESSION,
        turn_id="run-1",
        tool_name="agentbarn_task",
        args={"action": "status", "task_id": _TASK_ID, "status": "done"},
    )

    plugin.end_turn(session_id=_CRON_SESSION, turn_id="run-1")

    assert_that(_statuses(plugin), equal_to([["status", _TASK_ID, "in_progress"]]))


def test_a_run_of_a_schedule_with_no_task_is_handled_as_before(tmp_path: Path):
    plugin = _scheduling(tmp_path)
    _jobs(plugin, _job(completed=2))

    _scheduled_run(plugin, tools=3)

    assert_that(_argvs(plugin, "note"), equal_to([]))
    assert_that(len(_argvs(plugin, "create")), equal_to(1))


def test_removing_the_schedule_finishes_its_task(tmp_path: Path):
    plugin = _scheduling(tmp_path)
    _linked(plugin)
    _jobs(plugin)
    plugin.start_turn(user_message="Stop the greetings", turn_id="turn-1")
    plugin.tool_call(
        "call-1", tool_name="cronjob", args={"action": "remove", "job_id": _JOB_ID}, result='{"success": true}'
    )

    plugin.end_turn()

    assert_that(_statuses(plugin), equal_to([["status", _TASK_ID, "done"]]))
    assert_that(_links(plugin), equal_to({}))


def test_a_schedule_that_ended_while_nobody_was_looking_finishes_its_task_on_the_next_turn(tmp_path: Path):
    plugin = _scheduling(tmp_path)
    _linked(plugin)
    _jobs(plugin, _job(completed=7, state="completed"))
    plugin.start_turn(user_message="hello there, how are things going today?", turn_id="turn-1")
    plugin.tool_call("call-1")

    plugin.end_turn()

    assert_that(_statuses(plugin), equal_to([["status", _TASK_ID, "done"]]))
    assert_that(_links(plugin), equal_to({}))


def test_links_are_left_alone_when_the_schedules_cannot_be_read(tmp_path: Path):
    plugin = _scheduling(tmp_path)
    _linked(plugin)
    (plugin.home / "cron" / "jobs.json").write_text("{not json")
    plugin.start_turn(user_message="hello there, how are things going today?", turn_id="turn-1")
    plugin.tool_call("call-1")

    plugin.end_turn()

    assert_that(_statuses(plugin), equal_to([]))
    assert_that(bool(_links(plugin)), equal_to(True))


def test_a_scheduled_run_reported_twice_is_noted_once(tmp_path: Path):
    plugin = _scheduling(tmp_path)
    _linked(plugin)
    _jobs(plugin, _job(completed=2))
    _scheduled_run(plugin, tools=3)

    plugin.end_turn(session_id=_CRON_SESSION, turn_id="run-1")

    assert_that(len(_argvs(plugin, "note")), equal_to(1))
    assert_that(_argvs(plugin, "create"), equal_to([]))

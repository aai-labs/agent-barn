"""The OpenClaw agentbarn-tasks plugin: a typed Task tool, open Tasks each turn, and reminders."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_entries, is_, is_not

_PLUGIN_DIR = Path(__file__).parents[2] / "domains/agents/scripts/openclaw/plugins/agentbarn-tasks"
_DRIVER = Path(__file__).parents[1] / "fixtures/agent_tasks/openclaw_tasks_plugin_driver.mjs"
_FAKE_COMMAND = Path(__file__).parents[1] / "fixtures/agent_tasks/fake_task_command.py"
_TASK_ID = "0199f1d2-0000-7000-8000-0000000000aa"
_SESSIONS_KEPT = 500
_PARENT_ID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
_BOT_ID = "0000000b-0000-4000-8000-00000000000b"
_BOT_IDENTITY = {
    "AGENT_ID": _BOT_ID,
    "INGEST_URL": "http://ingest/bot",
    "INGEST_API_KEY": "bot-ingest-key",
    "ARTIFACT_URL": "http://artifacts/bot",
    "ARTIFACT_API_KEY": "bot-artifact-key",
}


def _drive(tmp_path: Path, steps: list[dict], open_tasks: list[dict] | None = None, **env: str) -> dict:
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("node is required to exercise the OpenClaw plugin")
    workspace = tmp_path / ".openclaw" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    wrapper = tmp_path / "agentbarn-task"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{_FAKE_COMMAND}" "$@"\n')
    wrapper.chmod(0o755)
    steps_path = tmp_path / "steps.json"
    steps_path.write_text(json.dumps(steps))
    completed = subprocess.run(
        [node, str(_DRIVER), str(_PLUGIN_DIR / "index.js"), str(steps_path)],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env={
            "PATH": os.environ["PATH"],
            "HOME": str(tmp_path),
            "AGENT_ID": _PARENT_ID,
            "INGEST_URL": "http://localhost:8001/ingest/v1",
            "INGEST_API_KEY": "test-key-123",
            "AGENTBARN_TASK_COMMAND": str(wrapper),
            "FAKE_TASK_LOG": str(tmp_path / "calls.jsonl"),
            "FAKE_TASK_LIST": json.dumps(open_tasks or []),
            **env,
        },
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _calls(tmp_path: Path) -> list[dict]:
    log = tmp_path / "calls.jsonl"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def _tool(**params) -> dict:
    return {"tool": params}


def _tool_output(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


def _after_tool(
    call_id: str,
    run_id: str = "run-1",
    session: str = "s1",
    tool: str = "exec",
    command: str = "ls",
    trigger: str = "user",
    params: dict | None = None,
    result: dict | None = None,
    error: str | None = None,
) -> dict:
    return {
        "hook": "after_tool_call",
        "event": {
            "toolName": tool,
            "params": params if params is not None else {"command": command},
            "runId": run_id,
            "toolCallId": call_id,
            **({"result": result} if result is not None else {}),
            **({"error": error} if error is not None else {}),
        },
        "ctx": {"sessionKey": session, "runId": run_id, "trigger": trigger},
    }


def _finalize(run_id: str = "run-1", session: str = "s1") -> dict:
    return {
        "hook": "before_agent_finalize",
        "event": {"runId": run_id, "sessionKey": session, "lastAssistantMessage": "Done."},
        "ctx": {"sessionKey": session, "runId": run_id, "trigger": "user"},
    }


def _agent_end(run_id: str = "run-1", session: str = "s1", success: bool = True, trigger: str = "user") -> dict:
    return {
        "hook": "agent_end",
        "event": {"runId": run_id, "success": success, "messages": []},
        "ctx": {"sessionKey": session, "runId": run_id, "trigger": trigger},
    }


def _prompt(session: str = "s1", trigger: str = "user", prompt: str = "Please summarise the October invoices") -> dict:
    return {
        "hook": "before_prompt_build",
        "event": {"prompt": prompt, "messages": []},
        "ctx": {"sessionKey": session, "trigger": trigger},
    }


def _context(result) -> str:
    return (result or {}).get("appendContext", "")


# --- registration ---


def test_the_task_tool_and_turn_hooks_are_registered(tmp_path: Path):
    driven = _drive(tmp_path, [])

    assert_that(
        driven["hooks"],
        equal_to(
            [
                "after_tool_call",
                "agent_end",
                "before_agent_finalize",
                "before_prompt_build",
                "cron_changed",
                "tool_result_persist",
            ]
        ),
    )
    [tool] = driven["tools"]
    assert_that(tool["name"], equal_to("agentbarn_task"))
    assert_that(
        sorted(tool["parameters"]["properties"]["action"]["enum"]),
        equal_to(["attach", "create", "list", "note", "remove_file", "show", "status"]),
    )


def test_nothing_is_registered_without_the_ingest_credentials(tmp_path: Path):
    driven = _drive(tmp_path, [], INGEST_API_KEY="")

    assert_that((driven["hooks"], driven["tools"]), equal_to(([], [])))


def test_the_manifest_declares_the_tool_it_registers():
    manifest = json.loads((_PLUGIN_DIR / "openclaw.plugin.json").read_text())

    assert_that(manifest, has_entries(id="agentbarn-tasks", contracts={"tools": ["agentbarn_task"]}))


# --- the tool ---


@pytest.mark.parametrize(
    ("params", "argv", "stdin"),
    [
        (
            {"action": "create", "title": "Reconcile invoices", "description": "For October"},
            ["create", "--title=Reconcile invoices", "--description=For October", "--status=in_progress"],
            "",
        ),
        ({"action": "status", "task_id": _TASK_ID, "status": "done"}, ["status", _TASK_ID, "done"], ""),
        ({"action": "note", "task_id": _TASK_ID, "body": "Matched 40 of 42"}, ["note", _TASK_ID], "Matched 40 of 42"),
        ({"action": "list", "status": "open"}, ["list", "--status=open"], ""),
        ({"action": "show", "task_id": _TASK_ID}, ["show", _TASK_ID], ""),
        (
            {"action": "attach", "task_id": _TASK_ID, "path": "report.csv", "name": "October.csv"},
            ["attach", _TASK_ID, "report.csv", "--name=October.csv", "--replace"],
            "",
        ),
    ],
)
def test_each_action_maps_onto_the_task_command(tmp_path: Path, params: dict, argv: list[str], stdin: str):
    _drive(tmp_path, [_tool(**params)])

    call = _calls(tmp_path)[-1]
    assert_that((call["argv"], call["stdin"]), equal_to((argv, stdin)))


def test_files_are_found_relative_to_the_agents_workspace(tmp_path: Path):
    _drive(tmp_path, [_tool(action="attach", task_id=_TASK_ID, path="report.csv")])

    workspace = tmp_path / ".openclaw" / "workspace"
    assert_that(os.path.realpath(_calls(tmp_path)[-1]["cwd"]), equal_to(os.path.realpath(workspace)))


def test_the_tool_returns_the_commands_answer(tmp_path: Path):
    driven = _drive(tmp_path, [_tool(action="create", title="Report")])

    assert_that(_tool_output(driven["results"][0]), has_entries(id=_TASK_ID))


def test_a_refusal_is_returned_to_the_model_as_an_error(tmp_path: Path):
    driven = _drive(tmp_path, [_tool(action="create", title="fail")])

    assert_that(_tool_output(driven["results"][0]), has_entries(error=contains_string("not allowed")))


def test_a_missing_required_argument_is_returned_without_running_the_command(tmp_path: Path):
    driven = _drive(tmp_path, [_tool(action="status", task_id=_TASK_ID)])

    assert_that((_tool_output(driven["results"][0]).get("error") is not None, _calls(tmp_path)), equal_to((True, [])))


# --- reminders ---


def test_a_run_doing_real_work_without_a_task_is_asked_to_revise_once(tmp_path: Path):
    driven = _drive(tmp_path, [_after_tool("c1"), _after_tool("c2"), _after_tool("c3"), _finalize(), _finalize()])

    first, second = driven["results"][3], driven["results"][4]
    assert_that(first, has_entries(action="revise"))
    assert_that(first["retry"], has_entries(maxAttempts=1, instruction=contains_string("agentbarn_task")))
    assert_that(second, is_(None))


def test_a_run_that_records_a_task_is_not_asked_to_revise(tmp_path: Path):
    driven = _drive(
        tmp_path,
        [
            _created("c0"),
            _after_tool("c1"),
            _after_tool("c2"),
            _after_tool("c3"),
            _finalize(),
        ],
    )

    assert_that(driven["results"][-1], is_(None))


def test_using_the_task_command_from_exec_counts_as_recording(tmp_path: Path):
    driven = _drive(
        tmp_path,
        [
            _after_tool("c0", command="agentbarn-task create --title Report"),
            _after_tool("c1"),
            _after_tool("c2"),
            _after_tool("c3"),
            _finalize(),
        ],
    )

    assert_that(driven["results"][-1], is_(None))


def test_a_short_run_is_not_reminded(tmp_path: Path):
    driven = _drive(tmp_path, [_after_tool("c1"), _after_tool("c2"), _finalize(), _agent_end(), _prompt()])

    assert_that(driven["results"][2], is_(None))
    assert_that("did work without recording" in _context(driven["results"][4]), is_(False))


def test_heartbeat_runs_are_not_reminded(tmp_path: Path):
    steps = [_after_tool(f"c{n}", trigger="heartbeat") for n in range(1, 4)]
    driven = _drive(tmp_path, [*steps, _agent_end(trigger="heartbeat"), _prompt()])

    assert_that("did work without recording" in _context(driven["results"][-1]), is_(False))


# --- open Tasks each turn ---


def test_an_unfinished_tasks_latest_note_is_shown_with_it(tmp_path: Path):
    driven = _drive(
        tmp_path,
        [_prompt()],
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

    context = _context(driven["results"][0])

    assert_that(context, contains_string('task-1 [in_progress] Weekly greetings (latest note: "Greeting 5 of 7 sent")'))
    assert_that(context, contains_string("task-2 [open] Draft summary\n"))
    assert_that(context, contains_string("task-3 [done] Old work\n"))
    assert_that(context, contains_string('task-4 [open] Long (latest note: "' + "x" * 200 + '…")'))


def test_each_turn_starts_with_the_agents_open_tasks(tmp_path: Path):
    driven = _drive(
        tmp_path,
        [_prompt()],
        open_tasks=[
            {"id": "task-1", "title": "Reconcile invoices", "status": "in_progress"},
            {"id": "task-2", "title": "Draft summary", "status": "open"},
            {"id": "task-3", "title": "Old work", "status": "done"},
        ],
    )

    context = _context(driven["results"][0])
    assert_that(context, contains_string("task-1 [in_progress] Reconcile invoices"))
    assert_that(context, contains_string("task-2 [open] Draft summary"))
    assert_that(context, contains_string("task-3 [done] Old work"))
    assert_that(context, contains_string("only when the request is the same piece of work"))
    assert_that(context, contains_string("A new request gets its own Task, even while another is in progress"))


def test_open_tasks_are_cached_between_turns_until_a_task_changes(tmp_path: Path):
    _drive(
        tmp_path,
        [_prompt(), _prompt(), _tool(action="status", task_id="task-1", status="done"), _prompt()],
        open_tasks=[{"id": "task-1", "title": "Report", "status": "open"}],
    )

    assert_that(sum(call["argv"][0] == "list" for call in _calls(tmp_path)), equal_to(2))


def test_an_unavailable_task_service_does_not_break_the_turn(tmp_path: Path):
    driven = _drive(tmp_path, [_prompt()], AGENTBARN_TASK_COMMAND="/nonexistent/agentbarn-task")

    context = _context(driven["results"][0])
    assert_that(("Your open Tasks" in context, "agentbarn_task" in context), equal_to((False, True)))


# --- runs that produce files ---


@pytest.mark.parametrize("tool", ["write", "edit", "apply_patch"])
def test_a_run_that_writes_a_file_without_a_task_is_asked_to_revise(tmp_path: Path, tool: str):
    driven = _drive(tmp_path, [_after_tool("c1", tool=tool), _finalize()])

    assert_that(driven["results"][-1], has_entries(action="revise"))


# --- reminders in the tool result the model reads ---


def _persist(call_id: str, tool: str = "write", session: str = "s1") -> dict:
    return {
        "hook": "tool_result_persist",
        "event": {
            "toolName": tool,
            "toolCallId": call_id,
            "message": {"role": "toolResult", "content": [{"type": "text", "text": "ok"}]},
        },
        "ctx": {"sessionKey": session, "toolName": tool, "toolCallId": call_id},
    }


def _persisted_text(result) -> str:
    return " ".join(part.get("text", "") for part in ((result or {}).get("message") or {}).get("content", []))


def test_a_run_doing_real_work_without_a_task_gets_a_reminder_in_the_tool_result_once(tmp_path: Path):
    driven = _drive(
        tmp_path,
        [
            _after_tool("c1", tool="write", params={"path": "states.csv"}),
            _persist("c1"),
            _after_tool("c2", tool="read", params={"path": "states.csv"}),
            _persist("c2", tool="read"),
        ],
    )

    first, second = driven["results"][1], driven["results"][3]
    assert_that(_persisted_text(first), contains_string("ok"))
    assert_that(_persisted_text(first), contains_string("agentbarn_task"))
    assert_that(second, is_(None))


def test_another_sessions_work_does_not_add_a_reminder(tmp_path: Path):
    driven = _drive(tmp_path, [_after_tool("c1", tool="write", params={"path": "a.csv"}), _persist("c1", session="s2")])

    assert_that(driven["results"][-1], is_(None))


# --- files the run produced are attached when it ends ---


def _wrote(tmp_path: Path, call_id: str = "c1", name: str = "states.csv") -> tuple[dict, str]:
    workspace = tmp_path / ".openclaw" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    path = workspace / name
    path.write_text("a,b\n")
    return _after_tool(call_id, tool="write", params={"path": str(path)}), str(path)


def _task(call_id: str, result: dict | None = None, **params) -> dict:
    return _after_tool(call_id, tool="agentbarn_task", params=params, result=result)


def _created(call_id: str = "c2", task_id: str = _TASK_ID) -> dict:
    details = {"id": task_id, "status": "in_progress"}
    return _task(
        call_id,
        result={"content": [{"type": "text", "text": json.dumps(details)}], "details": details},
        action="create",
        title="States",
    )


def _attaches(tmp_path: Path) -> list[list[str]]:
    return [call["argv"] for call in _calls(tmp_path) if call["argv"][0] == "attach"]


def test_files_the_run_wrote_are_attached_to_its_task_when_it_ends(tmp_path: Path):
    wrote_states, states = _wrote(tmp_path)
    wrote_chart, chart = _wrote(tmp_path, "c3", "chart.png")

    _drive(tmp_path, [wrote_states, wrote_chart, _created(), _agent_end()])

    assert_that(
        _attaches(tmp_path),
        equal_to(sorted([["attach", _TASK_ID, chart, "--replace"], ["attach", _TASK_ID, states, "--replace"]])),
    )


def test_files_go_to_a_task_the_run_touched_by_id(tmp_path: Path):
    wrote, states = _wrote(tmp_path)

    _drive(tmp_path, [wrote, _task("c2", action="status", task_id="task-9", status="done"), _agent_end()])

    assert_that(_attaches(tmp_path), equal_to([["attach", "task-9", states, "--replace"]]))


def test_a_file_the_agent_attached_is_not_attached_again(tmp_path: Path):
    wrote, _ = _wrote(tmp_path)

    _drive(
        tmp_path,
        [wrote, _created(), _task("c3", action="attach", task_id=_TASK_ID, path="states.csv"), _agent_end()],
    )

    assert_that(_attaches(tmp_path), equal_to([]))


def test_a_file_that_no_longer_exists_is_not_attached(tmp_path: Path):
    wrote, states = _wrote(tmp_path)
    Path(states).unlink()

    _drive(tmp_path, [wrote, _created(), _agent_end()])

    assert_that(_attaches(tmp_path), equal_to([]))


def test_files_are_not_attached_when_the_run_touched_several_tasks(tmp_path: Path):
    wrote, _ = _wrote(tmp_path)

    driven = _drive(tmp_path, [wrote, _created("c2", "task-1"), _created("c3", "task-2"), _agent_end(), _prompt()])

    assert_that(_attaches(tmp_path), equal_to([]))
    assert_that(_context(driven["results"][-1]), contains_string("states.csv"))


def test_a_file_that_could_not_be_attached_is_named_on_the_next_turn(tmp_path: Path):
    wrote, _ = _wrote(tmp_path)

    driven = _drive(
        tmp_path, [wrote, _created(), _agent_end(), _prompt()], AGENTBARN_TASK_COMMAND="/nonexistent/agentbarn-task"
    )

    assert_that(_context(driven["results"][-1]), contains_string("states.csv"))


def test_a_file_over_the_limit_is_named_on_the_next_turn(tmp_path: Path):
    wrote, _ = _wrote(tmp_path)

    driven = _drive(tmp_path, [wrote, _created(), _agent_end(), _prompt()], ARTIFACT_MAX_BYTES="1")

    assert_that((_attaches(tmp_path), "states.csv" in _context(driven["results"][-1])), equal_to(([], True)))


@pytest.mark.parametrize("name", [".env", ".env.production", "service-account.json", "id_rsa", "server.pem"])
def test_a_credential_file_is_not_attached_automatically(tmp_path: Path, name: str):
    wrote, _ = _wrote(tmp_path, name=name)

    driven = _drive(tmp_path, [wrote, _created(), _agent_end(), _prompt()])

    assert_that((_attaches(tmp_path), name in _context(driven["results"][-1])), equal_to(([], False)))


def test_files_with_the_same_name_in_different_folders_are_both_attached(tmp_path: Path):
    workspace = tmp_path / ".openclaw" / "workspace"
    (workspace / "a").mkdir(parents=True)
    (workspace / "b").mkdir()
    wrote_first, first = _wrote(tmp_path, "c1", "a/report.md")
    wrote_second, second = _wrote(tmp_path, "c3", "b/report.md")

    _drive(tmp_path, [wrote_first, wrote_second, _created(), _agent_end()])

    assert_that(_attaches(tmp_path), equal_to([["attach", _TASK_ID, first], ["attach", _TASK_ID, second]]))


def test_a_failed_file_write_is_not_a_produced_file(tmp_path: Path):
    _drive(
        tmp_path,
        [
            _after_tool("c1", tool="write", params={"path": "states.csv"}, error="EACCES: permission denied"),
            _agent_end(),
        ],
    )

    assert_that(_creates(tmp_path), equal_to([]))


@pytest.mark.parametrize(
    ("command", "exit_code"),
    [("agentbarn-task create --title=States", 1), ("grep 'agentbarn-task create' notes.md", 0)],
)
def test_a_task_command_that_failed_or_was_only_mentioned_does_not_count(tmp_path: Path, command: str, exit_code: int):
    wrote, _ = _wrote(tmp_path)
    result = {"content": [{"type": "text", "text": "out"}], "details": {"status": "completed", "exitCode": exit_code}}

    _drive(tmp_path, [wrote, _after_tool("c2", command=command, result=result), _agent_end()])

    assert_that(len(_creates(tmp_path)), equal_to(1))


def test_files_a_patch_added_are_attached(tmp_path: Path):
    workspace = tmp_path / ".openclaw" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    notes = workspace / "notes.md"
    notes.write_text("hi\n")
    patch = "*** Begin Patch\n*** Add File: notes.md\n+hi\n*** End Patch"
    result = {
        "content": [{"type": "text", "text": "Applied"}],
        "details": {"summary": {"added": ["notes.md"], "modified": [], "deleted": []}},
    }

    _drive(
        tmp_path,
        [_after_tool("c1", tool="apply_patch", params={"input": patch}, result=result), _created(), _agent_end()],
    )

    assert_that(_attaches(tmp_path), equal_to([["attach", _TASK_ID, str(notes), "--replace"]]))


def _exec_result(exit_code: int) -> dict:
    return {"content": [{"type": "text", "text": "out"}], "details": {"status": "completed", "exitCode": exit_code}}


def test_a_file_the_agent_published_is_attached(tmp_path: Path):
    workspace = tmp_path / ".openclaw" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "states.csv").write_text("a,b\n")
    publish = _after_tool("c1", command="/usr/local/bin/agentbarn-artifacts upload states.csv", result=_exec_result(0))

    _drive(tmp_path, [publish, _created(), _agent_end()])

    assert_that(_attaches(tmp_path), equal_to([["attach", _TASK_ID, str(workspace / "states.csv"), "--replace"]]))


def test_a_failed_publish_is_not_attached(tmp_path: Path):
    workspace = tmp_path / ".openclaw" / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "states.csv").write_text("a,b\n")
    publish = _after_tool("c1", command="agentbarn-artifacts upload states.csv", result=_exec_result(1))

    _drive(tmp_path, [publish, _created(), _agent_end()])

    assert_that(_attaches(tmp_path), equal_to([]))


def test_the_task_command_run_by_its_full_path_counts_as_recording(tmp_path: Path):
    wrote, _ = _wrote(tmp_path)
    record = _after_tool("c2", command="/usr/local/bin/agentbarn-task create --title=States", result=_exec_result(0))

    _drive(tmp_path, [wrote, record, _agent_end()])

    assert_that(_creates(tmp_path), equal_to([]))


def test_nothing_about_attaching_is_said_within_the_run_or_after_an_automatic_attach(tmp_path: Path):
    wrote, _ = _wrote(tmp_path)

    driven = _drive(
        tmp_path, [wrote, _created(), _persist("c2", tool="agentbarn_task"), _finalize(), _agent_end(), _prompt()]
    )

    assert_that((driven["results"][2], driven["results"][3]), equal_to((None, None)))
    assert_that("states.csv" in _context(driven["results"][-1]), is_(False))


def test_a_run_that_attached_what_it_wrote_may_finish(tmp_path: Path):
    wrote, _ = _wrote(tmp_path)

    driven = _drive(
        tmp_path, [wrote, _created(), _task("c3", action="attach", task_id="t", path="states.csv"), _finalize()]
    )

    assert_that(driven["results"][-1], is_(None))


# --- the request-time line ---


@pytest.mark.parametrize("trigger", ["user", "cron"])
def test_each_request_carries_the_task_line(tmp_path: Path, trigger: str):
    driven = _drive(tmp_path, [_prompt(trigger=trigger)])

    context = _context(driven["results"][0])
    assert_that(context, contains_string("create a Task with agentbarn_task before you start"))
    assert_that(context, contains_string("Don't mention Tasks in your reply"))


def test_heartbeats_do_not_carry_the_task_line(tmp_path: Path):
    driven = _drive(tmp_path, [_prompt(trigger="heartbeat")])

    assert_that(driven["results"][0], is_(None))


def test_create_passes_a_starting_status(tmp_path: Path):
    _drive(tmp_path, [_tool(action="create", title="Report", status="in_progress")])

    assert_that(_calls(tmp_path)[-1]["argv"], equal_to(["create", "--title=Report", "--status=in_progress"]))


def test_create_starts_the_task_in_progress_by_default(tmp_path: Path):
    _drive(tmp_path, [_tool(action="create", title="Report")])

    assert_that(_calls(tmp_path)[-1]["argv"], equal_to(["create", "--title=Report", "--status=in_progress"]))


def test_remove_file_maps_onto_the_task_command(tmp_path: Path):
    _drive(tmp_path, [_tool(action="remove_file", task_id=_TASK_ID, file_id="0199f1d2-0000-7000-8000-0000000000ff")])

    assert_that(
        _calls(tmp_path)[-1]["argv"], equal_to(["remove-file", _TASK_ID, "0199f1d2-0000-7000-8000-0000000000ff"])
    )


def test_remove_file_needs_a_file_id(tmp_path: Path):
    driven = _drive(tmp_path, [_tool(action="remove_file", task_id=_TASK_ID)])

    assert_that((_tool_output(driven["results"][0]).get("error") is not None, _calls(tmp_path)), equal_to((True, [])))


# --- closing the run's Task, notes in the same call, and small talk ---


def _statuses(tmp_path: Path) -> list[list[str]]:
    return [call["argv"] for call in _calls(tmp_path) if call["argv"][0] == "status"]


def test_create_and_status_carry_a_note_in_the_same_call(tmp_path: Path):
    _drive(
        tmp_path,
        [
            _tool(action="create", title="Report", body="Started from the October export"),
            _tool(action="status", task_id=_TASK_ID, status="failed", body="The export was empty"),
        ],
    )

    assert_that(
        [call["argv"] for call in _calls(tmp_path)],
        equal_to(
            [
                ["create", "--title=Report", "--status=in_progress", "--note=Started from the October export"],
                ["status", _TASK_ID, "failed", "--note=The export was empty"],
            ]
        ),
    )


def test_a_task_left_in_progress_is_marked_done_when_the_run_ends(tmp_path: Path):
    _drive(tmp_path, [_created(), _agent_end()])

    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "done"]]))


@pytest.mark.parametrize("status", ["failed", "open", "done"])
def test_a_status_the_agent_set_itself_is_kept(tmp_path: Path, status: str):
    _drive(tmp_path, [_created(), _task("c3", action="status", task_id=_TASK_ID, status=status), _agent_end()])

    assert_that(_statuses(tmp_path), equal_to([]))


def test_a_task_the_run_only_noted_on_is_not_closed(tmp_path: Path):
    _drive(tmp_path, [_task("c1", action="note", task_id=_TASK_ID, body="Waiting on Dana"), _agent_end()])

    assert_that(_statuses(tmp_path), equal_to([]))


def test_a_task_left_in_progress_is_reopened_when_the_run_failed(tmp_path: Path):
    wrote, states = _wrote(tmp_path)

    _drive(tmp_path, [wrote, _created(), _agent_end(success=False)])

    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "open"]]))
    assert_that(_attaches(tmp_path), equal_to([["attach", _TASK_ID, states, "--replace"]]))


def test_every_task_left_in_progress_is_closed(tmp_path: Path):
    _drive(tmp_path, [_created("c1", "task-1"), _created("c2", "task-2"), _agent_end()])

    assert_that(sorted(_statuses(tmp_path)), equal_to([["status", "task-1", "done"], ["status", "task-2", "done"]]))


def _kept(call_id: str = "c2", action: str = "create", keep=True) -> dict:
    details = {"id": _TASK_ID, "status": "in_progress"}
    target = {"title": "States"} if action == "create" else {"task_id": _TASK_ID}
    return _task(
        call_id,
        result={"content": [{"type": "text", "text": json.dumps(details)}], "details": details},
        action=action,
        status="in_progress",
        keep=keep,
        **target,
    )


@pytest.mark.parametrize("action", ["create", "status"])
def test_a_task_the_agent_keeps_stays_in_progress_when_the_run_ends(tmp_path: Path, action: str):
    _drive(tmp_path, [_kept(action=action), _agent_end()])

    assert_that(_statuses(tmp_path), equal_to([]))


def test_keep_given_as_text_is_honoured(tmp_path: Path):
    _drive(tmp_path, [_kept(keep="true"), _agent_end()])

    assert_that(_statuses(tmp_path), equal_to([]))


def test_a_task_reopened_without_keep_is_marked_done_when_the_run_ends(tmp_path: Path):
    _drive(tmp_path, [_task("c1", action="status", task_id=_TASK_ID, status="in_progress"), _agent_end()])

    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "done"]]))


def test_the_last_status_call_in_a_run_wins_over_keep(tmp_path: Path):
    _drive(
        tmp_path,
        [_kept(), _task("c3", action="status", task_id=_TASK_ID, status="in_progress"), _agent_end()],
    )

    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "done"]]))


def test_a_kept_task_is_reopened_when_the_run_failed(tmp_path: Path):
    _drive(tmp_path, [_kept(), _agent_end(success=False)])

    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "open"]]))


def test_keep_is_not_passed_to_the_task_command(tmp_path: Path):
    _drive(
        tmp_path,
        [
            _tool(action="create", title="Report", keep=True),
            _tool(action="status", task_id=_TASK_ID, status="in_progress", keep=True),
        ],
    )

    assert_that(
        [call["argv"] for call in _calls(tmp_path)],
        equal_to([["create", "--title=Report", "--status=in_progress"], ["status", _TASK_ID, "in_progress"]]),
    )


def test_the_tool_offers_keep(tmp_path: Path):
    [tool] = _drive(tmp_path, [])["tools"]

    assert_that(tool["parameters"]["properties"]["keep"]["type"], equal_to("boolean"))
    assert_that(tool["description"], contains_string("keep"))


def test_files_are_attached_before_the_task_is_closed(tmp_path: Path):
    wrote, states = _wrote(tmp_path)

    _drive(tmp_path, [wrote, _created(), _agent_end()])

    assert_that(
        [call["argv"] for call in _calls(tmp_path) if call["argv"][0] in {"attach", "status"}],
        equal_to([["attach", _TASK_ID, states, "--replace"], ["status", _TASK_ID, "done"]]),
    )


def test_closing_a_task_refreshes_the_open_tasks_shown(tmp_path: Path):
    _drive(
        tmp_path,
        [_prompt(), _created(), _agent_end(), _prompt()],
        open_tasks=[{"id": _TASK_ID, "status": "in_progress", "title": "States"}],
    )

    assert_that(sum(call["argv"][0] == "list" for call in _calls(tmp_path)), equal_to(2))


@pytest.mark.parametrize("message", ["Thanks!", "Thanks, that's great.", "That's all for now, thanks!", "Good morning"])
def test_small_talk_does_not_carry_the_task_line(tmp_path: Path, message: str):
    driven = _drive(tmp_path, [_prompt(prompt=message)])

    assert_that("agentbarn_task before you start" in _context(driven["results"][0]), is_(False))


@pytest.mark.parametrize(
    "message",
    ["Ok", "Yes please", "Please summarise the October invoices", "Thanks, now rename states.csv"],
)
def test_requests_and_approvals_carry_the_task_line(tmp_path: Path, message: str):
    driven = _drive(tmp_path, [_prompt(prompt=message)])

    assert_that(_context(driven["results"][0]), contains_string("agentbarn_task before you start"))


# --- files and Tasks across runs ---


def test_only_the_three_latest_done_tasks_are_shown(tmp_path: Path):
    done = [{"id": f"task-{n}", "title": f"Job {n}", "status": "done"} for n in range(1, 6)]

    context = _context(_drive(tmp_path, [_prompt()], open_tasks=done)["results"][0])

    assert_that([f"task-{n} [done]" in context for n in range(1, 6)], equal_to([True, True, True, False, False]))


def _created_in(run_id: str, task_id: str) -> dict:
    details = {"id": task_id, "status": "in_progress"}
    step = _after_tool(
        "c9",
        run_id=run_id,
        tool="agentbarn_task",
        params={"action": "create", "title": "States"},
        result={"content": [{"type": "text", "text": json.dumps(details)}], "details": details},
    )
    return step


# --- work the Agent left unrecorded ---


def _creates(tmp_path: Path) -> list[list[str]]:
    return [call["argv"] for call in _calls(tmp_path) if call["argv"][0] == "create"]


def _option(argv: list[str], name: str) -> str:
    return next(arg.split("=", 1)[1] for arg in argv if arg.startswith(f"--{name}="))


def test_work_left_unrecorded_is_recorded_automatically_when_the_run_ends(tmp_path: Path):
    _drive(
        tmp_path,
        [
            _prompt(prompt="Please summarise the October invoices"),
            *[_after_tool(f"c{n}") for n in range(1, 4)],
            _agent_end(),
        ],
    )

    assert_that(
        _creates(tmp_path),
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


def test_the_automatic_task_gets_the_files_the_run_wrote(tmp_path: Path):
    wrote, states = _wrote(tmp_path)

    _drive(tmp_path, [_prompt(prompt="Write the states CSV"), wrote, _agent_end()])

    assert_that(_attaches(tmp_path), equal_to([["attach", _TASK_ID, states, "--replace"]]))


def test_a_long_request_is_shortened_for_the_automatic_title(tmp_path: Path):
    wrote, _ = _wrote(tmp_path)

    _drive(tmp_path, [_prompt(prompt="Please " + "compare these regional sales figures " * 10), wrote, _agent_end()])

    title = _option(_creates(tmp_path)[0], "title")
    assert_that((len(title), title.endswith("…")), equal_to((120, True)))


@pytest.mark.parametrize("success", [True, False])
def test_nothing_is_recorded_automatically_for_a_short_or_failed_run(tmp_path: Path, success: bool):
    wrote, _ = _wrote(tmp_path)
    steps = [_prompt(), _after_tool("c9")] + ([] if success else [wrote])

    _drive(tmp_path, [*steps, _agent_end(success=success)])

    assert_that(_creates(tmp_path), equal_to([]))


def test_a_run_the_agent_recorded_is_not_recorded_again(tmp_path: Path):
    wrote, _ = _wrote(tmp_path)

    _drive(tmp_path, [_prompt(), wrote, _created(), _agent_end()])

    assert_that(_creates(tmp_path), equal_to([]))


def test_the_next_turn_carries_no_catch_up_reminder(tmp_path: Path):
    wrote, _ = _wrote(tmp_path)

    driven = _drive(tmp_path, [_prompt(), wrote, _agent_end(), _prompt()])

    assert_that("did work without recording" in _context(driven["results"][-1]), is_(False))


def test_heartbeat_work_is_not_recorded_automatically(tmp_path: Path):
    _drive(
        tmp_path,
        [*[_after_tool(f"c{n}", trigger="heartbeat") for n in range(1, 4)], _agent_end(trigger="heartbeat")],
    )

    assert_that(_creates(tmp_path), equal_to([]))


# --- only a Task the run actually wrote counts as recording it ---


def test_reading_tasks_does_not_count_as_recording(tmp_path: Path):
    listed = {"items": []}
    driven = _drive(
        tmp_path,
        [
            _prompt(),
            _task(
                "c0",
                result={"content": [{"type": "text", "text": json.dumps(listed)}], "details": listed},
                action="list",
            ),
            *[_after_tool(f"c{n}") for n in range(1, 4)],
            _finalize(),
            _agent_end(),
        ],
    )

    assert_that(driven["results"][-2], has_entries(action="revise"))
    assert_that(len(_creates(tmp_path)), equal_to(1))


def test_a_task_call_that_failed_does_not_count_as_recording(tmp_path: Path):
    wrote, states = _wrote(tmp_path)
    refused = {"error": "Task not found."}

    _drive(
        tmp_path,
        [
            _prompt(prompt="Write the states CSV"),
            wrote,
            _task(
                "c2",
                result={"content": [{"type": "text", "text": json.dumps(refused)}], "details": refused},
                action="status",
                task_id="task-gone",
                status="in_progress",
            ),
            _agent_end(),
        ],
    )

    assert_that(len(_creates(tmp_path)), equal_to(1))
    assert_that(_attaches(tmp_path), equal_to([["attach", _TASK_ID, states, "--replace"]]))
    assert_that([argv for argv in _statuses(tmp_path) if "task-gone" in argv], equal_to([]))


@pytest.mark.parametrize("command", ["agentbarn-task --help", "agentbarn-task list", "agentbarn-task show abc"])
def test_reading_tasks_from_exec_does_not_count_as_recording(tmp_path: Path, command: str):
    driven = _drive(
        tmp_path, [_after_tool("c0", command=command), *[_after_tool(f"c{n}") for n in range(1, 4)], _finalize()]
    )

    assert_that(driven["results"][-1], has_entries(action="revise"))


# --- listing Tasks each turn stays cheap and bounded ---


def test_open_and_finished_tasks_come_from_one_list_call(tmp_path: Path):
    _drive(tmp_path, [_prompt()])

    assert_that([call["argv"] for call in _calls(tmp_path)], equal_to([["list", "--page-size=100"]]))


def test_a_failed_listing_is_not_retried_on_every_turn(tmp_path: Path):
    _drive(tmp_path, [_prompt(), _prompt()], FAKE_TASK_LIST_FAIL="1")

    assert_that(len(_calls(tmp_path)), equal_to(1))


def test_a_slow_listing_does_not_hold_up_the_turn(tmp_path: Path):
    started = time.monotonic()
    driven = _drive(
        tmp_path,
        [_prompt()],
        open_tasks=[{"id": "task-1", "title": "Report", "status": "open"}],
        FAKE_TASK_LIST_SLEEP="60",
    )

    assert_that((time.monotonic() - started < 25, "task-1" in _context(driven["results"][0])), equal_to((True, False)))


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
    wrote, _ = _wrote(tmp_path)

    _drive(tmp_path, [_prompt(prompt=request_text), wrote, _agent_end()])

    [create] = _creates(tmp_path)
    title, description = _option(create, "title"), _option(create, "description")
    assert_that((secret in title, secret in description), equal_to((False, False)))
    assert_that(description, contains_string("[redacted]"))


def test_a_request_that_looks_like_an_option_is_still_recorded(tmp_path: Path):
    wrote, _ = _wrote(tmp_path)

    _drive(tmp_path, [_prompt(prompt="-v"), wrote, _agent_end()])

    assert_that(_option(_creates(tmp_path)[0], "title"), equal_to("-v"))


# --- the startup checklist and subagent runs are not the user's request ---


@pytest.mark.parametrize("session", ["agent:main:boot", "agent:main:subagent:4f2a", "subagent:4f2a"])
def test_boot_and_subagent_runs_are_left_alone(tmp_path: Path, session: str):
    wrote, _ = _wrote(tmp_path)
    work = [_after_tool(f"c{n}", session=session) for n in range(2, 5)]

    driven = _drive(
        tmp_path,
        [
            _prompt(session=session),
            {**wrote, "ctx": {**wrote["ctx"], "sessionKey": session}},
            *work,
            _persist("c4", session=session),
            _finalize(session=session),
            _agent_end(session=session),
        ],
    )

    assert_that(driven["results"][0], is_(None))
    assert_that(driven["results"][-3:], equal_to([None, None, None]))
    assert_that(_calls(tmp_path), equal_to([]))


# --- what the plugin remembers stays bounded ---


def test_only_the_latest_sessions_requests_are_kept(tmp_path: Path):
    wrote, _ = _wrote(tmp_path)
    later = [_prompt(session=f"later-{n}", prompt="Hello there, do something") for n in range(_SESSIONS_KEPT)]

    _drive(tmp_path, [_prompt(session="s1", prompt="Write the states CSV"), *later, wrote, _agent_end()])

    assert_that(_option(_creates(tmp_path)[0], "title"), equal_to("Work recorded automatically"))


# --- each agent in a pod with Bots ---


def _bot_pod(tmp_path: Path, **secret: str) -> str:
    directory = tmp_path / "bots" / _BOT_ID
    directory.mkdir(parents=True)
    for name, value in {**_BOT_IDENTITY, **secret}.items():
        (directory / name).write_text(value)
    (tmp_path / ".openclaw" / f"workspace-{_BOT_ID}").mkdir(parents=True)
    return str(tmp_path / "bots")


def _as(step: dict, agent: str | None = _BOT_ID) -> dict:
    ctx = step.get("ctx", {})
    session = f"agent:{agent or _BOT_ID}:{ctx.get('sessionKey', 's1')}"
    return {**step, "ctx": {**ctx, "sessionKey": session, **({"agentId": agent} if agent else {})}}


def _env_of(tmp_path: Path, command: str) -> list[dict]:
    return [call["env"] for call in _calls(tmp_path) if call["argv"][0] == command]


def test_a_bots_task_tool_runs_the_command_as_that_bot_in_its_own_workspace(tmp_path: Path):
    pod = _bot_pod(tmp_path)

    _drive(tmp_path, [_as(_tool(action="create", title="Report"))], BOT_SECRET_ROOT=pod)

    call = _calls(tmp_path)[-1]
    assert_that(call["env"], equal_to(_BOT_IDENTITY))
    workspace = tmp_path / ".openclaw" / f"workspace-{_BOT_ID}"
    assert_that(os.path.realpath(call["cwd"]), equal_to(os.path.realpath(workspace)))


@pytest.mark.parametrize("agent", [_BOT_ID, None])
def test_a_bots_unrecorded_work_is_recorded_as_that_bot(tmp_path: Path, agent: str | None):
    pod = _bot_pod(tmp_path)
    work = [_as(_after_tool(f"c{n}"), agent) for n in range(3)]

    _drive(tmp_path, [*work, _as(_agent_end(), agent)], BOT_SECRET_ROOT=pod)

    assert_that(_env_of(tmp_path, "create"), equal_to([_BOT_IDENTITY]))


def test_a_bots_files_are_found_in_its_own_workspace(tmp_path: Path):
    pod = _bot_pod(tmp_path)
    states = tmp_path / ".openclaw" / f"workspace-{_BOT_ID}" / "states.csv"
    states.write_text("a,b\n")
    wrote = _after_tool("c1", tool="write", params={"path": "states.csv"})

    _drive(tmp_path, [_as(wrote), _as(_created()), _as(_agent_end())], BOT_SECRET_ROOT=pod)

    assert_that(_attaches(tmp_path), equal_to([["attach", _TASK_ID, str(states), "--replace"]]))
    assert_that(_env_of(tmp_path, "attach"), equal_to([_BOT_IDENTITY]))


def test_a_bots_file_over_its_own_limit_is_named_on_the_next_turn(tmp_path: Path):
    pod = _bot_pod(tmp_path, ARTIFACT_MAX_BYTES="1")
    (tmp_path / ".openclaw" / f"workspace-{_BOT_ID}" / "states.csv").write_text("a,b\n")
    wrote = _after_tool("c1", tool="write", params={"path": "states.csv"})

    driven = _drive(tmp_path, [_as(wrote), _as(_created()), _as(_agent_end()), _as(_prompt())], BOT_SECRET_ROOT=pod)

    assert_that((_attaches(tmp_path), "states.csv" in _context(driven["results"][-1])), equal_to(([], True)))


@pytest.mark.parametrize(
    "secret", [None, {"AGENT_ID": _PARENT_ID}, {"INGEST_API_KEY": ""}], ids=["missing", "another_agent", "no_key"]
)
def test_a_bot_without_its_own_secret_records_nothing_and_never_as_the_parent(tmp_path: Path, secret: dict | None):
    pod = _bot_pod(tmp_path, **secret) if secret is not None else str(tmp_path / "bots")
    work = [_as(_after_tool(f"c{n}")) for n in range(3)]

    driven = _drive(
        tmp_path,
        [_as(_tool(action="create", title="Report")), *work, _as(_agent_end()), _as(_prompt())],
        BOT_SECRET_ROOT=pod,
    )

    assert_that(_calls(tmp_path), equal_to([]))
    assert_that(_tool_output(driven["results"][0])["error"], contains_string("unavailable"))
    assert_that(_context(driven["results"][-1]), is_not(contains_string("Your open and latest finished Tasks")))


def test_each_agent_is_shown_its_own_open_tasks(tmp_path: Path):
    pod = _bot_pod(tmp_path)

    _drive(
        tmp_path,
        [_prompt(), _as(_prompt()), _prompt(), _as(_prompt())],
        open_tasks=[{"id": "task-1", "title": "Report", "status": "open"}],
        BOT_SECRET_ROOT=pod,
    )

    assert_that([env["AGENT_ID"] for env in _env_of(tmp_path, "list")], equal_to([_PARENT_ID, _BOT_ID]))


def test_the_parent_in_a_pod_with_bots_keeps_its_own_identity_and_workspace(tmp_path: Path):
    pod = _bot_pod(tmp_path)

    _drive(tmp_path, [_as(_tool(action="create", title="Report"), "main")], BOT_SECRET_ROOT=pod)

    call = _calls(tmp_path)[-1]
    assert_that(call["env"], has_entries(AGENT_ID=_PARENT_ID, INGEST_API_KEY="test-key-123"))
    workspace = tmp_path / ".openclaw" / "workspace"
    assert_that(os.path.realpath(call["cwd"]), equal_to(os.path.realpath(workspace)))


# --- schedules: a Task follows the schedule it was created for ---

_JOB_ID = "a829ba55-d319-4b26-962a-7eee853a53f0"
_GREETING = "Post a greeting every minute, 7 times. It is done after 7 greetings."
_CRON_SESSION = f"agent:main:cron:{_JOB_ID}:run:r1"


def _links(tmp_path: Path) -> dict:
    path = tmp_path / ".openclaw" / "agentbarn-task-schedules.json"
    return json.loads(path.read_text()) if path.exists() else {}


def _linked(tmp_path: Path, runs: int = 0) -> None:
    (tmp_path / ".openclaw").mkdir(parents=True, exist_ok=True)
    link = {"task_id": _TASK_ID, **({"runs": runs} if runs else {})}
    (tmp_path / ".openclaw" / "agentbarn-task-schedules.json").write_text(json.dumps({_JOB_ID: link}))


def _schedule_added(tool: str = "automations", kind: str = "every") -> dict:
    schedule = {"kind": "every", "everyMs": 60000} if kind == "every" else {"kind": "at", "at": "2026-11-18T09:00:00Z"}
    job = {"name": "greeting-7x", "schedule": schedule, "payload": {"kind": "agentTurn", "message": "Post a greeting"}}
    return _after_tool(
        "call-s", tool=tool, params={"action": "add", "job": job}, result={"details": {"id": _JOB_ID, **job}}
    )


def _task_recorded(status: str = "done", keep: bool = False) -> dict:
    params = {"action": "create", "title": "Greetings for a week", "status": status, **({"keep": True} if keep else {})}
    return _after_tool("call-t", tool="agentbarn_task", params=params, result={"details": {"id": _TASK_ID}})


def _statuses(tmp_path: Path) -> list[list[str]]:
    return [call["argv"] for call in _calls(tmp_path) if call["argv"][0] == "status"]


def _argvs(tmp_path: Path, command: str) -> list[list[str]]:
    return [call["argv"] for call in _calls(tmp_path) if call["argv"][0] == command]


def _cron_prompt(run_id: str = "cron-1") -> dict:
    return {
        "hook": "before_prompt_build",
        "event": {"prompt": f"[cron:{_JOB_ID} greeting-7x] Post a greeting", "messages": []},
        "ctx": {"sessionKey": _CRON_SESSION, "trigger": "cron", "runId": run_id, "jobId": _JOB_ID},
    }


def _cron_end(run_id: str = "cron-1", reply: str = "Good morning, team!") -> dict:
    return {
        "hook": "agent_end",
        "event": {"runId": run_id, "success": True, "messages": [{"role": "assistant", "content": reply}]},
        "ctx": {"sessionKey": _CRON_SESSION, "runId": run_id, "trigger": "cron", "jobId": _JOB_ID},
    }


def _cron_tool(call_id: str, run_id: str = "cron-1", **kwargs) -> dict:
    return _after_tool(call_id, run_id=run_id, session=_CRON_SESSION, trigger="cron", **kwargs)


@pytest.mark.parametrize("tool", ["automations", "cron"])
def test_a_task_whose_job_is_the_runs_stays_in_progress_and_follows_the_schedule(tmp_path: Path, tool: str):
    _drive(
        tmp_path,
        [_prompt(prompt=_GREETING), _schedule_added(tool), _task_recorded("done"), _agent_end()],
        FAKE_SCHEDULE_INTENT="runs",
    )

    asked = json.loads(next(call["stdin"] for call in _calls(tmp_path) if call["argv"][0] == "schedule-intent"))
    assert_that(
        asked,
        has_entries(
            request=_GREETING,
            schedule=has_entries(recurrence="every 60s", run_limit=None),
            task=has_entries(title="Greetings for a week", status="done"),
        ),
    )
    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "in_progress"]]))
    assert_that(_links(tmp_path), equal_to({_JOB_ID: {"task_id": _TASK_ID, "agent": "main"}}))


def test_a_task_whose_job_was_setting_up_the_schedule_is_done_even_if_the_agent_kept_it(tmp_path: Path):
    steps = [_prompt(prompt="Remind me every morning"), _schedule_added(), _task_recorded("in_progress", keep=True)]
    _drive(tmp_path, [*steps, _agent_end()], FAKE_SCHEDULE_INTENT="setup")

    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "done"]]))
    assert_that(_links(tmp_path), equal_to({}))


@pytest.mark.parametrize(
    ("keep", "linked", "statuses"), [(True, True, []), (False, False, [["status", _TASK_ID, "done"]])]
)
def test_without_a_decision_the_agents_own_choice_stands(tmp_path: Path, keep: bool, linked: bool, statuses: list):
    _drive(tmp_path, [_prompt(prompt=_GREETING), _schedule_added(), _task_recorded("in_progress", keep), _agent_end()])

    assert_that(_statuses(tmp_path), equal_to(statuses))
    assert_that(bool(_links(tmp_path)), equal_to(linked))


def test_a_schedule_whose_runs_are_the_job_gets_a_task_when_the_agent_recorded_none(tmp_path: Path):
    _drive(tmp_path, [_prompt(prompt=_GREETING), _schedule_added(), _agent_end()], FAKE_SCHEDULE_INTENT="runs")

    [created] = _argvs(tmp_path, "create")
    assert_that("--status=in_progress" in created and "--origin=automatic" in created, equal_to(True))
    assert_that(_links(tmp_path), equal_to({_JOB_ID: {"task_id": _TASK_ID, "agent": "main"}}))


def test_a_one_off_schedule_is_asked_about_with_a_limit_of_one_run(tmp_path: Path):
    _drive(
        tmp_path, [_prompt(), _schedule_added(kind="at"), _task_recorded(), _agent_end()], FAKE_SCHEDULE_INTENT="setup"
    )

    asked = json.loads(next(call["stdin"] for call in _calls(tmp_path) if call["argv"][0] == "schedule-intent"))
    assert_that(asked["schedule"], has_entries(run_limit=1))


def test_each_scheduled_run_is_noted_on_its_task_without_the_agent_doing_anything(tmp_path: Path):
    _linked(tmp_path, runs=2)
    work = [_cron_tool(f"work-{index}") for index in range(4)]

    _drive(tmp_path, [_cron_prompt(), *work, _cron_end()])

    notes = [call for call in _calls(tmp_path) if call["argv"][:2] == ["note", _TASK_ID]]
    assert_that([note["stdin"] for note in notes], equal_to(["Run 3: Good morning, team!"]))
    assert_that(_statuses(tmp_path), equal_to([]))
    assert_that(_argvs(tmp_path, "create"), equal_to([]))
    assert_that(_links(tmp_path), equal_to({_JOB_ID: {"task_id": _TASK_ID, "runs": 3}}))


def test_a_run_that_removes_its_own_schedule_finishes_the_task(tmp_path: Path):
    _linked(tmp_path, runs=6)
    removal = _cron_tool("call-r", tool="automations", params={"action": "remove", "jobId": _JOB_ID}, result={})
    changed = {"hook": "cron_changed", "event": {"action": "removed", "jobId": _JOB_ID}, "ctx": {}}

    _drive(tmp_path, [_cron_prompt(), removal, changed, _cron_end()])

    assert_that(_argvs(tmp_path, "note"), equal_to([["note", _TASK_ID]]))
    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "done"]]))
    assert_that(_argvs(tmp_path, "create"), equal_to([]))
    assert_that(_links(tmp_path), equal_to({}))


def test_a_schedule_removed_outside_a_run_finishes_its_task(tmp_path: Path):
    _linked(tmp_path)

    _drive(tmp_path, [{"hook": "cron_changed", "event": {"action": "removed", "jobId": _JOB_ID}, "ctx": {}}])

    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "done"]]))
    assert_that(_links(tmp_path), equal_to({}))


def test_a_one_off_schedule_finishes_its_task_when_it_has_run(tmp_path: Path):
    _linked(tmp_path)
    finished = {
        "hook": "cron_changed",
        "event": {"action": "finished", "jobId": _JOB_ID, "job": {"schedule": {"kind": "at"}}},
        "ctx": {},
    }

    _drive(tmp_path, [finished])

    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "done"]]))


def test_a_recurring_schedule_finishing_one_run_leaves_its_task_in_progress(tmp_path: Path):
    _linked(tmp_path)
    finished = {
        "hook": "cron_changed",
        "event": {"action": "finished", "jobId": _JOB_ID, "job": {"schedule": {"kind": "every"}}},
        "ctx": {},
    }

    _drive(tmp_path, [finished])

    assert_that(_statuses(tmp_path), equal_to([]))
    assert_that(bool(_links(tmp_path)), equal_to(True))


def test_a_task_the_agent_closed_during_an_earlier_run_is_put_back_in_progress(tmp_path: Path):
    _linked(tmp_path)
    closed = _cron_tool(
        "call-1", tool="agentbarn_task", params={"action": "status", "task_id": _TASK_ID, "status": "done"}, result={}
    )

    _drive(tmp_path, [_cron_prompt(), closed, _cron_end()])

    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "in_progress"]]))


def test_a_run_of_a_schedule_with_no_task_is_handled_as_before(tmp_path: Path):
    work = [_cron_tool(f"work-{index}") for index in range(3)]

    _drive(tmp_path, [_cron_prompt(), *work, _cron_end()])

    assert_that(_argvs(tmp_path, "note"), equal_to([]))
    assert_that(len(_argvs(tmp_path, "create")), equal_to(1))


def test_removing_the_schedule_in_a_conversation_finishes_its_task(tmp_path: Path):
    _linked(tmp_path)
    removal = _after_tool("call-r", tool="automations", params={"action": "remove", "jobId": _JOB_ID}, result={})

    _drive(tmp_path, [_prompt(prompt="Stop the greetings"), removal, _agent_end()])

    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "done"]]))
    assert_that(_links(tmp_path), equal_to({}))


def test_a_scheduled_run_is_recognised_from_its_prompt_when_the_runtime_names_no_job(tmp_path: Path):
    _linked(tmp_path)
    session = "agent:main:connection:abc:thread-1"
    prompt = {
        "hook": "before_prompt_build",
        "event": {"prompt": f"[cron:{_JOB_ID} greeting-7x] Post a greeting", "messages": []},
        "ctx": {"sessionKey": session, "trigger": "cron"},
    }
    end = {
        "hook": "agent_end",
        "event": {"runId": "cron-9", "success": True, "messages": [{"role": "assistant", "content": "Hello!"}]},
        "ctx": {"sessionKey": session, "runId": "cron-9", "trigger": "cron"},
    }

    _drive(tmp_path, [prompt, end])

    assert_that([call["stdin"] for call in _calls(tmp_path) if call["argv"][0] == "note"], equal_to(["Run 1: Hello!"]))


def test_a_conversation_turn_that_quotes_a_schedule_prefix_is_not_a_scheduled_run(tmp_path: Path):
    _linked(tmp_path)

    _drive(tmp_path, [_prompt(prompt=f"[cron:{_JOB_ID} greeting-7x] what does this mean?"), _agent_end()])

    assert_that(_argvs(tmp_path, "note"), equal_to([]))


# --- a Task about to be marked done can be held back ---


def _ended(reply: str = "I asked the channel.", run_id: str = "run-1", session: str = "s1", **ctx) -> dict:
    return {
        "hook": "agent_end",
        "event": {"runId": run_id, "success": True, "messages": [{"role": "assistant", "content": reply}]},
        "ctx": {"sessionKey": session, "runId": run_id, "trigger": "user", **ctx},
    }


def _asked(tmp_path: Path) -> list[dict]:
    return [json.loads(call["stdin"]) for call in _calls(tmp_path) if call["argv"] == ["turn-end"]]


def _left_in_progress(call_id: str = "c2", **kwargs) -> dict:
    return _after_tool(
        call_id,
        tool="agentbarn_task",
        params={"action": "create", "title": "Ask QA", "status": "in_progress"},
        result={"details": {"id": _TASK_ID, "status": "in_progress"}},
        **kwargs,
    )


def test_agent_barn_is_asked_about_a_task_before_it_is_marked_done(tmp_path: Path):
    steps = [
        _prompt(prompt="Ask the QA channel for the priority"),
        _after_tool("c1", command="post question"),
        _left_in_progress(),
        _ended(),
    ]

    _drive(tmp_path, steps)

    [asked] = _asked(tmp_path)
    assert_that(
        asked,
        has_entries(
            request="Ask the QA channel for the priority",
            reply="I asked the channel.",
            closing=[_TASK_ID],
            trigger="user",
        ),
    )
    assert_that(asked["tools"][0], contains_string("exec"))
    assert_that(asked["tools"][0], contains_string("post question"))
    assert_that(len(asked["tools"]), equal_to(2))
    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "done"]]))


def test_a_task_whose_job_is_still_going_is_not_marked_done(tmp_path: Path):
    _drive(tmp_path, [_left_in_progress(), _ended()], FAKE_TURN_END="in_progress")

    assert_that(_statuses(tmp_path), equal_to([]))


def test_a_task_waiting_on_the_user_is_left_open(tmp_path: Path):
    _drive(tmp_path, [_left_in_progress(), _ended()], FAKE_TURN_END="open")

    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "open"]]))


def test_a_task_the_agent_kept_is_not_asked_about(tmp_path: Path):
    _drive(tmp_path, [_kept(), _ended()], FAKE_TURN_END="open")

    assert_that(_asked(tmp_path), equal_to([]))
    assert_that(_statuses(tmp_path), equal_to([]))


@pytest.mark.parametrize("status", ["done", "open", "failed"])
def test_a_status_the_agent_set_itself_is_not_asked_about(tmp_path: Path, status: str):
    set_by_agent = _task("c1", result={"details": {"id": _TASK_ID}}, action="status", task_id=_TASK_ID, status=status)

    _drive(tmp_path, [set_by_agent, _ended()], FAKE_TURN_END="in_progress")

    assert_that(_asked(tmp_path), equal_to([]))
    assert_that(_statuses(tmp_path), equal_to([]))


def test_a_run_that_failed_reopens_its_task_without_asking(tmp_path: Path):
    _drive(tmp_path, [_left_in_progress(), _agent_end(success=False)], FAKE_TURN_END="in_progress")

    assert_that(_asked(tmp_path), equal_to([]))
    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "open"]]))


def test_a_run_that_touched_no_task_asks_nothing(tmp_path: Path):
    _drive(tmp_path, [_after_tool("c1"), _ended()], FAKE_TURN_END="in_progress")

    assert_that(_asked(tmp_path), equal_to([]))


def test_secrets_are_not_sent_with_the_question(tmp_path: Path):
    secret = "sk-" + "a1B2c3D4" * 5
    steps = [
        _prompt(prompt=f"Use the key {secret} to call the API"),
        _after_tool("c1", command=f"curl -H 'Authorization: Bearer {secret}' https://example.com"),
        _left_in_progress(),
        _ended(f"I used {secret}."),
    ]

    _drive(tmp_path, steps)

    assert_that(len(_asked(tmp_path)), equal_to(1))
    assert_that(secret in json.dumps(_asked(tmp_path)), equal_to(False))


def test_a_task_finished_by_setting_up_its_schedule_is_marked_done_without_asking(tmp_path: Path):
    steps = [
        _prompt(prompt="Remind me to stretch every morning"),
        _schedule_added(),
        _task_recorded("in_progress", keep=True),
        _ended(),
    ]

    _drive(tmp_path, steps, FAKE_TURN_END="in_progress", FAKE_SCHEDULE_INTENT="setup")

    assert_that(_asked(tmp_path), equal_to([]))
    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "done"]]))


def test_a_task_following_a_schedule_is_not_asked_about(tmp_path: Path):
    steps = [_prompt(prompt=_GREETING), _schedule_added(), _task_recorded("in_progress"), _ended()]

    _drive(tmp_path, steps, FAKE_TURN_END="open", FAKE_SCHEDULE_INTENT="runs")

    assert_that(_asked(tmp_path), equal_to([]))
    assert_that(_statuses(tmp_path), equal_to([]))


def test_a_scheduled_run_with_no_linked_task_is_asked_about_as_a_scheduled_run(tmp_path: Path):
    steps = [_cron_prompt(), _left_in_progress(run_id="cron-1", session=_CRON_SESSION, trigger="cron"), _cron_end()]

    _drive(tmp_path, steps)

    assert_that(_asked(tmp_path)[0]["trigger"], equal_to("cron"))


# --- a Bot's schedules and turn-end questions ---

_BOT_CRON_SESSION = f"agent:{_BOT_ID}:cron:{_JOB_ID}:run:r1"


def _bot_cron(step: dict) -> dict:
    return {**step, "ctx": {**step["ctx"], "sessionKey": _BOT_CRON_SESSION, "agentId": _BOT_ID}}


def _bot_linked(tmp_path: Path) -> None:
    (tmp_path / ".openclaw").mkdir(parents=True, exist_ok=True)
    link = {"task_id": _TASK_ID, "agent": _BOT_ID}
    (tmp_path / ".openclaw" / "agentbarn-task-schedules.json").write_text(json.dumps({_JOB_ID: link}))


def _removed() -> dict:
    return {"hook": "cron_changed", "event": {"action": "removed", "jobId": _JOB_ID, "agentId": _BOT_ID}, "ctx": {}}


def test_a_bots_schedule_is_linked_to_its_task_as_that_bot(tmp_path: Path):
    pod = _bot_pod(tmp_path)
    steps = [_prompt(prompt=_GREETING), _schedule_added(), _task_recorded("done"), _agent_end()]

    _drive(tmp_path, [_as(step) for step in steps], FAKE_SCHEDULE_INTENT="runs", BOT_SECRET_ROOT=pod)

    assert_that(_links(tmp_path), equal_to({_JOB_ID: {"task_id": _TASK_ID, "agent": _BOT_ID}}))
    assert_that(_env_of(tmp_path, "schedule-intent"), equal_to([_BOT_IDENTITY]))
    assert_that(_env_of(tmp_path, "status"), equal_to([_BOT_IDENTITY]))


def test_a_bots_scheduled_run_is_noted_on_its_task_as_that_bot(tmp_path: Path):
    pod = _bot_pod(tmp_path)
    _bot_linked(tmp_path)

    _drive(tmp_path, [_bot_cron(_cron_prompt()), _bot_cron(_cron_end())], BOT_SECRET_ROOT=pod)

    assert_that(_env_of(tmp_path, "note"), equal_to([_BOT_IDENTITY]))


def test_a_bots_schedule_removed_outside_a_run_finishes_its_task_as_that_bot(tmp_path: Path):
    pod = _bot_pod(tmp_path)
    _bot_linked(tmp_path)

    _drive(tmp_path, [_removed()], BOT_SECRET_ROOT=pod)

    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "done"]]))
    assert_that(_env_of(tmp_path, "status"), equal_to([_BOT_IDENTITY]))


def test_a_bots_task_is_asked_about_as_that_bot_before_it_is_marked_done(tmp_path: Path):
    pod = _bot_pod(tmp_path)

    _drive(tmp_path, [_as(_left_in_progress()), _as(_ended())], BOT_SECRET_ROOT=pod)

    assert_that(_env_of(tmp_path, "turn-end"), equal_to([_BOT_IDENTITY]))
    assert_that(_statuses(tmp_path), equal_to([["status", _TASK_ID, "done"]]))
    assert_that(_env_of(tmp_path, "status"), equal_to([_BOT_IDENTITY]))


def test_a_schedule_linked_without_an_agent_finishes_its_task_as_the_parent(tmp_path: Path):
    pod = _bot_pod(tmp_path)
    _linked(tmp_path)

    _drive(tmp_path, [_removed()], BOT_SECRET_ROOT=pod)

    assert_that([env["AGENT_ID"] for env in _env_of(tmp_path, "status")], equal_to([_PARENT_ID]))

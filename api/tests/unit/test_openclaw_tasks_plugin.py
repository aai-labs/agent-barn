"""The OpenClaw agentbarn-tasks plugin: a typed Task tool, open Tasks each turn, and reminders."""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_entries, is_

_PLUGIN_DIR = Path(__file__).parents[2] / "domains/agents/scripts/openclaw/plugins/agentbarn-tasks"
_DRIVER = Path(__file__).parents[1] / "fixtures/agent_tasks/openclaw_tasks_plugin_driver.mjs"
_FAKE_COMMAND = Path(__file__).parents[1] / "fixtures/agent_tasks/fake_task_command.py"
_TASK_ID = "0199f1d2-0000-7000-8000-0000000000aa"
_SESSIONS_KEPT = 500


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
            "AGENT_ID": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
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
) -> dict:
    return {
        "hook": "after_tool_call",
        "event": {
            "toolName": tool,
            "params": params if params is not None else {"command": command},
            "runId": run_id,
            "toolCallId": call_id,
            **({"result": result} if result is not None else {}),
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
            ["after_tool_call", "agent_end", "before_agent_finalize", "before_prompt_build", "tool_result_persist"]
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

"""The OpenClaw agentbarn-tasks plugin: a typed Task tool, open Tasks each turn, and reminders."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_string, equal_to, has_entries, is_

_PLUGIN_DIR = Path(__file__).parents[2] / "domains/agents/scripts/openclaw/plugins/agentbarn-tasks"
_DRIVER = Path(__file__).parents[1] / "fixtures/agent_tasks/openclaw_tasks_plugin_driver.mjs"
_FAKE_COMMAND = Path(__file__).parents[1] / "fixtures/agent_tasks/fake_task_command.py"
_TASK_ID = "0199f1d2-0000-7000-8000-0000000000aa"


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
) -> dict:
    return {
        "hook": "after_tool_call",
        "event": {"toolName": tool, "params": {"command": command}, "runId": run_id, "toolCallId": call_id},
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


def _prompt(session: str = "s1", trigger: str = "user") -> dict:
    return {
        "hook": "before_prompt_build",
        "event": {"prompt": "hi", "messages": []},
        "ctx": {"sessionKey": session, "trigger": trigger},
    }


def _context(result) -> str:
    return (result or {}).get("appendContext", "")


# --- registration ---


def test_the_task_tool_and_turn_hooks_are_registered(tmp_path: Path):
    driven = _drive(tmp_path, [])

    assert_that(
        driven["hooks"], equal_to(["after_tool_call", "agent_end", "before_agent_finalize", "before_prompt_build"])
    )
    [tool] = driven["tools"]
    assert_that(tool["name"], equal_to("agentbarn_task"))
    assert_that(
        sorted(tool["parameters"]["properties"]["action"]["enum"]),
        equal_to(["attach", "create", "list", "note", "show", "status"]),
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
            ["create", "--title", "Reconcile invoices", "--description", "For October"],
            "",
        ),
        ({"action": "status", "task_id": _TASK_ID, "status": "done"}, ["status", _TASK_ID, "done"], ""),
        ({"action": "note", "task_id": _TASK_ID, "body": "Matched 40 of 42"}, ["note", _TASK_ID], "Matched 40 of 42"),
        ({"action": "list", "status": "open"}, ["list", "--status", "open"], ""),
        ({"action": "show", "task_id": _TASK_ID}, ["show", _TASK_ID], ""),
        (
            {"action": "attach", "task_id": _TASK_ID, "path": "report.csv", "name": "October.csv"},
            ["attach", _TASK_ID, "report.csv", "--name", "October.csv"],
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
            _after_tool("c0", tool="agentbarn_task"),
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

    assert_that((driven["results"][2], _context(driven["results"][4])), equal_to((None, "")))


def test_heartbeat_runs_are_not_reminded(tmp_path: Path):
    steps = [_after_tool(f"c{n}", trigger="heartbeat") for n in range(1, 4)]
    driven = _drive(tmp_path, [*steps, _agent_end(trigger="heartbeat"), _prompt()])

    assert_that(_context(driven["results"][-1]), equal_to(""))


def test_a_run_that_ends_without_a_task_is_reminded_on_the_next_turn_of_that_session(tmp_path: Path):
    driven = _drive(
        tmp_path,
        [
            _after_tool("c1"),
            _after_tool("c2"),
            _after_tool("c3"),
            _agent_end(),
            _prompt("s2"),
            _prompt("s1"),
            _prompt("s1"),
        ],
    )

    other, reminded, after = (_context(result) for result in driven["results"][4:])
    assert_that((other, after), equal_to(("", "")))
    assert_that(reminded, contains_string("did work without recording it as a Task"))


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
    assert_that("Old work" in context, is_(False))


def test_open_tasks_are_cached_between_turns_until_a_task_changes(tmp_path: Path):
    _drive(
        tmp_path,
        [_prompt(), _prompt(), _tool(action="status", task_id="task-1", status="done"), _prompt()],
        open_tasks=[{"id": "task-1", "title": "Report", "status": "open"}],
    )

    assert_that(sum(call["argv"][0] == "list" for call in _calls(tmp_path)), equal_to(4))


def test_an_unavailable_task_service_does_not_break_the_turn(tmp_path: Path):
    driven = _drive(tmp_path, [_prompt()], AGENTBARN_TASK_COMMAND="/nonexistent/agentbarn-task")

    assert_that(driven["results"][0], is_(None))


# --- runs that produce files ---


@pytest.mark.parametrize("tool", ["write", "edit", "apply_patch"])
def test_a_run_that_writes_a_file_without_a_task_is_asked_to_revise(tmp_path: Path, tool: str):
    driven = _drive(tmp_path, [_after_tool("c1", tool=tool), _finalize()])

    assert_that(driven["results"][-1], has_entries(action="revise"))


def test_a_run_that_wrote_a_file_without_a_task_is_reminded_next_turn(tmp_path: Path):
    driven = _drive(tmp_path, [_after_tool("c1", tool="write"), _agent_end(), _prompt()])

    assert_that(_context(driven["results"][-1]), contains_string("did work without recording it as a Task"))

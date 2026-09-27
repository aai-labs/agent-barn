import json
import shlex
from pathlib import Path
from typing import Any
from uuid import uuid7

import pytest

from api.domains.business_value.catalogue import OutcomeType
from api.domains.business_value.classifier import BusinessActionStatus, ClassifiedAction, classify
from api.domains.tool_calls.models import ToolCall, ToolCallStatus

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "business_actions"
_ENVELOPE = (
    '{"code":"config_error","details":null,"message":"m","operation":"issues.get","service":"jira","status":null}'
)
_SUCCESS = BusinessActionStatus.SUCCESS
_ERROR = BusinessActionStatus.ERROR
_UNKNOWN = BusinessActionStatus.UNKNOWN


def _tool_call(
    tool_name: str, arguments: dict[str, Any], result: Any, status: ToolCallStatus = ToolCallStatus.SUCCESS
) -> ToolCall:
    return ToolCall(
        organization_id=uuid7(),
        agent_id=uuid7(),
        session_id="session",
        external_id="call",
        tool_name=tool_name,
        arguments=arguments,
        result=result,
        status=status,
    )


def _hermes(command: str, *, exit_code: int = 0, output: str = "{}", **arguments: Any) -> ToolCall:
    result = json.dumps({"output": output, "exit_code": exit_code, "error": None})
    return _tool_call("terminal", {"command": command, **arguments}, result, ToolCallStatus.SUCCESS)


def _openclaw(
    command: str,
    *,
    exit_code: int | None = 0,
    output: str = "{}",
    details_status: str = "completed",
    status: ToolCallStatus = ToolCallStatus.SUCCESS,
) -> ToolCall:
    details = {"status": details_status, "exitCode": exit_code, "aggregated": output}
    return _tool_call(
        "exec", {"command": command}, {"content": [{"type": "text", "text": output}], "details": details}, status
    )


def _paths(actions: list[ClassifiedAction]) -> list[tuple[str, str, str, bool | None, OutcomeType | None]]:
    return [(a.integration, a.resource, a.verb, a.is_write, a.outcome_type) for a in actions]


def _statuses(actions: list[ClassifiedAction]) -> list[BusinessActionStatus]:
    return [a.status for a in actions]


def _openclaw_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (
            "aai-cli jira issues comments create ABC-1 --body x",
            [("jira", "issues comments", "create", True, OutcomeType.COMMENT_POSTED)],
        ),
        (
            "aai-cli --profile work github prs create --title t",
            [("github", "prs", "create", True, OutcomeType.PULL_REQUEST_OPENED)],
        ),
        (
            "aai-cli github prs create --title t --profile=work",
            [("github", "prs", "create", True, OutcomeType.PULL_REQUEST_OPENED)],
        ),
        (
            "aai-cli github --profile work prs --profile=other create",
            [("github", "prs", "create", True, OutcomeType.PULL_REQUEST_OPENED)],
        ),
        (
            "aai-cli --config /c --secrets-file /s --key-file=/k jira issues get A-1",
            [("jira", "issues", "get", False, None)],
        ),
        ("/usr/local/bin/aai-cli excel sheets list f.xlsx", [("excel", "sheets", "list", False, None)]),
        ("AAI_PROFILE=x FOO=bar aai-cli excel sheets list f.xlsx", [("excel", "sheets", "list", False, None)]),
        (
            "aai-cli microsoft excel tables rows append T1 --values v",
            [("microsoft", "excel tables rows", "append", True, OutcomeType.SPREADSHEET_UPDATED)],
        ),
        ("aai-cli jira issues get create", [("jira", "issues", "get", False, None)]),
        (
            "aai-cli confluence pages update 123 --version 5 --body x",
            [("confluence", "pages", "update", True, OutcomeType.DOCUMENT_AUTHORED)],
        ),
        ("aai-cli pipedrive request get /api/v2/deals", [("pipedrive", "", "request", False, None)]),
        ("aai-cli hubspot request head /crm/v3/objects", [("hubspot", "", "request", False, None)]),
        (
            "aai-cli microsoft request POST /me/events --json x --allow-write",
            [("microsoft", "", "request", True, None)],
        ),
        ("aai-cli openpanel request", [("openpanel", "", "request", None, None)]),
        ("aai-cli jira issues transition A-1", [("jira", "issues", "transition", None, None)]),
        ("aai-cli jira issues 'Some Text'", [("jira", "issues", "", None, None)]),
        ("aai-cli excel nonsense-command", [("excel", "", "nonsense-command", None, None)]),
        ("aai-cli slack channels list", [("slack", "", "", None, None)]),
        (
            "aai-cli jira issues create --summary 'a && b; c | d'",
            [("jira", "issues", "create", True, OutcomeType.RECORD_CREATED)],
        ),
        (
            "aai-cli jira issues comments create A --body 'line1\nline2'",
            [("jira", "issues comments", "create", True, OutcomeType.COMMENT_POSTED)],
        ),
    ],
)
def test_classifies_command_paths(command, expected):
    assert _paths(classify(_hermes(command))) == expected


@pytest.mark.parametrize(
    "command",
    [
        "aai-cli jira issues create --help",
        "aai-cli jira issues create -h",
        "aai-cli --help",
        "aai-cli --version",
        "aai-cli help",
        "aai-cli excel help sheets",
        "aai-cli",
        "aai-cli jira",
        "aai-cli jira issues",
        "aai-cli jira issues --limit 5",
        "aai-cli 'Hello World'",
        "aai-cli config show",
        "aai-cli skills list",
        "aai-cli secrets set x",
        "aai-cli microsoft auth login",
        "aai-cli hubspot health",
        "aai-cli hubspot events custom send --json e.json",
        "aai-cli hubspot conversations visitor-identification tokens create --json t.json",
        "ls -la",
        "echo aai-cli jira issues get A-1",
        "grep aai-cli notes.txt",
        "aai-cli jira issues get 'unbalanced",
    ],
)
def test_ignores_commands_that_are_not_business_actions(command):
    assert classify(_hermes(command)) == []


def test_ignores_tool_calls_that_are_not_shell_commands():
    tool_call = _tool_call("read_file", {"command": "aai-cli jira issues get A-1"}, "x", ToolCallStatus.SUCCESS)
    assert classify(tool_call) == []


def test_ignores_shell_tool_calls_without_a_string_command():
    assert classify(_tool_call("exec", {}, None, ToolCallStatus.SUCCESS)) == []
    assert classify(_tool_call("exec", {"command": 1}, None, ToolCallStatus.SUCCESS)) == []


@pytest.mark.parametrize("quote", [shlex.quote, _openclaw_quote])
def test_unwraps_the_agentbarn_message_wrapper(quote):
    inner = "aai-cli excel values update f.xlsx \"'Sheet1'!A1\" --values x && agentbarn-message send hi"
    command = f"AGENTBARN_TOOL_SESSION={quote('s:1')} AGENTBARN_TOOL_INVOCATION={quote('call-1')} sh -c {quote(inner)}"

    actions = classify(_hermes(command))

    assert _paths(actions) == [("excel", "values", "update", True, OutcomeType.SPREADSHEET_UPDATED)]
    assert _statuses(actions) == [_SUCCESS]


def test_does_not_unwrap_an_unrelated_sh_c():
    assert classify(_hermes("sh -c 'aai-cli excel sheets list f.xlsx'")) == []


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("aai-cli excel workbook create f.xlsx && aai-cli excel sheets list f.xlsx", [_SUCCESS, _SUCCESS]),
        ("cd /tmp && aai-cli excel sheets list f.xlsx", [_SUCCESS]),
        ("aai-cli excel sheets list f.xlsx; aai-cli excel sheets add f.xlsx X", [_UNKNOWN, _SUCCESS]),
        ("aai-cli jira issues get A || aai-cli jira issues get B", [_UNKNOWN, _SUCCESS]),
        ("aai-cli excel sheets list f.xlsx | head -5", [_UNKNOWN]),
        ("aai-cli excel sheets list f.xlsx\naai-cli excel sheets add f.xlsx X", [_UNKNOWN, _SUCCESS]),
        ("aai-cli excel sheets list f.xlsx; echo done", [_UNKNOWN]),
        ("aai-cli excel sheets list f.xlsx &", [_UNKNOWN]),
    ],
)
def test_success_needs_a_zero_exit_that_covers_the_action(command, expected):
    actions = classify(_hermes(command))

    assert _statuses(actions) == expected
    assert [a.ordinal for a in actions] == list(range(len(expected)))


def test_ordinal_counts_every_aai_cli_invocation_including_ignored_ones():
    actions = classify(_hermes("aai-cli hubspot health && aai-cli jira issues get A-1"))

    assert [(a.ordinal, a.integration) for a in actions] == [(1, "jira")]


@pytest.mark.parametrize(
    "command",
    ["echo $(aai-cli jira issues get A-1)", "(aai-cli jira issues get A-1 && cd /tmp)"],
)
def test_subshell_invocations_are_never_success(command):
    actions = classify(_hermes(command))

    assert _paths(actions) == [("jira", "issues", "get", False, None)]
    assert _statuses(actions) == [_UNKNOWN]


@pytest.mark.parametrize("build", [_hermes, _openclaw])
def test_single_action_with_an_envelope_is_an_error(build):
    assert _statuses(classify(build("aai-cli jira issues get A-1", exit_code=3, output=_ENVELOPE))) == [_ERROR]


@pytest.mark.parametrize("build", [_hermes, _openclaw])
def test_envelope_overrides_a_zero_exit(build):
    actions = classify(build("aai-cli jira issues get A-1 | head -5", exit_code=0, output=_ENVELOPE))
    assert _statuses(actions) == [_ERROR]


@pytest.mark.parametrize("build", [_hermes, _openclaw])
def test_non_zero_exit_without_an_envelope_is_an_error(build):
    output = "error: unrecognized subcommand 'x'"
    assert _statuses(classify(build("aai-cli excel x", exit_code=2, output=output))) == [_ERROR]


def test_envelope_is_attributed_to_the_only_action_of_its_service():
    command = "aai-cli excel sheets list f.xlsx && aai-cli jira issues get A-1"

    actions = classify(_hermes(command, exit_code=3, output="{}\n" + _ENVELOPE))

    assert _statuses(actions) == [_UNKNOWN, _ERROR]


def test_unattributable_failure_leaves_every_action_unknown():
    same_service = "aai-cli jira issues get A-1 && aai-cli jira issues get A-2"
    no_envelope = "aai-cli excel sheets list f.xlsx && aai-cli jira issues get A-1"

    assert _statuses(classify(_hermes(same_service, exit_code=3, output=_ENVELOPE))) == [_UNKNOWN, _UNKNOWN]
    assert _statuses(classify(_hermes(no_envelope, exit_code=1, output="boom"))) == [_UNKNOWN, _UNKNOWN]


def test_hermes_background_run_is_unknown():
    tool_call = _hermes("aai-cli excel sheets list f.xlsx", output="Background process started", background=True)
    assert _statuses(classify(tool_call)) == [_UNKNOWN]


@pytest.mark.parametrize("hermes_status", ["blocked", "pending_approval"])
def test_hermes_blocked_run_is_an_error(hermes_status):
    result = json.dumps({"output": "", "error": "denied", "status": hermes_status})
    tool_call = _tool_call("terminal", {"command": "aai-cli excel sheets add f.xlsx X"}, result, ToolCallStatus.SUCCESS)
    assert _statuses(classify(tool_call)) == [_ERROR]


@pytest.mark.parametrize("result", [None, "not json", json.dumps(["x"]), json.dumps({"output": "x"})])
def test_hermes_result_without_exit_evidence_is_unknown(result):
    tool_call = _tool_call("terminal", {"command": "aai-cli excel sheets list f.xlsx"}, result, ToolCallStatus.SUCCESS)
    assert _statuses(classify(tool_call)) == [_UNKNOWN]


def test_openclaw_running_command_is_unknown():
    tool_call = _openclaw("aai-cli excel sheets list f.xlsx", exit_code=None, output="", details_status="running")
    assert _statuses(classify(tool_call)) == [_UNKNOWN]


@pytest.mark.parametrize("result", [None, "text", {"content": [{"type": "text", "text": "{}"}]}])
def test_openclaw_result_without_details_is_unknown(result):
    tool_call = _tool_call("exec", {"command": "aai-cli excel sheets list f.xlsx"}, result, ToolCallStatus.SUCCESS)
    assert _statuses(classify(tool_call)) == [_UNKNOWN]


def test_openclaw_reported_error_is_an_error():
    tool_call = _tool_call("exec", {"command": "aai-cli excel sheets list f.xlsx"}, None, ToolCallStatus.ERROR)
    assert _statuses(classify(tool_call)) == [_ERROR]


def _fixtures() -> list[tuple[str, dict[str, Any]]]:
    cases = []
    for path in sorted(_FIXTURES_DIR.glob("*.json")):
        for fixture in json.loads(path.read_text(encoding="utf-8")):
            cases.append((f"{path.stem}:{fixture['name']}", fixture))
    return cases


@pytest.mark.parametrize(("name", "fixture"), _fixtures(), ids=[name for name, _ in _fixtures()])
def test_classifies_recorded_runtime_tool_calls(name, fixture):
    tool_call = _tool_call(
        fixture["tool_name"],
        fixture["arguments"],
        fixture["result"],
        ToolCallStatus(fixture["stored_status"]),
    )

    actual = [
        {
            "ordinal": a.ordinal,
            "integration": a.integration,
            "resource": a.resource,
            "verb": a.verb,
            "is_write": a.is_write,
            "outcome_type": a.outcome_type.value if a.outcome_type else None,
            "status": a.status.value,
        }
        for a in classify(tool_call)
    ]

    assert actual == fixture["expected_actions"], name

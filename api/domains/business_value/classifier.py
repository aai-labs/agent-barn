import json
import logging
import re
import shlex
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from api.domains.business_value.catalogue import (
    GLOBAL_FLAGS,
    HELP_FLAGS,
    HELP_TOKEN,
    IGNORED_GROUPS,
    INTEGRATIONS,
    PASSTHROUGH_READ_METHODS,
    CommandKind,
    OutcomeType,
    deepest_node,
    longest_match,
)
from api.domains.tool_calls.models import ToolCall, ToolCallStatus

logger = logging.getLogger(__name__)

SHELL_TOOL_NAMES = frozenset({"terminal", "exec"})
EXECUTABLE = "aai-cli"
WRAPPER_ASSIGNMENTS = ("AGENTBARN_TOOL_SESSION=", "AGENTBARN_TOOL_INVOCATION=")
PUNCTUATION = "();<>|&\n"
SEPARATORS = frozenset({"&&", "||", "|", "|&", ";", ";;", "&", "\n", "(", ")"})
SUCCESS_TERMINATORS = frozenset({None, ";", "\n"})
ENVELOPE_KEYS = frozenset({"code", "message", "operation", "service"})
HERMES_FAILURE_STATUSES = frozenset({"blocked", "pending_approval"})
OPENCLAW_COMPLETED = "completed"
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
COMMAND_TOKEN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")


class BusinessActionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ClassifiedAction:
    ordinal: int
    integration: str
    resource: str
    verb: str
    is_write: bool | None
    outcome_type: OutcomeType | None
    status: BusinessActionStatus


@dataclass(frozen=True)
class _Segment:
    tokens: list[str]
    terminator: str | None


@dataclass(frozen=True)
class _Invocation:
    ordinal: int
    segment_index: int
    integration: str
    resource: str
    verb: str
    is_write: bool | None
    outcome_type: OutcomeType | None


@dataclass(frozen=True)
class _Evidence:
    exit_code: int | None
    reported_failure: bool
    envelope_services: list[str]


def classify(tool_call: ToolCall) -> list[ClassifiedAction]:
    command = tool_call.arguments.get("command") if isinstance(tool_call.arguments, dict) else None
    if tool_call.tool_name not in SHELL_TOOL_NAMES or not isinstance(command, str):
        return []
    try:
        segments = _segments(_unwrap(command))
    except ValueError:
        logger.warning("Could not tokenize the command of tool call %s", tool_call.id)
        return []

    invocations = _invocations(segments)
    if not invocations:
        return []
    statuses = _statuses(tool_call, segments, invocations)
    return [
        ClassifiedAction(
            ordinal=invocation.ordinal,
            integration=invocation.integration,
            resource=invocation.resource,
            verb=invocation.verb,
            is_write=invocation.is_write,
            outcome_type=invocation.outcome_type,
            status=status,
        )
        for invocation, status in zip(invocations, statuses, strict=True)
    ]


def _tokenize(command: str) -> list[str]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=PUNCTUATION)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    return list(lexer)


def _unwrap(command: str) -> str:
    tokens = _tokenize(command)
    prefix = len(WRAPPER_ASSIGNMENTS)
    if (
        len(tokens) == prefix + 3
        and all(token.startswith(name) for token, name in zip(tokens, WRAPPER_ASSIGNMENTS, strict=False))
        and tokens[prefix : prefix + 2] == ["sh", "-c"]
    ):
        return tokens[-1]
    return command


def _separator(token: str) -> str | None:
    if not token or any(char not in PUNCTUATION for char in token) or "<" in token or ">" in token:
        return None
    operator = token.replace("\n", "")
    if not operator:
        return "\n"
    return operator if operator in SEPARATORS else None


def _segments(command: str) -> list[_Segment]:
    segments: list[_Segment] = []
    current: list[str] = []
    for token in _tokenize(command):
        operator = _separator(token)
        if operator is None:
            current.append(token)
            continue
        if current:
            segments.append(_Segment(current, operator))
        elif segments and segments[-1].terminator in SUCCESS_TERMINATORS:
            segments[-1] = _Segment(segments[-1].tokens, operator)
        current = []
    if current:
        segments.append(_Segment(current, None))
    return segments


def _invocations(segments: list[_Segment]) -> list[_Invocation]:
    invocations: list[_Invocation] = []
    ordinal = 0
    for index, segment in enumerate(segments):
        arguments = _aai_cli_arguments(segment.tokens)
        if arguments is None:
            continue
        invocation = _invocation(ordinal, index, arguments)
        ordinal += 1
        if invocation is not None:
            invocations.append(invocation)
    return invocations


def _aai_cli_arguments(tokens: list[str]) -> list[str] | None:
    position = 0
    while position < len(tokens) and ASSIGNMENT.match(tokens[position]):
        position += 1
    if position >= len(tokens) or tokens[position].rsplit("/", 1)[-1] != EXECUTABLE:
        return None
    return _strip_global_flags(tokens[position + 1 :])


def _strip_global_flags(tokens: list[str]) -> list[str]:
    kept: list[str] = []
    skip_value = False
    for token in tokens:
        if skip_value:
            skip_value = False
        elif token in GLOBAL_FLAGS:
            skip_value = True
        elif "=" not in token or token.split("=", 1)[0] not in GLOBAL_FLAGS:
            kept.append(token)
    return kept


def _invocation(ordinal: int, segment_index: int, arguments: list[str]) -> _Invocation | None:
    if not arguments or any(token in HELP_FLAGS for token in arguments):
        return None
    group = arguments[0]
    if group in IGNORED_GROUPS or not COMMAND_TOKEN.match(group):
        return None
    if group not in INTEGRATIONS:
        return _Invocation(ordinal, segment_index, group, "", "", None, None)

    match = longest_match(arguments)
    if match is None:
        return _unknown_path(ordinal, segment_index, arguments)
    path, entry = match
    if entry.kind is CommandKind.IGNORED:
        return None

    is_write: bool | None = entry.kind is CommandKind.WRITE
    if entry.kind is CommandKind.PASSTHROUGH:
        method = arguments[len(path)].lower() if len(arguments) > len(path) else None
        is_write = None if method is None else method not in PASSTHROUGH_READ_METHODS
    return _Invocation(ordinal, segment_index, group, " ".join(path[1:-1]), path[-1], is_write, entry.outcome_type)


def _unknown_path(ordinal: int, segment_index: int, arguments: list[str]) -> _Invocation | None:
    node = deepest_node(arguments)
    if len(arguments) <= len(node):
        return None
    candidate = arguments[len(node)]
    if candidate == HELP_TOKEN or candidate.startswith("-"):
        return None
    verb = candidate if COMMAND_TOKEN.match(candidate) else ""
    return _Invocation(ordinal, segment_index, arguments[0], " ".join(node[1:]), verb, None, None)


def _statuses(
    tool_call: ToolCall, segments: list[_Segment], invocations: list[_Invocation]
) -> list[BusinessActionStatus]:
    if tool_call.arguments.get("background") is True:
        return [BusinessActionStatus.UNKNOWN] * len(invocations)

    evidence = _evidence(tool_call)
    failed = evidence.reported_failure or bool(evidence.envelope_services) or evidence.exit_code not in (None, 0)
    if failed:
        return _failure_statuses(invocations, evidence.envelope_services)
    if evidence.exit_code != 0:
        return [BusinessActionStatus.UNKNOWN] * len(invocations)

    if all(segment.terminator in (None, "&&") for segment in segments):
        return [BusinessActionStatus.SUCCESS] * len(invocations)
    last = len(segments) - 1
    return [
        BusinessActionStatus.SUCCESS
        if invocation.segment_index == last and segments[last].terminator in SUCCESS_TERMINATORS
        else BusinessActionStatus.UNKNOWN
        for invocation in invocations
    ]


def _failure_statuses(invocations: list[_Invocation], envelope_services: list[str]) -> list[BusinessActionStatus]:
    if len(invocations) == 1:
        return [BusinessActionStatus.ERROR]
    if len(envelope_services) == 1:
        matching = [invocation for invocation in invocations if invocation.integration == envelope_services[0]]
        if len(matching) == 1:
            return [
                BusinessActionStatus.ERROR if invocation is matching[0] else BusinessActionStatus.UNKNOWN
                for invocation in invocations
            ]
    return [BusinessActionStatus.UNKNOWN] * len(invocations)


def _evidence(tool_call: ToolCall) -> _Evidence:
    result: Any = tool_call.result
    if isinstance(result, str):
        raw = result
        try:
            result = json.loads(raw)
        except ValueError:
            return _Evidence(None, tool_call.status == ToolCallStatus.ERROR, _envelope_services(raw))
    if not isinstance(result, dict):
        return _Evidence(None, tool_call.status == ToolCallStatus.ERROR, [])

    exit_code: int | None = None
    reported_failure = tool_call.status == ToolCallStatus.ERROR
    outputs: list[str] = []
    details = result.get("details")
    if isinstance(details, dict):
        if details.get("status") == OPENCLAW_COMPLETED:
            exit_code = _integer(details.get("exitCode"))
        outputs.append(_text(details.get("aggregated")))
        outputs.extend(_text(part.get("text")) for part in _list(result.get("content")) if isinstance(part, dict))
    else:
        exit_code = _integer(result.get("exit_code"))
        reported_failure = (
            reported_failure or result.get("error") is not None or result.get("status") in HERMES_FAILURE_STATUSES
        )
        outputs.append(_text(result.get("output")))
    return _Evidence(exit_code, reported_failure, _envelope_services("\n".join(outputs)))


def _envelope_services(output: str) -> list[str]:
    services = []
    for line in output.splitlines():
        candidate = line.strip()
        if not (candidate.startswith("{") and candidate.endswith("}")):
            continue
        try:
            envelope = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(envelope, dict) and ENVELOPE_KEYS <= envelope.keys():
            services.append(str(envelope["service"]))
    return services


def _integer(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []

import datetime
import json
import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class ParsedToolCall:
    external_id: str
    session_id: str
    tool_name: str
    arguments: dict[str, Any]
    occurred_at: datetime.datetime


@dataclass
class ParsedToolResult:
    external_id: str  # matches ParsedToolCall.external_id
    result: list[Any] | None
    is_error: bool
    completed_at: datetime.datetime


def parse_jsonl(
    raw: str, session_id: str
) -> tuple[list[ParsedToolCall], list[ParsedToolResult]]:
    """Parse openclaw JSONL transcript text into tool call and result records."""
    tool_calls: list[ParsedToolCall] = []
    tool_results: list[ParsedToolResult] = []

    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed JSONL line: %.100s", line)
            continue

        if entry.get("type") != "message":
            continue

        msg = entry.get("message", {})
        role = msg.get("role")

        if role == "assistant":
            ts_ms = msg.get("timestamp")
            if ts_ms is None:
                continue
            for item in msg.get("content", []):
                if item.get("type") == "toolCall":
                    tool_calls.append(
                        ParsedToolCall(
                            external_id=item["id"],
                            session_id=session_id,
                            tool_name=item["name"],
                            arguments=item.get("arguments", {}),
                            occurred_at=_ms_to_utc(ts_ms),
                        )
                    )

        elif role == "toolResult":
            ts_ms = msg.get("timestamp")
            if ts_ms is None:
                continue
            tool_results.append(
                ParsedToolResult(
                    external_id=msg["toolCallId"],
                    result=msg.get("content"),
                    is_error=msg.get("isError", False),
                    completed_at=_ms_to_utc(ts_ms),
                )
            )

    return tool_calls, tool_results


def _ms_to_utc(ts_ms: int) -> datetime.datetime:
    return datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=datetime.timezone.utc)

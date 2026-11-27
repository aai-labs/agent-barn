"""OpenClaw reaches Organization MCP Servers through the gateway with the Agent's token, and
forgets a server the Organization removed even though its config persists on the volume."""

import json
from pathlib import Path

import pytest
from hamcrest import assert_that, contains_exactly, equal_to

from api.runtime_tests.mcp_servers_contract import TOKEN, server, start_runtime
from api.runtime_tests.memory_helpers import selected_image
from api.tests.core.givenpy import then, when


@pytest.fixture
def openclaw_image() -> str:
    return selected_image("openclaw")


_REMOVED_SERVER = {"mcp": {"servers": {"removed": {"url": "http://mcp-gateway:18765/gateway/v1/mcp/removed"}}}}


def test_openclaw_connects_with_its_token_and_applies_the_tool_filter(openclaw_image: str, tmp_path: Path):
    with when("OpenClaw starts with a server that hides one tool, over a config that still lists a removed one"):
        run = start_runtime(
            "openclaw",
            openclaw_image,
            tmp_path,
            [server("wiki", tool_exclude=["summarize"])],
            probe="wiki",
            saved_openclaw_config=_REMOVED_SERVER,
        )

    with then("only the current server survives the merge into the saved config"):
        merged = json.loads(run.output("openclaw.json"))
        assert_that(list(merged["mcp"]["servers"]), contains_exactly("wiki"), run.completed.stderr)

    with then("its MCP client reached the gateway with the Secret's token and kept the visible tool"):
        assert_that({r["authorization"] for r in run.requests}, equal_to({f"Bearer {TOKEN}"}))
        probe = run.output("probe.json")
        assert_that("search" in probe and "summarize" not in probe, equal_to(True), probe + run.output("probe.err"))


def test_openclaw_starts_cleanly_with_no_servers(openclaw_image: str, tmp_path: Path):
    with when("OpenClaw starts with an empty server list over a config that lists a removed one"):
        run = start_runtime(
            "openclaw", openclaw_image, tmp_path, [], probe="removed", saved_openclaw_config=_REMOVED_SERVER
        )

    with then("the saved list is emptied and nothing reaches the gateway"):
        assert_that(json.loads(run.output("openclaw.json"))["mcp"], equal_to({"servers": {}}), run.completed.stderr)
        assert_that(run.requests, equal_to([]))

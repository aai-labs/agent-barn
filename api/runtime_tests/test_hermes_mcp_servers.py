"""Hermes reaches Organization MCP Servers through the gateway with the Agent's token."""

from pathlib import Path

import pytest
import yaml
from hamcrest import assert_that, contains_string, equal_to, has_entries, has_item

from api.runtime_tests.mcp_servers_contract import TOKEN, server, start_runtime
from api.runtime_tests.memory_helpers import selected_image
from api.tests.core.givenpy import then, when


@pytest.fixture
def hermes_image() -> str:
    return selected_image("hermes")


def test_hermes_connects_to_the_gateway_with_the_token_from_its_environment(hermes_image: str, tmp_path: Path):
    with when("Hermes starts with one Organization MCP Server and tests it"):
        run = start_runtime("hermes", hermes_image, tmp_path, [server("wiki")], probe="wiki")

    with then("its own MCP client connected and listed the server's tools"):
        assert_that(run.output("mcp-test.txt"), contains_string("Tools discovered: 2"), run.completed.stderr)

    with then("every request to the gateway carried the token the pod's Secret holds"):
        posts = [r for r in run.requests if r["method"] == "POST"]
        assert_that(posts, has_item(has_entries(rpc="initialize")))
        assert_that({r["authorization"] for r in run.requests}, equal_to({f"Bearer {TOKEN}"}))

    with then("the merged config keeps sampling and elicitation off"):
        block = yaml.safe_load(run.output("config.yaml"))["mcp_servers"]["wiki"]
        assert_that(block, has_entries(sampling={"enabled": False}, elicitation={"enabled": False}))

"""Which Honcho requests an Agent may send through the memory proxy (AF-338).

The proxy forwards with a token scoped to the Agent's own pool, so Honcho refuses
other workspaces anyway. These rules add what that scope does not: an Agent must
not rewrite its pool's configuration (our deriver instructions live there),
delete the pool, or drive cost the runtimes never need.
"""

import pytest
from hamcrest import assert_that, equal_to

from api.domains.memory_proxy.policy import MemoryRequestRefused, check_memory_request

WS = "af-pool-0199"


def allowed(method, path, body=None):
    check_memory_request(method, path, body, WS)
    return True


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", f"v3/workspaces/{WS}/chat"),
        ("POST", f"v3/workspaces/{WS}/peers"),
        ("POST", f"v3/workspaces/{WS}/peers/agent-1/chat"),
        ("POST", f"v3/workspaces/{WS}/sessions/s1/messages"),
        ("GET", f"v3/workspaces/{WS}/sessions/s1/context"),
        ("PUT", f"v3/workspaces/{WS}/sessions/s1"),
        ("POST", f"v3/workspaces/{WS}/search"),
        ("DELETE", f"v3/workspaces/{WS}/conclusions/c1"),
    ],
)
def test_the_runtimes_calls_inside_the_agents_own_pool_pass(method, path):
    assert_that(allowed(method, path), equal_to(True))


def test_getting_or_creating_the_agents_own_workspace_passes():
    assert_that(allowed("POST", "v3/workspaces", {"id": WS, "metadata": {}}), equal_to(True))


def test_the_openclaw_plugins_workspace_metadata_write_passes():
    """The stock plugin stores its peer map in workspace metadata."""
    assert_that(allowed("PUT", f"v3/workspaces/{WS}", {"metadata": {"agentPeerMap": {}}}), equal_to(True))


def test_reading_the_workspace_passes():
    assert_that(allowed("GET", f"v3/workspaces/{WS}"), equal_to(True))


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        # Another pool, or every pool.
        ("POST", "v3/workspaces/af-pool-other/chat", None),
        ("POST", "v3/workspaces/list", {}),
        ("POST", "v3/workspaces", {"id": "af-pool-other"}),
        # Minting keys is Honcho's admin surface.
        ("POST", "v3/keys", {}),
        # The pool's configuration holds our deriver instructions; get-or-create
        # applies a configuration only when it creates, but refuse it there too.
        ("PUT", f"v3/workspaces/{WS}", {"configuration": {"reasoning": {"custom_instructions": "x"}}}),
        ("PUT", f"v3/workspaces/{WS}", {"metadata": {}, "configuration": {}}),
        ("POST", "v3/workspaces", {"id": WS, "configuration": {}}),
        # Erasing the pool is the group's delete, not an Agent's.
        ("DELETE", f"v3/workspaces/{WS}", None),
        # Dreams are extra model work no runtime asks for.
        ("POST", f"v3/workspaces/{WS}/schedule_dream", {}),
        # Anything outside /v3.
        ("GET", "health", None),
        ("GET", "v2/workspaces", None),
    ],
)
def test_requests_outside_the_agents_own_pool_or_rights_are_refused(method, path, body):
    with pytest.raises(MemoryRequestRefused):
        check_memory_request(method, path, body, WS)


@pytest.mark.parametrize(
    "path", [f"v3/workspaces/{WS}/../af-pool-other/chat", f"v3/workspaces/{WS}/./chat", "v3//keys"]
)
def test_paths_that_could_escape_the_pool_are_refused(path):
    with pytest.raises(MemoryRequestRefused):
        check_memory_request("POST", path, None, WS)


def test_a_workspace_write_whose_body_cannot_be_read_is_refused():
    with pytest.raises(MemoryRequestRefused):
        check_memory_request("PUT", f"v3/workspaces/{WS}", "not json", WS)


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        # Sessions, peers and messages carry configuration that overrides the pool's
        # (deriver instructions, dreams), so it is refused wherever it appears.
        ("POST", f"v3/workspaces/{WS}/sessions", {"id": "s1", "configuration": {"dream": {"enabled": True}}}),
        ("PUT", f"v3/workspaces/{WS}/sessions/s1", {"configuration": {"reasoning": {"custom_instructions": "x"}}}),
        ("PUT", f"v3/workspaces/{WS}/peers/p1", {"configuration": {}}),
        (
            "POST",
            f"v3/workspaces/{WS}/sessions/s1/messages",
            {"messages": [{"content": "hi", "peer_id": "p1"}, {"content": "x", "peer_id": "p1", "configuration": {}}]},
        ),
    ],
)
def test_configuration_is_refused_below_the_pool_too(method, path, body):
    with pytest.raises(MemoryRequestRefused):
        check_memory_request(method, path, body, WS)


def test_what_the_runtimes_actually_send_still_passes():
    """Neither runtime sends configuration; session peer observation settings are a
    different field and stay allowed."""
    assert_that(allowed("POST", f"v3/workspaces/{WS}/sessions", {"id": "s1", "metadata": {}}), equal_to(True))
    assert_that(
        allowed("POST", f"v3/workspaces/{WS}/sessions/s1/messages", {"messages": [{"content": "hi", "peer_id": "p1"}]}),
        equal_to(True),
    )
    assert_that(allowed("PUT", f"v3/workspaces/{WS}/sessions/s1/peers/p1/config", {"observe_me": True}), equal_to(True))

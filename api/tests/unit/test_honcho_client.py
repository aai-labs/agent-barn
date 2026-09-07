"""HonchoClient request shaping.

These pin the request the client makes, not Honcho's behaviour — the calls were
verified against a live server separately. What matters here is that a rename or a
reorder does not silently change what hits the API.
"""

from unittest.mock import patch

from hamcrest import assert_that, equal_to

from api.core.config import Config
from api.infrastructure.honcho.client import HonchoClient


def _client() -> HonchoClient:
    return HonchoClient(config=Config(honcho_base_url="http://honcho"))


def test_ensure_deriver_instructions_creates_then_updates():
    """The runtime creates the workspace lazily, and get-or-create does not update
    an existing workspace's config — so the client must both create (to exist) and
    update (to set config, including on workspaces that predate this)."""
    client = _client()
    calls: list[tuple[str, str, dict]] = []
    with patch.object(
        HonchoClient, "_request", side_effect=lambda m, p, **kw: calls.append((m, p, kw.get("json", {})))
    ):
        client.ensure_deriver_instructions("af-x", "Record only durable facts.")

    assert_that([(m, p) for m, p, _ in calls], equal_to([("POST", "/workspaces"), ("PUT", "/workspaces/af-x")]))
    # Both carry the instruction under reasoning.custom_instructions.
    for _, _, body in calls:
        assert_that(body["configuration"]["reasoning"]["custom_instructions"], equal_to("Record only durable facts."))
    # The create call also names the workspace; the update addresses it by path.
    assert_that(calls[0][2]["id"], equal_to("af-x"))


def test_default_deriver_instruction_excludes_transient_actions():
    """The point of the instruction is to drop "the peer asked X" — guard that the
    shipped text actually says so, since it is the whole mechanism."""
    text = HonchoClient.DERIVER_INSTRUCTIONS.lower()
    assert_that("durable facts" in text, equal_to(True))
    assert_that("asked a question" in text, equal_to(True))

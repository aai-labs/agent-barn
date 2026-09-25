"""HonchoClient request shaping.

These pin the request the client makes, not Honcho's behaviour — the calls were
verified against a live server separately. What matters here is that a rename or a
reorder does not silently change what hits the API.
"""

from unittest.mock import patch

import jwt
from hamcrest import assert_that, equal_to

from api.core.config import Config
from api.infrastructure.honcho.client import HonchoClient, mint_admin_token, mint_workspace_token

_SECRET = "a-shared-honcho-jwt-secret"


def _client() -> HonchoClient:
    return HonchoClient(config=Config(honcho_base_url="http://honcho"))


def test_mint_admin_token_carries_the_admin_claim():
    decoded = jwt.decode(mint_admin_token(_SECRET), _SECRET.encode("utf-8"), algorithms=["HS256"])
    assert_that(decoded.get("ad"), equal_to(True))


def test_mint_workspace_token_is_scoped_to_one_workspace_and_is_not_admin():
    """A pod's token grants its own pool workspace (`w`) and nothing more — no admin
    claim, so a prompt-injected pod cannot reach another org's pool."""
    decoded = jwt.decode(mint_workspace_token(_SECRET, "af-pool-abc"), _SECRET.encode("utf-8"), algorithms=["HS256"])
    assert_that(decoded.get("w"), equal_to("af-pool-abc"))
    assert_that(decoded.get("ad"), equal_to(None))


def test_requests_carry_an_admin_bearer_when_auth_is_configured():
    client = HonchoClient(config=Config(honcho_base_url="http://honcho", honcho_jwt_secret=_SECRET))
    header = client._auth_headers["Authorization"]
    assert_that(header.startswith("Bearer "), equal_to(True))
    decoded = jwt.decode(header.split(" ", 1)[1], _SECRET.encode("utf-8"), algorithms=["HS256"])
    assert_that(decoded.get("ad"), equal_to(True))


def test_no_bearer_when_auth_is_disabled():
    """Empty secret = Honcho auth off (dev): the client sends no Authorization."""
    assert_that(_client()._auth_headers, equal_to({}))


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

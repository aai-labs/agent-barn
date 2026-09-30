import pytest

from api.domains.communications.addressing import (
    SLUG_LIMIT,
    build_local_part,
    compose_address,
    extract_local_part,
)


def test_local_part_carries_a_readable_slug_of_the_agent_name() -> None:
    assert build_local_part("Tommy").startswith("tommy-")


@pytest.mark.parametrize(
    ("agent_name", "expected_slug"),
    [
        ("Tommy The Helper", "tommy-the-helper"),
        ("Support  Bot!!", "support-bot"),
        ("  spaced  ", "spaced"),
        ("Ünïcødé", "n-c-d"),
        ("---", "agent"),
        ("", "agent"),
        ("123", "123"),
    ],
)
def test_agent_names_reduce_to_an_address_safe_slug(agent_name, expected_slug) -> None:
    local_part = build_local_part(agent_name)

    assert local_part.rsplit("-", 1)[0] == expected_slug


def test_a_long_agent_name_is_truncated_without_a_trailing_separator() -> None:
    local_part = build_local_part("A" * 100)

    slug = local_part.rsplit("-", 1)[0]
    assert len(slug) <= SLUG_LIMIT
    assert not slug.endswith("-")


def test_two_agents_with_the_same_name_get_different_local_parts() -> None:
    assert build_local_part("Tommy") != build_local_part("Tommy")


def test_an_address_is_the_mailbox_subaddressed_with_the_local_part() -> None:
    assert compose_address("agent", "tommy-4f2a", "agents.agentbarn.dev") == ("agent+tommy-4f2a@agents.agentbarn.dev")


def test_the_local_part_round_trips_out_of_a_composed_address() -> None:
    address = compose_address("agent", "tommy-4f2a", "agents.agentbarn.dev")

    assert extract_local_part("agent", address) == "tommy-4f2a"


@pytest.mark.parametrize(
    "address",
    [
        "AGENT+Tommy-4F2A@AGENTS.AGENTBARN.DEV",
        "  agent+tommy-4f2a@agents.agentbarn.dev  ",
    ],
)
def test_extracting_a_local_part_normalizes_case_and_whitespace(address) -> None:
    assert extract_local_part("agent", address) == "tommy-4f2a"


@pytest.mark.parametrize(
    "address",
    [
        "agent@agents.agentbarn.dev",
        "someone+tommy-4f2a@agents.agentbarn.dev",
        "agent+tommy-4f2a",
        "",
        "@agents.agentbarn.dev",
    ],
)
def test_an_address_that_is_not_a_subaddressed_agent_yields_no_local_part(address) -> None:
    assert extract_local_part("agent", address) == ""

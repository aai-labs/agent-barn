from datetime import UTC, datetime

from hamcrest import assert_that, equal_to, has_entry, is_not, none

from api.domains.restore_points.models import selection_from_manifest

_MANIFEST = {
    "version": 2,
    "agent_type": "hermes",
    "template_key": "recorded-template",
    "template_version": 1,
    "template_selection_type": "organization",
    "override_version": None,
    "model": "",
    "effective_model": "",
    "approval_mode": "auto",
    "verbose_mode": False,
    "skills": [],
}


def _replayed(manifest: dict) -> dict:
    selection = selection_from_manifest(manifest, datetime.now(UTC))
    assert selection is not None
    return selection.model_dump(exclude_unset=True)


def test_a_manifest_recorded_before_turn_limits_leaves_the_limit_alone() -> None:
    assert_that(_replayed(_MANIFEST), is_not(has_entry("max_turns", none())))


def test_a_recorded_turn_limit_is_replayed() -> None:
    assert_that(_replayed({**_MANIFEST, "max_turns": 150})["max_turns"], equal_to(150))


def test_a_recorded_platform_default_is_replayed_as_a_cleared_limit() -> None:
    assert_that(_replayed({**_MANIFEST, "max_turns": None}), has_entry("max_turns", none()))

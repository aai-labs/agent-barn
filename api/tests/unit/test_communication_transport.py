import pytest
from hamcrest import assert_that, equal_to

from api.core.config import Config
from api.domains.communications.transport import NATIVE_PLATFORM_KEYS, platform_transport


@pytest.mark.parametrize("legacy_allowlist", ["", "slack", "slack,discord,telegram,teams", "web,email"])
def test_deployment_configuration_cannot_change_platform_ownership(legacy_allowlist: str, monkeypatch) -> None:
    monkeypatch.setenv("COMMUNICATIONS_NATIVE_PLATFORMS", legacy_allowlist)
    # Stale external environment entries cannot break startup or restore a switch.
    Config()

    assert_that(NATIVE_PLATFORM_KEYS, equal_to(frozenset({"slack", "discord", "telegram", "teams"})))
    for key in NATIVE_PLATFORM_KEYS:
        assert_that(platform_transport(key), equal_to("native"))
    for key in ("web", "email"):
        assert_that(platform_transport(key), equal_to("gateway"))

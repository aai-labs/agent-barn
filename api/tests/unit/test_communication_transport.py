import pytest
from hamcrest import assert_that, equal_to

from api.core.config import Config
from api.domains.communications.transport import NATIVE_PLATFORM_KEYS, platform_transport


@pytest.mark.parametrize("legacy_allowlist", ["", "slack", "slack,discord,telegram,teams", "web,email"])
def test_deployment_configuration_cannot_change_platform_ownership(legacy_allowlist: str) -> None:
    config = Config(communications_native_platforms=legacy_allowlist)

    assert_that(config.native_platform_keys, equal_to(frozenset({"slack", "discord", "telegram", "teams"})))
    for key in NATIVE_PLATFORM_KEYS:
        assert_that(platform_transport(key), equal_to("native"))
    for key in ("web", "email"):
        assert_that(platform_transport(key), equal_to("gateway"))

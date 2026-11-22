import pytest

from api.runtime_tests.ssh_contract import ssh_should_run
from api.runtime_tests.ssh_startup import ssh_disabled_should_start


@pytest.mark.parametrize(
    "with_bot,shared_key", [(False, False), (True, False), (True, True)], ids=["agent", "bot", "shared-key"]
)
def test_hermes_ssh_access(tmp_path, with_bot, shared_key):
    ssh_should_run("hermes", tmp_path, with_bot=with_bot, shared_key=shared_key)


@pytest.mark.parametrize("manifest", ["empty", "unkeyed-bot"])
def test_hermes_without_ssh_credentials_starts_on_older_images(tmp_path, manifest):
    ssh_disabled_should_start("hermes", manifest, tmp_path)

import pytest

from api.runtime_tests.ssh_contract import ssh_should_run


@pytest.mark.parametrize(
    "with_bot,shared_key", [(False, False), (True, False), (True, True)], ids=["agent", "bot", "shared-key"]
)
def test_openclaw_ssh_access(tmp_path, with_bot, shared_key):
    ssh_should_run("openclaw", tmp_path, with_bot=with_bot, shared_key=shared_key)

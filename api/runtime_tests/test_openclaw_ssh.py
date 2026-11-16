from api.runtime_tests.ssh_contract import ssh_should_run


def test_openclaw_ssh_access(tmp_path):
    ssh_should_run("openclaw", tmp_path)

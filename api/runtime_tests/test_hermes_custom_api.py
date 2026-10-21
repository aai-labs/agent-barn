from pathlib import Path

from api.runtime_tests.custom_api_contract import custom_api_should_run


def test_hermes_custom_api_command(tmp_path: Path):
    custom_api_should_run("hermes", tmp_path)

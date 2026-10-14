from pathlib import Path

from api.runtime_tests.sharepoint_contract import sharepoint_should_handoff


def test_hermes_sharepoint_broker_and_handoff(tmp_path: Path):
    sharepoint_should_handoff("hermes", tmp_path)

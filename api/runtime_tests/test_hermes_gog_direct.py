from pathlib import Path

from api.runtime_tests.gog_direct_contract import direct_google_should_import


def test_hermes_gog_imports_direct_credentials(tmp_path: Path):
    direct_google_should_import("hermes", tmp_path)

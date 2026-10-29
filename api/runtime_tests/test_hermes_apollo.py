from pathlib import Path

from api.runtime_tests.apollo_contract import apollo_should_route


def test_hermes_apollo_routes_direct_and_isolated(tmp_path: Path):
    apollo_should_route("hermes", tmp_path)

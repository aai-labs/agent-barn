from pathlib import Path

from api.runtime_tests.apollo_contract import apollo_should_route


def test_openclaw_apollo_routes_direct_and_isolated(tmp_path: Path):
    apollo_should_route("openclaw", tmp_path)

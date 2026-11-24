from pathlib import Path

import pytest

from api.runtime_tests.file_sync_contract import selected_image
from api.runtime_tests.stop_during_boot_contract import stop_should_end_the_container_while_start_sh_is_in_setup


@pytest.fixture
def openclaw_image() -> str:
    return selected_image("openclaw")


def test_openclaw_stops_on_sigterm_while_start_sh_is_in_setup(openclaw_image: str, tmp_path: Path):
    stop_should_end_the_container_while_start_sh_is_in_setup("openclaw", openclaw_image, tmp_path)

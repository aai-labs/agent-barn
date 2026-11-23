from pathlib import Path

import pytest

from api.runtime_tests.file_sync_contract import selected_image
from api.runtime_tests.stop_during_boot_contract import stop_should_end_the_container_while_start_sh_is_in_setup


@pytest.fixture
def hermes_image() -> str:
    return selected_image("hermes")


def test_hermes_stops_on_sigterm_while_start_sh_is_in_setup(hermes_image: str, tmp_path: Path):
    stop_should_end_the_container_while_start_sh_is_in_setup("hermes", hermes_image, tmp_path)

from pathlib import Path

import pytest

from api.runtime_tests.file_sync_contract import (
    file_sync_should_never_block_the_runtime,
    file_sync_should_offer_the_agents_files_before_the_runtime_starts,
    selected_image,
)


@pytest.fixture
def hermes_image() -> str:
    return selected_image("hermes")


def test_hermes_offers_its_files_before_the_runtime_starts(hermes_image: str, tmp_path: Path):
    file_sync_should_offer_the_agents_files_before_the_runtime_starts("hermes", hermes_image, tmp_path)


def test_hermes_starts_when_ingest_cannot_be_reached(hermes_image: str, tmp_path: Path):
    file_sync_should_never_block_the_runtime("hermes", hermes_image, tmp_path)

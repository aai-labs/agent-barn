from pathlib import Path

import pytest

from api.runtime_tests.file_sync_contract import (
    file_sync_should_never_block_the_runtime,
    file_sync_should_offer_the_agents_files_before_the_runtime_starts,
    selected_image,
)


@pytest.fixture
def openclaw_image() -> str:
    return selected_image("openclaw")


def test_openclaw_offers_its_files_before_the_runtime_starts(openclaw_image: str, tmp_path: Path):
    file_sync_should_offer_the_agents_files_before_the_runtime_starts("openclaw", openclaw_image, tmp_path)


def test_openclaw_starts_when_ingest_cannot_be_reached(openclaw_image: str, tmp_path: Path):
    file_sync_should_never_block_the_runtime("openclaw", openclaw_image, tmp_path)

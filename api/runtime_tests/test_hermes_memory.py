"""The real Hermes turn loop consumes Agent Barn's generated memory configuration."""

from pathlib import Path

import pytest

from api.runtime_tests.memory_contract import memory_should_start, memory_should_stop
from api.runtime_tests.memory_helpers import selected_image


@pytest.fixture
def hermes_image() -> str:
    return selected_image("hermes")


def test_hermes_should_recall_and_retain_alongside_native_memory(hermes_image: str, tmp_path: Path):
    memory_should_start("hermes", hermes_image, tmp_path)


def test_hermes_should_preserve_native_memory_when_disabled(hermes_image: str, tmp_path: Path):
    memory_should_stop("hermes", hermes_image, tmp_path)


def test_hermes_reports_permission_denied_from_its_real_terminal(hermes_image: str, tmp_path: Path):
    memory_should_start("hermes", hermes_image, tmp_path, organization_write_status=403)

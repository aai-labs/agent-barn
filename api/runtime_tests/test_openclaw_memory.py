"""The real OpenClaw loader and hooks consume Agent Barn's memory configuration."""

from pathlib import Path

import pytest

from api.runtime_tests.memory_contract import memory_should_start, memory_should_stop
from api.runtime_tests.memory_helpers import selected_image


@pytest.fixture
def openclaw_image() -> str:
    return selected_image("openclaw")


def test_openclaw_should_recall_and_retain_alongside_native_memory(openclaw_image: str, tmp_path: Path):
    memory_should_start("openclaw", openclaw_image, tmp_path)


def test_openclaw_should_preserve_native_memory_when_disabled(openclaw_image: str, tmp_path: Path):
    memory_should_stop("openclaw", openclaw_image, tmp_path)


def test_openclaw_reports_explicit_memory_search_unavailable(openclaw_image: str, tmp_path: Path):
    memory_should_start("openclaw", openclaw_image, tmp_path, explicit_recall_status=503)


def test_openclaw_reports_organization_memory_write_refusal(openclaw_image: str, tmp_path: Path):
    memory_should_start("openclaw", openclaw_image, tmp_path, organization_write_status=403)

"""The real openclaw image records Tasks through the generated agentbarn-task command."""

from pathlib import Path

from api.runtime_tests.memory_helpers import selected_image
from api.runtime_tests.task_contract import tasks_should_be_recorded_from_the_agents_shell


def test_openclaw_records_tasks_from_its_own_shell(tmp_path: Path):
    tasks_should_be_recorded_from_the_agents_shell("openclaw", selected_image("openclaw"), tmp_path)

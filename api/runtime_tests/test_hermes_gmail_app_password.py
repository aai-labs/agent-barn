from pathlib import Path

from api.runtime_tests.gmail_app_password_contract import (
    gmail_instructions_should_load_in_hermes,
    gmail_should_be_read_through_the_gateway,
)


def test_hermes_reads_gmail_through_the_gateway(tmp_path: Path):
    gmail_should_be_read_through_the_gateway("hermes", tmp_path)


def test_hermes_loads_the_gmail_instructions(tmp_path: Path):
    gmail_instructions_should_load_in_hermes(tmp_path)

from pathlib import Path

from api.runtime_tests.addons_contract import (
    a_checksum_mismatch_should_fail_the_install,
    an_add_on_should_not_replace_a_runtime_command,
    every_kind_should_install_and_be_usable,
)


def test_hermes_installs_every_kind_of_add_on_for_the_agent_user(tmp_path: Path):
    every_kind_should_install_and_be_usable("hermes", tmp_path)


def test_hermes_never_lets_an_add_on_replace_a_runtime_command(tmp_path: Path):
    an_add_on_should_not_replace_a_runtime_command("hermes", tmp_path)


def test_hermes_refuses_an_add_on_whose_checksum_does_not_match(tmp_path: Path):
    a_checksum_mismatch_should_fail_the_install("hermes", tmp_path)

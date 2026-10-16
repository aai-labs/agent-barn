from pathlib import Path

from api.runtime_tests.gmail_app_password_contract import gmail_should_be_read_through_the_gateway


def test_openclaw_reads_gmail_through_the_gateway(tmp_path: Path):
    gmail_should_be_read_through_the_gateway("openclaw", tmp_path)

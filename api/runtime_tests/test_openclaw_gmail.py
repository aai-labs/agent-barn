from pathlib import Path

from api.runtime_tests.gmail_contract import gmail_should_be_wired


def test_openclaw_gmail_profile_reaches_the_token_refresh(tmp_path: Path):
    gmail_should_be_wired("openclaw", tmp_path)

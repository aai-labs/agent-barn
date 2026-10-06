import logging

import pytest

# Importing the proxy routes installs the redaction on the access log.
from api.domains.communications import agentbarn_telegram_routes  # noqa: F401

_STAND_IN = "424242:0f3a9c1d2e4b5a6978c0d1e2f3a4b5c6d7e8f90123456789abcdef0123456789"


def test_access_logs_never_show_an_agents_stand_in_token(caplog: pytest.LogCaptureFixture) -> None:
    path = f"/communications/v1/telegram/7c1e/bot{_STAND_IN}/sendMessage"

    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "10.0.0.7:41234", "POST", path, "1.1", 200)

    assert _STAND_IN not in caplog.text
    assert "/bot<redacted>/sendMessage" in caplog.text

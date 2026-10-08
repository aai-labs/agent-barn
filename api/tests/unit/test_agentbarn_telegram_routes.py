import io
import logging

import pytest
from uvicorn.logging import AccessFormatter

# Importing the proxy routes installs the redaction on the access log.
from api.domains.communications import agentbarn_telegram_routes  # noqa: F401

_STAND_IN = "424242:0f3a9c1d2e4b5a6978c0d1e2f3a4b5c6d7e8f90123456789abcdef0123456789"


def test_access_logs_never_show_an_agents_stand_in_token(caplog: pytest.LogCaptureFixture) -> None:
    path = f"/communications/v1/telegram/7c1e/bot{_STAND_IN}/sendMessage"

    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "10.0.0.7:41234", "POST", path, "1.1", 200)

    assert _STAND_IN not in caplog.text
    assert "/bot<redacted>/sendMessage" in caplog.text


def test_a_url_encoded_stand_in_token_is_redacted_too(caplog: pytest.LogCaptureFixture) -> None:
    # Runtimes percent-encode the colon, and the access log prints the path as sent.
    encoded = _STAND_IN.replace(":", "%3A")
    path = f"/communications/v1/telegram/7c1e/bot{encoded}/getMe"

    with caplog.at_level(logging.INFO, logger="uvicorn.access"):
        logging.getLogger("uvicorn.access").info('%s - "%s %s HTTP/%s" %d', "10.0.0.7:41234", "POST", path, "1.1", 200)

    assert _STAND_IN.split(":")[1] not in caplog.text
    assert "/bot<redacted>/getMe" in caplog.text


def test_redaction_keeps_the_access_log_format_working() -> None:
    # uvicorn's AccessFormatter unpacks record.args, so redaction must keep them.
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(AccessFormatter('%(client_addr)s - "%(request_line)s" %(status_code)s', use_colors=False))
    logger = logging.getLogger("uvicorn.access")
    previous_level = logger.level
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    try:
        logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "10.0.0.7:41234",
            "POST",
            f"/communications/v1/telegram/7c1e/bot{_STAND_IN.replace(':', '%3A')}/getMe",
            "1.1",
            200,
        )
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)

    line = stream.getvalue()
    assert "/bot<redacted>/getMe" in line
    assert "200" in line
    assert _STAND_IN.split(":")[1] not in line

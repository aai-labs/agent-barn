from unittest.mock import MagicMock, patch

import httpx
import pytest

from api.infrastructure.slack import transport
from api.infrastructure.slack.transport import request_json

_URL = "https://slack.com/api/users.list"
_REQUEST = httpx.Request("GET", _URL)


def _resp(
    body: dict, *, status: int = 200, headers: dict | None = None
) -> httpx.Response:
    return httpx.Response(status, json=body, headers=headers, request=_REQUEST)


def _rate_limited(retry_after: str | None = None) -> httpx.Response:
    headers = {"Retry-After": retry_after} if retry_after is not None else None
    return _resp({}, status=429, headers=headers)


def _transport_error(
    msg: str = "peer closed connection mid-body",
) -> httpx.TransportError:
    return httpx.RemoteProtocolError(msg, request=_REQUEST)


def _mock_httpx(items: list) -> MagicMock:
    """Mock for httpx.request: each item is a Response to return or an Exception to raise."""
    return MagicMock(side_effect=list(items))


def _request() -> dict:
    return request_json("GET", _URL, headers={})


def test_returns_parsed_json_on_success():
    with patch("httpx.request", _mock_httpx([_resp({"ok": True, "value": 1})])):
        assert _request() == {"ok": True, "value": 1}


def test_429_is_retried_honoring_retry_after():
    mock = _mock_httpx([_rate_limited("5"), _resp({"ok": True})])
    with patch("httpx.request", mock), patch.object(transport.time, "sleep") as sleep:
        assert _request() == {"ok": True}

    assert mock.call_count == 2  # one retry after the 429
    sleep.assert_called_once_with(5)


def test_429_past_retry_budget_raises():
    mock = _mock_httpx([_rate_limited("1")] * 5)
    with patch("httpx.request", mock), patch.object(transport.time, "sleep"):
        with pytest.raises(httpx.HTTPStatusError):
            _request()


def test_transport_error_is_retried():
    mock = _mock_httpx([_transport_error(), _resp({"ok": True})])
    with patch("httpx.request", mock), patch.object(transport.time, "sleep") as sleep:
        assert _request() == {"ok": True}

    assert mock.call_count == 2  # one retry after the transport error
    sleep.assert_called_once()


def test_transport_error_past_retry_budget_reraises():
    mock = _mock_httpx([_transport_error()] * 5)
    with patch("httpx.request", mock), patch.object(transport.time, "sleep"):
        with pytest.raises(httpx.TransportError):
            _request()


def test_non_2xx_status_raises():
    with patch("httpx.request", _mock_httpx([_resp({}, status=500)])):
        with pytest.raises(httpx.HTTPStatusError):
            _request()


def test_uses_configured_timeout():
    mock = _mock_httpx([_resp({"ok": True})])
    cfg = MagicMock()
    cfg.slack_request_timeout_seconds = 45
    with patch.object(transport, "get_config", return_value=cfg):
        with patch("httpx.request", mock):
            _request()

    assert mock.call_args_list[0].kwargs["timeout"] == 45


def test_retry_after_seconds_clamps_and_defaults():
    assert (
        transport._retry_after_seconds(None) == transport._DEFAULT_RETRY_AFTER_SECONDS
    )
    assert (
        transport._retry_after_seconds("not-a-number")
        == transport._DEFAULT_RETRY_AFTER_SECONDS
    )
    assert transport._retry_after_seconds("0") == 1  # clamped up to the floor
    assert (
        transport._retry_after_seconds("9999")
        == transport._RATE_LIMIT_MAX_WAIT_SECONDS  # clamped down to the ceiling
    )

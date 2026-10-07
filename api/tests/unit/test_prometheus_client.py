from datetime import UTC, datetime
from unittest.mock import patch

import httpx
import pytest

from api.core.config import get_config
from api.infrastructure.prometheus.client import PrometheusClient, PrometheusError

_URL = "http://prometheus.test"
_PASSWORD = "s3cretpassw0rd"
_AT = datetime(2026, 9, 29, 12, 0, 0, tzinfo=UTC)


def _client(**overrides) -> PrometheusClient:
    settings = {
        "prometheus_url": _URL,
        "prometheus_username": "monitoring",
        "prometheus_password": _PASSWORD,
        "prometheus_timeout_seconds": 5.0,
        **overrides,
    }
    return PrometheusClient(config=get_config().model_copy(update=settings))


def _response(payload=None, *, status_code: int = 200, content: bytes | None = None) -> httpx.Response:
    request = httpx.Request("POST", f"{_URL}/api/v1/query")
    if content is not None:
        return httpx.Response(status_code, content=content, request=request)
    return httpx.Response(status_code, json=payload, request=request)


def _vector(*rows: tuple[dict, str]) -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": "vector",
            "result": [{"metric": metric, "value": [1790000000.0, value]} for metric, value in rows],
        },
    }


def _matrix(*rows: tuple[dict, list[tuple[float, str]]]) -> dict:
    return {
        "status": "success",
        "data": {
            "resultType": "matrix",
            "result": [{"metric": metric, "values": [list(pair) for pair in values]} for metric, values in rows],
        },
    }


def test_instant_query_posts_a_form_with_basic_auth_and_timeouts():
    with patch("api.infrastructure.prometheus.client.httpx.post", return_value=_response(_vector())) as post:
        _client().query("up", _AT)

    assert post.call_args.args[0] == f"{_URL}/api/v1/query"
    kwargs = post.call_args.kwargs
    assert kwargs["data"]["query"] == "up"
    assert float(kwargs["data"]["time"]) == _AT.timestamp()
    assert kwargs["data"]["timeout"] == "5s"
    assert kwargs["auth"] == ("monitoring", _PASSWORD)
    assert kwargs["timeout"] == httpx.Timeout(5.0, connect=2.0)


def test_a_trailing_slash_on_the_url_is_tolerated():
    with patch("api.infrastructure.prometheus.client.httpx.post", return_value=_response(_vector())) as post:
        _client(prometheus_url=f"{_URL}/").query("up", _AT)

    assert post.call_args.args[0] == f"{_URL}/api/v1/query"


def test_no_password_means_no_auth():
    with patch("api.infrastructure.prometheus.client.httpx.post", return_value=_response(_vector())) as post:
        _client(prometheus_password="").query("up", _AT)

    assert post.call_args.kwargs["auth"] is None


def test_instant_query_returns_labelled_samples_and_drops_values_that_are_not_numbers():
    payload = _vector(
        ({"app": "agent-1", "usage_field": "cpu_cores"}, "0.25"),
        ({"app": "agent-2", "usage_field": "cpu_cores"}, "NaN"),
        ({"app": "agent-3", "usage_field": "cpu_cores"}, "+Inf"),
        ({"app": "agent-4", "usage_field": "cpu_cores"}, "-Inf"),
    )
    with patch("api.infrastructure.prometheus.client.httpx.post", return_value=_response(payload)):
        samples = _client().query("q", _AT)

    assert [(dict(s.labels), s.value) for s in samples] == [({"app": "agent-1", "usage_field": "cpu_cores"}, 0.25)]


def test_range_query_returns_utc_points_and_leaves_gaps_for_non_numbers():
    payload = _matrix(({"app": "agent-1"}, [(1790000000.0, "1"), (1790000300.0, "NaN"), (1790000600.0, "3")]))
    with patch("api.infrastructure.prometheus.client.httpx.post", return_value=_response(payload)) as post:
        series = _client().query_range("q", _AT, _AT.replace(hour=13), 300)

    assert post.call_args.args[0] == f"{_URL}/api/v1/query_range"
    assert post.call_args.kwargs["data"]["step"] == "300"
    assert len(series) == 1
    assert dict(series[0].labels) == {"app": "agent-1"}
    assert series[0].points == (
        (datetime.fromtimestamp(1790000000.0, UTC), 1.0),
        (datetime.fromtimestamp(1790000600.0, UTC), 3.0),
    )


def test_an_unconfigured_client_reports_so_and_makes_no_request():
    client = _client(prometheus_url="  ")

    with patch("api.infrastructure.prometheus.client.httpx.post") as post:
        assert client.is_configured is False
        with pytest.raises(PrometheusError, match="not configured"):
            client.query("up", _AT)

    post.assert_not_called()


def test_a_status_error_reports_only_the_status():
    with patch("api.infrastructure.prometheus.client.httpx.post", return_value=_response({}, status_code=401)):
        with pytest.raises(PrometheusError) as raised:
            _client().query("up", _AT)

    assert "401" in str(raised.value)
    assert _URL not in str(raised.value)
    assert _PASSWORD not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__suppress_context__ is True


def test_a_transport_error_reports_only_its_kind():
    error = httpx.ConnectError(f"cannot reach {_URL} as monitoring:{_PASSWORD}")
    with patch("api.infrastructure.prometheus.client.httpx.post", side_effect=error):
        with pytest.raises(PrometheusError) as raised:
            _client().query("up", _AT)

    assert "ConnectError" in str(raised.value)
    assert _URL not in str(raised.value)
    assert _PASSWORD not in str(raised.value)


def test_a_timeout_is_an_error_not_a_hang():
    with patch("api.infrastructure.prometheus.client.httpx.post", side_effect=httpx.ReadTimeout("slow")):
        with pytest.raises(PrometheusError, match="ReadTimeout"):
            _client().query("up", _AT)


def test_a_body_that_is_not_json_is_an_error():
    with patch("api.infrastructure.prometheus.client.httpx.post", return_value=_response(content=b"<html>")):
        with pytest.raises(PrometheusError):
            _client().query("up", _AT)


def test_a_prometheus_error_body_is_an_error():
    payload = {"status": "error", "errorType": "bad_data", "error": "parse error at char 12"}
    with patch("api.infrastructure.prometheus.client.httpx.post", return_value=_response(payload)):
        with pytest.raises(PrometheusError) as raised:
            _client().query("up", _AT)

    # Prometheus echoes the query in its error text; that is not passed along.
    assert "parse error" not in str(raised.value)


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "success", "data": {"result": [{"nope": 1}]}},
        {"status": "success", "data": {"result": [{"metric": {}, "value": []}]}},
        {"status": "success", "data": {"result": "not a list"}},
        {"status": "success", "data": []},
        [],
    ],
)
def test_an_unexpected_shape_is_an_error(payload):
    with patch("api.infrastructure.prometheus.client.httpx.post", return_value=_response(payload)):
        with pytest.raises(PrometheusError, match="unexpected|error"):
            _client().query("up", _AT)

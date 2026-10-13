import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
from injector import inject, singleton

from api.core.config import Config

_CONNECT_TIMEOUT_SECONDS = 2.0


class PrometheusError(Exception):
    """Prometheus could not answer. The message never carries the URL or credentials."""


@dataclass(frozen=True)
class PrometheusSample:
    labels: Mapping[str, str]
    value: float


@dataclass(frozen=True)
class PrometheusSeries:
    labels: Mapping[str, str]
    points: tuple[tuple[datetime, float], ...]


def _finite(raw: object) -> float | None:
    """Prometheus writes NaN and ±Inf as strings; a value that is not a real number is a
    missing value, not a reading."""
    value = float(str(raw))
    return value if math.isfinite(value) else None


@inject
@dataclass
@singleton
class PrometheusClient:
    """Read-only client for the in-namespace Prometheus (the monitoring chart)."""

    config: Config

    @property
    def is_configured(self) -> bool:
        return bool(self.config.prometheus_url.strip())

    def query(self, promql: str, at: datetime) -> list[PrometheusSample]:
        """Instant query at one moment. Samples whose value is not finite are dropped."""
        data = self._post("/api/v1/query", {"query": promql, "time": f"{at.timestamp():.3f}"})
        try:
            samples = []
            for item in data["result"]:
                value = _finite(item["value"][1])
                if value is not None:
                    samples.append(PrometheusSample(labels=dict(item["metric"]), value=value))
            return samples
        except KeyError, IndexError, TypeError, ValueError:
            raise PrometheusError("Prometheus returned an unexpected response") from None

    def query_range(self, promql: str, start: datetime, end: datetime, step_seconds: int) -> list[PrometheusSeries]:
        """Range query. Points whose value is not finite are dropped, so they show as gaps."""
        data = self._post(
            "/api/v1/query_range",
            {
                "query": promql,
                "start": f"{start.timestamp():.3f}",
                "end": f"{end.timestamp():.3f}",
                "step": str(step_seconds),
            },
        )
        try:
            series = []
            for item in data["result"]:
                points = []
                for timestamp, raw in item["values"]:
                    value = _finite(raw)
                    if value is not None:
                        points.append((datetime.fromtimestamp(float(timestamp), UTC), value))
                series.append(PrometheusSeries(labels=dict(item["metric"]), points=tuple(points)))
            return series
        except KeyError, IndexError, TypeError, ValueError:
            raise PrometheusError("Prometheus returned an unexpected response") from None

    def _post(self, path: str, form: dict[str, str]) -> dict:
        # A form body keeps long selectors out of URLs and access logs.
        if not self.is_configured:
            raise PrometheusError("Prometheus is not configured")
        config = self.config
        timeout = config.prometheus_timeout_seconds
        auth = (config.prometheus_username, config.prometheus_password) if config.prometheus_password else None
        try:
            response = httpx.post(
                f"{config.prometheus_url.strip().rstrip('/')}{path}",
                data={**form, "timeout": f"{max(int(timeout), 1)}s"},
                auth=auth,
                timeout=httpx.Timeout(timeout, connect=min(_CONNECT_TIMEOUT_SECONDS, timeout)),
            )
            response.raise_for_status()
            body = response.json()
        except httpx.HTTPStatusError as exc:
            # Only the status: httpx's own message repeats the request URL.
            raise PrometheusError(f"Prometheus answered {exc.response.status_code}") from None
        except (httpx.HTTPError, ValueError) as exc:
            raise PrometheusError(f"Prometheus request failed: {type(exc).__name__}") from None
        if not isinstance(body, dict) or body.get("status") != "success" or not isinstance(body.get("data"), dict):
            raise PrometheusError("Prometheus returned an error")
        return body["data"]

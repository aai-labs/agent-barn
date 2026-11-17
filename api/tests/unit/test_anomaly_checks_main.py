"""The anomaly-checks Job entrypoint.

One Agent failing is logged by the check and retried by the next scheduled run, so the
Job succeeds: a failed Job would be restarted and check every other Agent again.
"""

import sys
from dataclasses import dataclass

import pytest
from hamcrest import assert_that, equal_to

from api.domains.anomalies import checks
from api.domains.anomalies.service import CheckSummary


@dataclass
class _Service:
    summary: CheckSummary
    runs: int = 0

    def run_checks(self) -> CheckSummary:
        self.runs += 1
        return self.summary


@dataclass
class _Injector:
    service: _Service

    def get(self, _cls):
        return self.service


def _run(monkeypatch: pytest.MonkeyPatch, summary: CheckSummary) -> _Service:
    service = _Service(summary)
    monkeypatch.setattr(checks, "create_injector", lambda: _Injector(service))
    monkeypatch.setattr(sys, "argv", ["checks"])
    checks.main()
    return service


def test_a_run_where_some_agents_failed_still_succeeds(monkeypatch: pytest.MonkeyPatch):
    service = _run(monkeypatch, CheckSummary(organizations=1, agents=3, failures=1))

    assert_that(service.runs, equal_to(1))


def test_a_run_that_cannot_check_at_all_fails(monkeypatch: pytest.MonkeyPatch):
    class _Broken(_Service):
        def run_checks(self) -> CheckSummary:
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(checks, "create_injector", lambda: _Injector(_Broken(CheckSummary(0, 0, 0))))
    monkeypatch.setattr(sys, "argv", ["checks"])

    with pytest.raises(RuntimeError):
        checks.main()

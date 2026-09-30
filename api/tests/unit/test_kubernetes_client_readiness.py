from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from api.infrastructure.kubernetes.client import KubernetesClient

_DEPLOYMENT = "agent-01a0c443-98ce-751c-be8d-a8df0a249ed0"
_NAMESPACE = "agent-farm"
_OLDER = datetime(2026, 9, 21, 14, 0, 0, tzinfo=UTC)
_NEWER = _OLDER + timedelta(minutes=5)


def _terminated_status(reason=None, exit_code=None):
    return SimpleNamespace(state=SimpleNamespace(terminated=SimpleNamespace(reason=reason, exit_code=exit_code)))


def _waiting_status(reason):
    return SimpleNamespace(state=SimpleNamespace(terminated=None, waiting=SimpleNamespace(reason=reason)))


def _pod(name, phase, *, created, deleting=False, ready=False, container_statuses=None):
    conditions = [SimpleNamespace(type="Ready", status="True" if ready else "False")]
    return SimpleNamespace(
        metadata=SimpleNamespace(
            name=name,
            creation_timestamp=created,
            deletion_timestamp=datetime(2026, 9, 21, 14, 17, 35, tzinfo=UTC) if deleting else None,
        ),
        status=SimpleNamespace(phase=phase, conditions=conditions, container_statuses=container_statuses),
    )


def _client_listing(*pods):
    k8s = KubernetesClient(config=MagicMock())
    core_v1 = MagicMock()
    core_v1.list_namespaced_pod.return_value = SimpleNamespace(items=list(pods))
    k8s._core_v1 = core_v1
    return k8s


def _readiness(*pods):
    return _client_listing(*pods).get_pod_readiness(_DEPLOYMENT, _NAMESPACE)


def test_terminating_failed_pod_is_ignored_while_the_replacement_starts():
    old = _pod(
        "agent-xlhzs", "Failed", created=_OLDER, deleting=True, container_statuses=[_terminated_status("Error", 143)]
    )
    new = _pod("agent-hw5pl", "Pending", created=_NEWER, container_statuses=[_waiting_status("PodInitializing")])

    assert _readiness(old, new) == ("initializing", None)


def test_terminating_failed_pod_is_ignored_whatever_the_list_order():
    old = _pod(
        "agent-aaaaa", "Failed", created=_OLDER, deleting=True, container_statuses=[_terminated_status("Error", 143)]
    )
    new = _pod("agent-zzzzz", "Pending", created=_NEWER, container_statuses=[_waiting_status("PodInitializing")])

    assert _readiness(old, new) == ("initializing", None)
    assert _readiness(new, old) == ("initializing", None)


def test_terminating_pod_does_not_report_ready_while_the_replacement_boots():
    old = _pod("agent-old", "Running", created=_OLDER, deleting=True, ready=True)
    new = _pod("agent-new", "Pending", created=_NEWER, container_statuses=[_waiting_status("PodInitializing")])

    assert _readiness(old, new) == ("initializing", None)


def test_ready_replacement_reports_ready_beside_a_terminating_pod():
    old = _pod(
        "agent-old", "Failed", created=_OLDER, deleting=True, container_statuses=[_terminated_status("Error", 143)]
    )
    new = _pod("agent-new", "Running", created=_NEWER, ready=True)

    assert _readiness(old, new) == ("ready", None)


def test_only_a_terminating_pod_reports_nothing():
    old = _pod(
        "agent-old", "Failed", created=_OLDER, deleting=True, container_statuses=[_terminated_status("Error", 143)]
    )

    assert _readiness(old) == (None, None)


def test_crash_looping_pod_still_reports_crashed():
    pod = _pod("agent-new", "Running", created=_NEWER, container_statuses=[_waiting_status("CrashLoopBackOff")])

    assert _readiness(pod) == ("crashed", "CrashLoopBackOff")


def test_failed_pod_that_is_not_terminating_still_reports_crashed():
    pod = _pod("agent-new", "Failed", created=_NEWER, container_statuses=[_terminated_status(None, 137)])

    assert _readiness(pod) == ("crashed", "exit code 137")


def test_ready_pod_reports_ready():
    pod = _pod("agent-new", "Running", created=_NEWER, ready=True)

    assert _readiness(pod) == ("ready", None)


def test_no_pods_reports_nothing():
    assert _readiness() == (None, None)


def test_pod_in_an_indeterminate_phase_reports_nothing_rather_than_crashed():
    pod = _pod("agent-new", "Unknown", created=_NEWER)

    assert _readiness(pod) == (None, None)


def test_newest_pod_wins_when_several_are_alive():
    older = _pod("agent-older", "Running", created=_OLDER, container_statuses=[_waiting_status("CrashLoopBackOff")])
    newer = _pod("agent-newer", "Running", created=_NEWER, ready=True)

    assert _readiness(older, newer) == ("ready", None)

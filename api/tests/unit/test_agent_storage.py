"""An Agent Size's storage: the volume a new Agent gets, how an older one grows, when it is
pending, and how large a restore point's archive volume is."""

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import uuid7

import pytest
from hamcrest import assert_that, equal_to, none
from kubernetes.client.exceptions import ApiException

from api.domains.agent_sizes.models import (
    GIB,
    MIB,
    STANDARD_STORAGE_BYTES,
    AgentSize,
    running_snapshot,
    size_is_pending,
)
from api.domains.agents.builders.common import build_pvc, pvc_storage_bytes, storage_quantity
from api.domains.agents.service import AgentService
from api.domains.restore_points.service import RestorePointService


def _size(storage_bytes: int, *, memory_limit_bytes: int = 1 * GIB) -> AgentSize:
    return AgentSize(
        id=uuid7(),
        name="Size",
        cpu_request_millicores=50,
        cpu_limit_millicores=500,
        memory_request_bytes=320 * MIB,
        memory_limit_bytes=memory_limit_bytes,
        storage_bytes=storage_bytes,
    )


def _pvc(storage_bytes: int):
    return build_pvc(uuid7(), uuid7(), "agent-farm", storage_bytes=storage_bytes)


# --- the volume ------------------------------------------------------------------


def test_a_standard_volume_is_written_exactly_as_before():
    assert_that(_pvc(STANDARD_STORAGE_BYTES).spec.resources.requests, equal_to({"storage": "1Gi"}))


@pytest.mark.parametrize(("storage", "expected"), [(10 * GIB, "10Gi"), (1536 * MIB, "1536Mi")])
def test_storage_is_written_in_gi_or_mi(storage: int, expected: str):
    assert_that(storage_quantity(storage), equal_to(expected))
    assert_that(_pvc(storage).spec.resources.requests, equal_to({"storage": expected}))


def test_a_volume_reads_back_its_request_and_anything_else_reads_as_unknown():
    assert_that(pvc_storage_bytes(_pvc(10 * GIB)), equal_to(10 * GIB))
    assert_that(pvc_storage_bytes(MagicMock()), none())
    assert_that(pvc_storage_bytes(None), none())


# --- growing an existing volume ---------------------------------------------------


def _ensure(pvc, storage_bytes: int, k8s: MagicMock) -> int:
    service = cast(Any, SimpleNamespace(k8s=k8s))
    return AgentService._ensure_volume(service, pvc, "agent-x", "agent-farm", storage_bytes)


def test_a_smaller_volume_grows_to_its_size():
    k8s = MagicMock()

    volume = _ensure(_pvc(1 * GIB), 10 * GIB, k8s)

    assert_that(volume, equal_to(10 * GIB))
    k8s.patch_pvc_storage.assert_called_once_with("agent-x", "agent-farm", "10Gi")


def test_a_volume_at_or_above_its_size_is_left_alone():
    k8s = MagicMock()

    assert_that(_ensure(_pvc(10 * GIB), 10 * GIB, k8s), equal_to(10 * GIB))
    assert_that(_ensure(_pvc(20 * GIB), 10 * GIB, k8s), equal_to(20 * GIB))
    k8s.patch_pvc_storage.assert_not_called()


def test_a_volume_the_cluster_cannot_grow_keeps_its_size_and_the_agent_still_starts():
    k8s = MagicMock()
    k8s.patch_pvc_storage.side_effect = ApiException(status=403, reason="Forbidden")

    assert_that(_ensure(_pvc(1 * GIB), 10 * GIB, k8s), equal_to(1 * GIB))


# --- pending ----------------------------------------------------------------------


def test_a_record_from_before_storage_is_read_as_the_1gi_every_volume_had():
    legacy = {key: value for key, value in running_snapshot(_size(GIB), GIB).items() if key != "storage_bytes"}

    assert_that(size_is_pending(legacy, _size(1 * GIB)), equal_to(False))
    assert_that(size_is_pending(legacy, _size(10 * GIB)), equal_to(True))


def test_more_storage_than_the_volume_has_is_pending_and_less_never_is():
    running = running_snapshot(_size(10 * GIB), 10 * GIB)

    assert_that(size_is_pending(running, _size(20 * GIB)), equal_to(True))
    assert_that(size_is_pending(running, _size(5 * GIB)), equal_to(False))
    assert_that(size_is_pending(running, _size(10 * GIB)), equal_to(False))


def test_cpu_and_memory_still_decide_pending_on_their_own():
    running = running_snapshot(_size(GIB), GIB)

    assert_that(size_is_pending(running, _size(GIB, memory_limit_bytes=4 * GIB)), equal_to(True))


# --- restore points ---------------------------------------------------------------


def _archive_size(agent_volume, floor: str = "1Gi") -> str:
    k8s = MagicMock()
    k8s.get_pvc.return_value = agent_volume
    service = cast(
        Any, SimpleNamespace(k8s=k8s, config=SimpleNamespace(restore_point_size=floor, k8s_namespace="agent-farm"))
    )
    return RestorePointService._archive_size(service, cast(Any, SimpleNamespace(id=uuid7())))


def test_a_restore_points_volume_follows_the_agents_volume():
    assert_that(_archive_size(_pvc(10 * GIB)), equal_to("10Gi"))


def test_a_restore_points_volume_is_never_below_the_configured_size():
    assert_that(_archive_size(_pvc(1 * GIB), floor="2Gi"), equal_to("2Gi"))
    assert_that(_archive_size(None), equal_to("1Gi"))

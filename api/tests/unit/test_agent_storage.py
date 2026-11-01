"""An Agent Size's storage: the volume a new Agent gets, how an older one grows, when it is
pending, and how large a restore point's archive volume is."""

import json
import os
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock
from uuid import uuid7

import pytest
from hamcrest import assert_that, equal_to, none
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from api.domains.agent_sizes.models import (
    GIB,
    MIB,
    STANDARD_STORAGE_BYTES,
    AgentSize,
    running_snapshot,
    size_is_pending,
)
from api.domains.agents.builders.common import build_pvc, pvc_capacity_bytes, pvc_storage_bytes, storage_quantity
from api.domains.agents.restore_point_job import capture
from api.domains.agents.service import AgentService
from api.domains.restore_points.constants import RESTORE_POINT_ARCHIVE_MARGIN_PERCENT
from api.domains.restore_points.service import RestorePointService, archive_volume_bytes
from api.infrastructure.kubernetes.client import KubernetesClient, VolumeExpansionUnsupported


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


def _bound(request: int, capacity: int):
    """A volume Kubernetes has bound, whose capacity can trail its request while it grows."""
    pvc = _pvc(request)
    pvc.status = client.V1PersistentVolumeClaimStatus(capacity={"storage": storage_quantity(capacity)})
    return pvc


def _ensure(pvc, storage_bytes: int, k8s: MagicMock) -> int:
    service = cast(Any, SimpleNamespace(k8s=k8s))
    return AgentService._ensure_volume(service, pvc, "agent-x", "agent-farm", storage_bytes)


def test_a_volume_reads_back_its_capacity_only_once_bound():
    assert_that(pvc_capacity_bytes(_bound(10 * GIB, 1 * GIB)), equal_to(1 * GIB))
    assert_that(pvc_capacity_bytes(_pvc(10 * GIB)), none())
    assert_that(pvc_capacity_bytes(MagicMock()), none())


def test_a_new_claim_is_provisioned_at_its_request():
    k8s = MagicMock()

    assert_that(_ensure(_pvc(10 * GIB), 10 * GIB, k8s), equal_to(10 * GIB))
    k8s.patch_pvc_storage.assert_not_called()


def test_a_smaller_volume_is_asked_to_grow_but_counts_as_its_capacity_until_it_has():
    """Kubernetes grows a volume asynchronously and may still fail, so the request is not the size."""
    k8s = MagicMock()

    volume = _ensure(_bound(1 * GIB, 1 * GIB), 10 * GIB, k8s)

    k8s.patch_pvc_storage.assert_called_once_with("agent-x", "agent-farm", "10Gi")
    assert_that(volume, equal_to(1 * GIB))


def test_a_grown_volume_counts_as_its_new_capacity_and_is_not_patched_again():
    k8s = MagicMock()

    assert_that(_ensure(_bound(10 * GIB, 10 * GIB), 10 * GIB, k8s), equal_to(10 * GIB))
    k8s.patch_pvc_storage.assert_not_called()


def test_a_volume_above_its_size_is_left_alone():
    k8s = MagicMock()

    assert_that(_ensure(_bound(20 * GIB, 20 * GIB), 10 * GIB, k8s), equal_to(20 * GIB))
    k8s.patch_pvc_storage.assert_not_called()


def test_a_volume_whose_storage_class_cannot_grow_counts_as_the_sizes_storage():
    # local-path refuses every resize and does not enforce a claim's size either.
    k8s = MagicMock()
    k8s.patch_pvc_storage.side_effect = VolumeExpansionUnsupported("agent-x")

    assert_that(_ensure(_bound(1 * GIB, 1 * GIB), 10 * GIB, k8s), equal_to(10 * GIB))


def test_any_other_refusal_keeps_the_volume_at_its_capacity_and_the_agent_still_starts():
    k8s = MagicMock()
    k8s.patch_pvc_storage.side_effect = ApiException(status=403, reason="Forbidden")

    assert_that(_ensure(_bound(1 * GIB, 1 * GIB), 10 * GIB, k8s), equal_to(1 * GIB))


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


@pytest.mark.parametrize(
    ("volume", "archive"),
    [(1 * GIB, "1792Mi"), (2 * GIB, "2816Mi"), (10 * GIB, "11776Mi"), (100 * GIB, "113152Mi")],
)
def test_a_restore_points_volume_is_the_agents_volume_and_a_margin(volume: int, archive: str):
    # A tenth more and 512Mi, rounded up to 256Mi: 1Gi -> 1.75Gi, 10Gi -> 11.5Gi.
    assert_that(_archive_size(_pvc(volume)), equal_to(archive))


def test_a_restore_points_volume_follows_what_the_agents_volume_has_when_it_is_larger():
    assert_that(_archive_size(_bound(1 * GIB, 10 * GIB)), equal_to("11776Mi"))


def test_a_restore_points_volume_is_never_below_the_configured_size():
    assert_that(_archive_size(_pvc(1 * GIB), floor="2Gi"), equal_to("2Gi"))
    assert_that(_archive_size(None), equal_to("1Gi"))


def test_an_archive_of_a_full_volume_of_incompressible_data_fits_the_margin(tmp_path):
    # The worst case for the archive format: random data, much of it in files of one 4KiB
    # block, where tar's per-file header and padding weigh most.
    source = tmp_path / "volume"
    for directory in range(20):
        (source / "workspace" / f"d{directory}").mkdir(parents=True)
        for index in range(100):
            (source / "workspace" / f"d{directory}" / f"f{index}.bin").write_bytes(os.urandom(4096))
    (source / "workspace" / "large.bin").write_bytes(os.urandom(8 * MIB))
    files = [path for path in source.rglob("*") if path.is_file()]
    data = sum(path.stat().st_size for path in files)
    # What the files take on the Agent's volume: whole 4KiB blocks, and one per directory.
    used = sum(-(-path.stat().st_size // 4096) * 4096 for path in files)
    used += 4096 * sum(1 for path in source.rglob("*") if path.is_dir())
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()

    manifest = capture(source, archive_dir, "openclaw")

    # The archive outgrows the data it holds, so a volume only as large as the Agent's would not do.
    assert_that(manifest["bytes"] > data, equal_to(True))
    # The format's overhead, with the archive volume's own filesystem (inode tables, about
    # 1.6% on ext4), stays inside the proportional part of the margin.
    overhead = manifest["bytes"] / used - 1
    assert_that(overhead + 0.016 < RESTORE_POINT_ARCHIVE_MARGIN_PERCENT / 100, equal_to(True))
    assert_that(archive_volume_bytes(used) >= manifest["bytes"] * 1.016, equal_to(True))


# --- the client --------------------------------------------------------------------


def _client_refusing(status: int, message: str):
    k8s = KubernetesClient(config=MagicMock())
    core_v1 = MagicMock()
    error = ApiException(status=status, reason="Forbidden")
    error.body = json.dumps({"kind": "Status", "message": message})
    core_v1.patch_namespaced_persistent_volume_claim.side_effect = error
    cast(Any, k8s)._core_v1 = core_v1
    return k8s


def test_a_storage_class_that_cannot_resize_is_told_apart_from_other_refusals():
    # The API server's own wording, as staging's local-path claims get it.
    unsupported = _client_refusing(
        403,
        'persistentvolumeclaims "agent-x" is forbidden: only dynamically provisioned pvc can be resized '
        "and the storageclass that provisions the pvc must support resize",
    )
    with pytest.raises(VolumeExpansionUnsupported):
        unsupported.patch_pvc_storage("agent-x", "agent-farm", "10Gi")

    quota = _client_refusing(403, "exceeded quota: storage, requested: requests.storage=9Gi")
    with pytest.raises(ApiException):
        quota.patch_pvc_storage("agent-x", "agent-farm", "10Gi")

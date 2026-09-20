from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

from hamcrest import assert_that, contains_string, empty, equal_to, has_length, is_not

from api.domains.agents.builders.restore_point import RESTORE_POINT_ID_LABEL_KEY
from api.domains.restore_points.constants import (
    RESTORE_POINT_ORPHAN_DELETE_LIMIT,
    RESTORE_POINT_ORPHAN_MIN_AGE_SECONDS,
    RESTORE_POINT_RECONCILIATION_BATCH_SIZE,
    RESTORE_POINT_RECONCILIATION_STALE_SECONDS,
)
from api.domains.restore_points.reconciliation import (
    RESTORE_POINT_SELECTOR,
    RestorePointReconciler,
)

_NAMESPACE = "agent-farm"
_OLD = datetime.now(UTC) - timedelta(seconds=RESTORE_POINT_ORPHAN_MIN_AGE_SECONDS * 2)
_RECENT = datetime.now(UTC)


class FakeRow:
    def __init__(self, *, status="PENDING", reapply_configuration=False, pvc_name=None):
        self.id = uuid4()
        self.status = status
        self.reapply_configuration = reapply_configuration
        self.pvc_name = pvc_name or f"restore-point-{self.id}"


class FakeRepository:
    def __init__(self, *, candidates=None, missing=None, existing_ids=None):
        self.candidates = candidates or []
        self.missing = missing or []
        self.existing_ids = existing_ids if existing_ids is not None else set()
        self.claim_args: dict | None = None
        self.missing_args: tuple | None = None
        self.failed: list[tuple[UUID, str]] = []

    def claim_reconciliation_candidates(self, *, stale_before, limit, skip_locked=True):
        self.claim_args = {"stale_before": stale_before, "limit": limit, "skip_locked": skip_locked}
        return self.candidates[:limit]

    def find_ready_rows_missing_volumes(self, live_pvc_names, limit):
        self.missing_args = (set(live_pvc_names), limit)
        return self.missing[:limit]

    def find_existing_ids(self, restore_point_ids):
        return {found for found in restore_point_ids if found in self.existing_ids}

    def mark_ready_row_failed(self, restore_point_id, reason):
        self.failed.append((restore_point_id, reason))
        return True


class FakeService:
    def __init__(self, *, reconcile_error_for=None, replay_error_for=None):
        self.reconcile_error_for = reconcile_error_for
        self.replay_error_for = replay_error_for
        self.reconciled: list[tuple[UUID, bool]] = []
        self.replayed: list[UUID] = []

    def reconcile_row(self, row, *, respect_grace=True):
        if row.id == self.reconcile_error_for:
            raise RuntimeError("cluster unavailable")
        self.reconciled.append((row.id, respect_grace))

    def apply_owed_replay(self, row):
        if row.id == self.replay_error_for:
            raise RuntimeError("template gone")
        self.replayed.append(row.id)


class FakeCluster:
    def __init__(self, *, pvcs=None, jobs=None, list_error=False):
        self.pvcs = pvcs or []
        self.jobs = jobs or []
        self.list_error = list_error
        self.deleted_pvcs: list[str] = []
        self.deleted_jobs: list[str] = []
        self.deletions: list[str] = []
        self.selectors: list[str] = []

    def list_pvcs(self, namespace, label_selector=""):
        if self.list_error:
            raise RuntimeError("api server unreachable")
        self.selectors.append(label_selector)
        return self.pvcs

    def list_jobs(self, namespace, label_selector=""):
        if self.list_error:
            raise RuntimeError("api server unreachable")
        self.selectors.append(label_selector)
        return self.jobs

    def delete_pvc(self, name, namespace):
        self.deleted_pvcs.append(name)
        self.deletions.append(f"pvc:{name}")

    def delete_job(self, name, namespace):
        self.deleted_jobs.append(name)
        self.deletions.append(f"job:{name}")


def _resource(name, restore_point_id=None, created=_OLD, labelled=True):
    labels = {"agentbarn.io/component": "restore-point"}
    if labelled:
        labels[RESTORE_POINT_ID_LABEL_KEY] = str(restore_point_id or uuid4())
    return SimpleNamespace(metadata=SimpleNamespace(name=name, labels=labels, creation_timestamp=created))


def _reconciler(repository=None, service=None, cluster=None):
    return RestorePointReconciler(
        repository=repository or FakeRepository(),
        service=service or FakeService(),
        k8s=cluster or FakeCluster(),
        namespace=_NAMESPACE,
    )


def test_claimed_rows_are_resolved_without_the_read_paths_grace_window():
    rows = [FakeRow(), FakeRow()]
    repository = FakeRepository(candidates=rows)
    service = FakeService()

    result = _reconciler(repository, service).run_once()

    assert_that(result.claimed, equal_to(2))
    assert_that(result.resolved, equal_to(2))
    assert_that(service.reconciled, equal_to([(rows[0].id, False), (rows[1].id, False)]))


def test_the_claim_asks_for_rows_stale_past_the_threshold_and_is_bounded():
    repository = FakeRepository(candidates=[FakeRow() for _ in range(RESTORE_POINT_RECONCILIATION_BATCH_SIZE + 5)])

    result = _reconciler(repository).run_once()

    assert_that(result.claimed, equal_to(RESTORE_POINT_RECONCILIATION_BATCH_SIZE))
    assert repository.claim_args is not None
    assert_that(repository.claim_args["limit"], equal_to(RESTORE_POINT_RECONCILIATION_BATCH_SIZE))
    assert_that(
        datetime.now(UTC) - repository.claim_args["stale_before"]
        >= timedelta(seconds=RESTORE_POINT_RECONCILIATION_STALE_SECONDS - 1),
        equal_to(True),
    )


def test_a_row_that_owes_a_replay_is_resolved_and_then_replayed():
    owing = FakeRow(status="READY", reapply_configuration=True)
    settled = FakeRow()
    service = FakeService()

    result = _reconciler(FakeRepository(candidates=[owing, settled]), service).run_once()

    assert_that(service.replayed, equal_to([owing.id]))
    assert_that(result.replays_attempted, equal_to(1))


def test_one_row_failing_does_not_stop_the_rest_of_the_batch():
    broken = FakeRow()
    healthy = FakeRow()
    service = FakeService(reconcile_error_for=broken.id)

    result = _reconciler(FakeRepository(candidates=[broken, healthy]), service).run_once()

    assert_that(result.resolved, equal_to(1))
    assert_that(result.failed, equal_to(1))
    assert_that(service.reconciled, equal_to([(healthy.id, False)]))


def test_a_failing_replay_is_counted_without_losing_the_resolution():
    owing = FakeRow(status="READY", reapply_configuration=True)
    service = FakeService(replay_error_for=owing.id)

    result = _reconciler(FakeRepository(candidates=[owing]), service).run_once()

    assert_that(result.resolved, equal_to(1))
    assert_that(result.replays_attempted, equal_to(0))
    assert_that(result.failed, equal_to(1))


def test_ready_rows_whose_volume_is_gone_are_failed():
    stranded = FakeRow(status="READY", pvc_name="restore-point-gone")
    repository = FakeRepository(missing=[stranded])
    cluster = FakeCluster(pvcs=[_resource("restore-point-live")])

    result = _reconciler(repository, cluster=cluster).run_once()

    assert_that(result.volumes_missing, equal_to(1))
    assert_that(repository.failed, has_length(1))
    assert_that(repository.failed[0][0], equal_to(stranded.id))
    assert_that(repository.failed[0][1], contains_string("restore-point-gone"))


def test_an_empty_volume_listing_never_fails_a_row():
    repository = FakeRepository(missing=[FakeRow(status="READY")])

    result = _reconciler(repository, cluster=FakeCluster(pvcs=[], jobs=[])).run_once()

    assert_that(result.volumes_missing, equal_to(0))
    assert_that(repository.failed, empty())
    assert_that(repository.missing_args, equal_to(None))


def test_a_failed_listing_skips_both_cluster_passes():
    repository = FakeRepository(missing=[FakeRow(status="READY")])
    cluster = FakeCluster(list_error=True)

    result = _reconciler(repository, cluster=cluster).run_once()

    assert_that(repository.failed, empty())
    assert_that(cluster.deleted_pvcs, empty())
    assert_that(cluster.deleted_jobs, empty())
    assert_that(result.orphans_deleted, equal_to(0))


def test_resources_no_row_owns_are_reclaimed_and_owned_ones_are_left_alone():
    owned_id, orphan_id = uuid4(), uuid4()
    cluster = FakeCluster(
        pvcs=[_resource("restore-point-owned", owned_id), _resource("restore-point-orphan", orphan_id)],
        jobs=[_resource("rp-cap-orphan", orphan_id)],
    )
    repository = FakeRepository(existing_ids={owned_id})

    result = _reconciler(repository, cluster=cluster).run_once()

    assert_that(result.orphans_deleted, equal_to(2))
    assert_that(cluster.deleted_jobs, equal_to(["rp-cap-orphan"]))
    assert_that(cluster.deleted_pvcs, equal_to(["restore-point-orphan"]))


def test_jobs_are_deleted_before_volumes_so_no_pod_still_holds_one():
    orphan_id = uuid4()
    cluster = FakeCluster(
        pvcs=[_resource("restore-point-orphan", orphan_id)],
        jobs=[_resource("rp-cap-orphan", orphan_id)],
    )

    _reconciler(FakeRepository(), cluster=cluster).run_once()

    assert_that(cluster.deletions, equal_to(["job:rp-cap-orphan", "pvc:restore-point-orphan"]))


def test_a_resource_younger_than_the_minimum_age_is_left_alone():
    cluster = FakeCluster(pvcs=[_resource("restore-point-new", created=_RECENT)])

    result = _reconciler(FakeRepository(), cluster=cluster).run_once()

    assert_that(result.orphans_deleted, equal_to(0))
    assert_that(cluster.deleted_pvcs, empty())


def test_an_unlabelled_resource_is_reported_and_never_deleted():
    cluster = FakeCluster(pvcs=[_resource("restore-point-legacy", labelled=False)])

    result = _reconciler(FakeRepository(), cluster=cluster).run_once()

    assert_that(result.orphans_unidentified, equal_to(1))
    assert_that(result.orphans_deleted, equal_to(0))
    assert_that(cluster.deleted_pvcs, empty())


def test_deletions_are_capped_per_run():
    cluster = FakeCluster(
        pvcs=[_resource(f"restore-point-{index}") for index in range(RESTORE_POINT_ORPHAN_DELETE_LIMIT + 5)]
    )

    result = _reconciler(FakeRepository(), cluster=cluster).run_once()

    assert_that(result.orphans_deleted, equal_to(RESTORE_POINT_ORPHAN_DELETE_LIMIT))
    assert_that(cluster.deleted_pvcs, has_length(RESTORE_POINT_ORPHAN_DELETE_LIMIT))


def test_the_runtime_bound_stops_the_passes_early():
    rows = [FakeRow() for _ in range(5)]
    cluster = FakeCluster(pvcs=[_resource("restore-point-orphan")])
    service = FakeService()

    with patch("api.domains.restore_points.reconciliation.time.monotonic", side_effect=[0] + [10_000] * 40):
        result = _reconciler(FakeRepository(candidates=rows), service, cluster).run_once()

    assert_that(service.reconciled, empty())
    assert_that(cluster.deleted_pvcs, empty())
    assert_that(result.claimed, equal_to(5))


def test_both_listings_are_narrowed_to_restore_point_resources():
    cluster = FakeCluster()

    _reconciler(cluster=cluster).run_once()

    assert_that(cluster.selectors, equal_to([RESTORE_POINT_SELECTOR, RESTORE_POINT_SELECTOR]))
    assert_that(RESTORE_POINT_SELECTOR, is_not(empty()))


def test_every_run_logs_a_summary():
    with patch("api.domains.restore_points.reconciliation.logger") as mock_logger:
        _reconciler().run_once()

    assert_that(mock_logger.info.call_count, equal_to(1))
    assert_that(mock_logger.info.call_args[0][0], contains_string("reconciliation summary"))


def test_one_malformed_resource_does_not_abort_the_sweep():
    orphan_id = uuid4()
    broken = _resource("restore-point-broken", created=1)
    cluster = FakeCluster(pvcs=[broken, _resource("restore-point-orphan", orphan_id)])

    result = _reconciler(FakeRepository(), cluster=cluster).run_once()

    assert_that(result.failed, equal_to(1))
    assert_that(result.orphans_deleted, equal_to(1))
    assert_that(cluster.deleted_pvcs, equal_to(["restore-point-orphan"]))

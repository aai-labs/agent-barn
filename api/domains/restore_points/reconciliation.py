import argparse
import logging
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID

from api.domains.agents.builders.restore_point import (
    COMPONENT_LABEL,
    COMPONENT_LABEL_KEY,
    RESTORE_POINT_ID_LABEL_KEY,
)
from api.domains.agents.models import AgentRestorePoint
from api.domains.restore_points.constants import (
    RESTORE_POINT_ORPHAN_DELETE_LIMIT,
    RESTORE_POINT_ORPHAN_MIN_AGE_SECONDS,
    RESTORE_POINT_RECONCILIATION_BATCH_SIZE,
    RESTORE_POINT_RECONCILIATION_MAX_RUNTIME_SECONDS,
    RESTORE_POINT_RECONCILIATION_MISSING_VOLUME_LIMIT,
    RESTORE_POINT_RECONCILIATION_STALE_SECONDS,
)

logger = logging.getLogger(__name__)

RESTORE_POINT_SELECTOR = f"{COMPONENT_LABEL_KEY}={COMPONENT_LABEL}"

_MISSING_VOLUME_REASON = "The archive volume {name} is no longer in the cluster, so this restore point cannot be used."


@dataclass(frozen=True)
class RestorePointReconciliationResult:
    claimed: int = 0
    resolved: int = 0
    replays_attempted: int = 0
    volumes_missing: int = 0
    orphans_deleted: int = 0
    orphans_unidentified: int = 0
    failed: int = 0


@dataclass(frozen=True)
class _ClusterObjects:
    pvcs: list[Any]
    jobs: list[Any]


class RestorePointReconciliationRepository(Protocol):
    def claim_reconciliation_candidates(
        self,
        *,
        stale_before: datetime,
        limit: int,
        skip_locked: bool = True,
    ) -> list[AgentRestorePoint]: ...

    def find_ready_rows_missing_volumes(self, live_pvc_names: set[str], limit: int) -> list[AgentRestorePoint]: ...

    def find_existing_ids(self, restore_point_ids: set[UUID]) -> set[UUID]: ...

    def mark_ready_row_failed(self, restore_point_id: UUID, reason: str) -> bool: ...


class RestorePointReconciliationService(Protocol):
    def reconcile_row(self, row: AgentRestorePoint, *, respect_grace: bool = True) -> None: ...

    def apply_owed_replay(self, row: AgentRestorePoint) -> None: ...


class RestorePointReconciliationCluster(Protocol):
    def list_pvcs(self, namespace: str, label_selector: str = "") -> list[Any]: ...

    def list_jobs(self, namespace: str, label_selector: str = "") -> list[Any]: ...

    def delete_pvc(self, name: str, namespace: str) -> None: ...

    def delete_job(self, name: str, namespace: str) -> None: ...


def _labelled_id(item: Any) -> UUID | None:
    metadata = getattr(item, "metadata", None)
    labels = getattr(metadata, "labels", None) or {}
    try:
        return UUID(labels[RESTORE_POINT_ID_LABEL_KEY])
    except KeyError, TypeError, ValueError:
        return None


def _object_name(item: Any) -> str:
    metadata = getattr(item, "metadata", None)
    return getattr(metadata, "name", None) or ""


def _created_before(item: Any, cutoff: datetime) -> bool:
    metadata = getattr(item, "metadata", None)
    created = getattr(metadata, "creation_timestamp", None)
    if created is None:
        return False
    return created <= cutoff


@dataclass
class RestorePointReconciler:
    repository: RestorePointReconciliationRepository
    service: RestorePointReconciliationService
    k8s: RestorePointReconciliationCluster
    namespace: str

    def run_once(self) -> RestorePointReconciliationResult:
        started = time.monotonic()
        result = self._resolve_claimed(started)
        objects = self._list_objects()
        if objects is not None:
            result = self._fail_rows_without_volumes(objects, started, result)
            result = self._reclaim_orphans(objects, started, result)
        self._log_summary(result)
        return result

    def _expired(self, started: float) -> bool:
        return time.monotonic() - started >= RESTORE_POINT_RECONCILIATION_MAX_RUNTIME_SECONDS

    def _resolve_claimed(self, started: float) -> RestorePointReconciliationResult:
        try:
            rows = self.repository.claim_reconciliation_candidates(
                stale_before=datetime.now(UTC) - timedelta(seconds=RESTORE_POINT_RECONCILIATION_STALE_SECONDS),
                limit=RESTORE_POINT_RECONCILIATION_BATCH_SIZE,
            )
        except Exception:
            logger.warning("Could not claim restore points to reconcile", exc_info=True)
            return RestorePointReconciliationResult(failed=1)

        resolved = 0
        replays_attempted = 0
        failed = 0
        for row in rows:
            if self._expired(started):
                break
            try:
                self.service.reconcile_row(row, respect_grace=False)
                resolved += 1
            except Exception:
                failed += 1
                logger.warning("Could not reconcile restore point %s", row.id, exc_info=True)
                continue
            if not row.reapply_configuration:
                continue
            try:
                self.service.apply_owed_replay(row)
                replays_attempted += 1
            except Exception:
                failed += 1
                logger.warning("Could not re-apply the recorded configuration for %s", row.id, exc_info=True)
        return RestorePointReconciliationResult(
            claimed=len(rows),
            resolved=resolved,
            replays_attempted=replays_attempted,
            failed=failed,
        )

    def _list_objects(self) -> _ClusterObjects | None:
        try:
            return _ClusterObjects(
                pvcs=list(self.k8s.list_pvcs(self.namespace, RESTORE_POINT_SELECTOR)),
                jobs=list(self.k8s.list_jobs(self.namespace, RESTORE_POINT_SELECTOR)),
            )
        except Exception:
            logger.warning("Could not list restore point resources in %s", self.namespace, exc_info=True)
            return None

    def _fail_rows_without_volumes(
        self,
        objects: _ClusterObjects,
        started: float,
        result: RestorePointReconciliationResult,
    ) -> RestorePointReconciliationResult:
        live = {name for name in (_object_name(pvc) for pvc in objects.pvcs) if name}
        if not live:
            logger.warning(
                "No restore point volumes are present in %s; not failing any rows on an empty listing.",
                self.namespace,
            )
            return result
        try:
            rows = self.repository.find_ready_rows_missing_volumes(
                live, RESTORE_POINT_RECONCILIATION_MISSING_VOLUME_LIMIT
            )
        except Exception:
            logger.warning("Could not load ready restore points to check against live volumes", exc_info=True)
            return replace(result, failed=result.failed + 1)

        volumes_missing = 0
        failed = result.failed
        for row in rows:
            if self._expired(started):
                break
            try:
                if self.repository.mark_ready_row_failed(row.id, _MISSING_VOLUME_REASON.format(name=row.pvc_name)):
                    volumes_missing += 1
            except Exception:
                failed += 1
                logger.warning("Could not fail restore point %s whose volume is gone", row.id, exc_info=True)
        return replace(result, volumes_missing=volumes_missing, failed=failed)

    def _reclaim_orphans(
        self,
        objects: _ClusterObjects,
        started: float,
        result: RestorePointReconciliationResult,
    ) -> RestorePointReconciliationResult:
        candidates: list[tuple[str, Any]] = [("job", job) for job in objects.jobs]
        candidates += [("pvc", pvc) for pvc in objects.pvcs]

        identified = {found for found in (_labelled_id(item) for _, item in candidates) if found is not None}
        try:
            known = self.repository.find_existing_ids(identified)
        except Exception:
            logger.warning("Could not load restore point rows to match against cluster resources", exc_info=True)
            return replace(result, failed=result.failed + 1)

        cutoff = datetime.now(UTC) - timedelta(seconds=RESTORE_POINT_ORPHAN_MIN_AGE_SECONDS)
        deleted = 0
        unidentified = 0
        failed = result.failed
        for kind, item in candidates:
            if self._expired(started) or deleted >= RESTORE_POINT_ORPHAN_DELETE_LIMIT:
                break
            name = _object_name(item)
            try:
                restore_point_id = _labelled_id(item)
                if restore_point_id is None:
                    unidentified += 1
                    logger.warning(
                        "Restore point %s %s carries no %s label and will not be reclaimed automatically.",
                        kind,
                        name,
                        RESTORE_POINT_ID_LABEL_KEY,
                    )
                    continue
                if restore_point_id in known or not _created_before(item, cutoff):
                    continue
                self._delete(kind, name)
                deleted += 1
                logger.info("Reclaimed orphaned restore point %s %s", kind, name)
            except Exception:
                failed += 1
                logger.warning("Could not reclaim orphaned restore point %s %s", kind, name, exc_info=True)
        return replace(result, orphans_deleted=deleted, orphans_unidentified=unidentified, failed=failed)

    def _delete(self, kind: str, name: str) -> None:
        if kind == "job":
            self.k8s.delete_job(name, self.namespace)
        else:
            self.k8s.delete_pvc(name, self.namespace)

    def _log_summary(self, result: RestorePointReconciliationResult) -> None:
        logger.info(
            "Restore point reconciliation summary: claimed=%s resolved=%s replays_attempted=%s "
            "volumes_missing=%s orphans_deleted=%s orphans_unidentified=%s failed=%s",
            result.claimed,
            result.resolved,
            result.replays_attempted,
            result.volumes_missing,
            result.orphans_deleted,
            result.orphans_unidentified,
            result.failed,
        )


def build_reconciler() -> RestorePointReconciler:
    from api.core.utils import create_injector

    injector = create_injector()
    return injector.get(RestorePointReconciler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve stranded restore points and reclaim orphaned resources.")
    parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    build_reconciler().run_once()


if __name__ == "__main__":
    main()

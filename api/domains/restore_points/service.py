import enum
import json
import logging
import re
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from fastapi import HTTPException, status
from injector import inject, singleton
from kubernetes.client import V1Job
from sqlalchemy.exc import IntegrityError

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.builders.restore_point import (
    build_capture_job,
    build_restore_job,
    build_restore_point_pvc,
    capture_job_name,
    restore_job_name,
    restore_point_resource_name,
)
from api.domains.agents.error_messages import friendly_k8s_error
from api.domains.agents.models import (
    Agent,
    AgentRestorePoint,
    AgentStatus,
    RestorePointOrigin,
    RestorePointStatus,
    managed_update_in_flight,
)
from api.domains.agents.override_repository import AgentOverrideRepository
from api.domains.agents.provisioning_errors import AgentProvisioningOperation
from api.domains.agents.repository import AgentRepository
from api.domains.agents.restore_point_job import ENV_BACKUP, EXIT_BACKUP_FAILED, EXIT_RESTORE_FAILED
from api.domains.agents.selection import SelectionValidator
from api.domains.auth.models import CurrentUserContext
from api.domains.events import ActorIdentity, ActorIdentityType
from api.domains.events.catalog import (
    AGENT_RESTORE_POINT_CREATED,
    AGENT_RESTORE_POINT_DELETED,
    AGENT_RESTORE_POINT_RESTORED,
)
from api.domains.events.dispatch import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.rbac.catalog import PermissionKey
from api.domains.restore_points.constants import (
    RESTORE_POINT_POD_TERMINATION_POLL_SECONDS,
    RESTORE_POINT_POD_TERMINATION_TIMEOUT_SECONDS,
    RESTORE_POINT_RECONCILIATION_PENDING_GRACE_SECONDS,
)
from api.domains.restore_points.models import (
    ACTIVE_CAPTURE_STATUSES,
    AUTOMATIC_BACKUP_ORIGINS,
    MANUAL_GROUP_ORIGINS,
    NON_TERMINAL_STATUSES,
    TERMINAL_STATUSES,
    AgentRestorePointCreate,
    AgentRestorePointList,
    AgentRestorePointRead,
    AgentRestorePointRestore,
    RestorePointConfigManifest,
    RestorePointSkill,
    selection_from_manifest,
)
from api.domains.restore_points.repository import RestorePointRepository
from api.domains.skills.repository import SkillRepository
from api.domains.templates.repository import TemplateRepository
from api.infrastructure.kubernetes import KubernetesClient
from api.infrastructure.shared.models import Pagination

logger = logging.getLogger(__name__)

_MAX_FAILURE_REASON = 500

CAPTURE_TIMEOUT_SETTING = "RESTORE_POINT_CAPTURE_TIMEOUT_SECONDS"
RESTORE_TIMEOUT_SETTING = "RESTORE_POINT_RESTORE_TIMEOUT_SECONDS"

NOTHING_TO_CAPTURE_DETAIL = "This Agent has never run, so there is nothing to capture."
AGENT_RUNNING_DETAIL = "Stop the Agent before capturing a restore point."
AGENT_RUNNING_RESTORE_DETAIL = "Stop the Agent before restoring a restore point."
CAPTURE_IN_FLIGHT_DETAIL = "A restore point operation is already in progress for this Agent."
NOT_READY_DETAIL = "Only a ready restore point can be restored."
DELETE_IN_FLIGHT_DETAIL = "This restore point is still being worked on. Wait for it to finish, then delete it."
PRE_RESTORE_LABEL = "Automatic backup before restore"
NOT_REPLAYABLE_DETAIL = "This restore point predates the recorded configuration, so there is nothing to re-apply."
STILL_SHUTTING_DOWN_DETAIL = "The Agent is still shutting down. Try again in a moment."
MANAGED_UPDATE_IN_FLIGHT_DETAIL = "A managed update is in progress for this Agent. Wait for it to finish."
SCHEDULED_LABEL = "Scheduled snapshot"
SCHEDULED_DID_NOT_RUN_DETAIL = (
    "The scheduled snapshot did not finish in time. The Agent may have stopped before it could run, "
    f"or its files need longer to archive: raise {CAPTURE_TIMEOUT_SETTING}."
)
SYSTEM_ACTOR_DISPLAY = "Agent Barn"


def _display(context: CurrentUserContext) -> str:
    return context.user.full_name or context.user.email


def _selection_type(agent: Agent) -> str:
    """The pin's origin as ``select_agent_template`` names it.

    The display pin type collapses platform and organization templates into
    "shared", which is enough to render but not enough to re-apply.
    """
    if agent.platform_template_id is not None:
        return "platform"
    if agent.agent_template_id is not None:
        return "organization"
    if agent.agent_template_override_version_id is not None:
        return "override"
    return ""


class _RestoreOutcome(str, enum.Enum):
    BACKUP_FAILED = "BACKUP_FAILED"
    EXTRACTION_FAILED = "EXTRACTION_FAILED"
    UNKNOWN = "UNKNOWN"


def _manifest_from_line(line: str) -> dict | None:
    line = line.strip()
    if not line.startswith("{"):
        return None
    try:
        parsed = json.loads(line)
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_manifest(logs: str) -> dict:
    for line in reversed(logs.splitlines()):
        manifest = _manifest_from_line(line)
        if manifest is not None:
            return manifest
    return {}


def _without_module_path(line: str) -> str:
    return re.sub(r"^(?:\w+\.)+(?=\w*(?:Error|Exception):)", "", line)


def _deadline_exceeded(job: V1Job) -> bool:
    conditions = job.status.conditions if job.status is not None else None
    return any(c.type == "Failed" and c.status == "True" and c.reason == "DeadlineExceeded" for c in conditions or [])


def _ran_safety_copy(job: V1Job) -> bool:
    """Whether this restore Job copied the volume aside before wiping it.

    Read from the Job itself, because a managed-update rollback restores without
    one. A Job whose spec cannot be read counts as having none, which is the
    side that destroys nothing.
    """
    template = job.spec.template if job.spec is not None else None
    containers = template.spec.containers if template is not None and template.spec is not None else None
    return any(env.name == ENV_BACKUP for container in containers or [] for env in container.env or [])


@inject
@singleton
@dataclass
class RestorePointService:
    config: Config
    repository: RestorePointRepository
    agent_repository: AgentRepository
    agent_authorization: AgentAuthorization
    template_repository: TemplateRepository
    skill_repository: SkillRepository
    override_repository: AgentOverrideRepository
    selection: SelectionValidator
    k8s: KubernetesClient
    event_delivery_dispatcher: EventDeliveryDispatcher

    def _event_payload(
        self,
        agent: Agent,
        restore_point: AgentRestorePoint,
        actor_display: str,
        *,
        backup_skipped: bool = False,
    ) -> dict:
        return {
            "organization_id": agent.organization_id,
            "agent_id": agent.id,
            "agent_name": agent.name,
            "restore_point_id": restore_point.id,
            "origin": restore_point.origin,
            "label": restore_point.label,
            "actor_display": actor_display,
            "subject_display": agent.name,
            "backup_skipped": backup_skipped,
        }

    def list_restore_points(
        self,
        agent_id: UUID,
        context: CurrentUserContext,
        pagination: Pagination,
    ) -> AgentRestorePointList:
        scope = self._read_scope(agent_id, context)
        self.reconcile_agent(agent_id)
        page = self.repository.find_by_agent(agent_id, pagination, scope)
        return AgentRestorePointList(
            page=page.page,
            page_size=page.page_size,
            total=page.total,
            items=page.items,
            cap=self.config.restore_point_max_per_agent,
            manual_count=self.repository.count_manual_for_agent(agent_id),
            scheduled_cap=self.config.restore_point_scheduled_max_per_agent,
            schedule_interval_minutes=self.config.restore_point_schedule_interval_minutes,
        )

    def reconcile_agent(self, agent_id: UUID) -> None:
        """Resolve non-terminal rows from live Job status.

        Never raises: a reconciliation failure must not fail the read that
        triggered it, so callers still serve the last known status.
        """
        try:
            rows = self.repository.find_non_terminal_for_agent(agent_id)
        except Exception:
            logger.warning("Could not load restore points to reconcile for agent %s", agent_id, exc_info=True)
            return

        for row in rows:
            try:
                self._reconcile_row(row)
            except Exception:
                logger.warning("Could not reconcile restore point %s", row.id, exc_info=True)

        # Separate pass, and driven by the stored intent rather than by what just
        # happened above: a replay owed by an earlier read — or by a process that
        # stopped before writing it — is still found here.
        try:
            owed = self.repository.find_owing_replay_for_agent(agent_id)
        except Exception:
            logger.warning("Could not load pending configuration replays for agent %s", agent_id, exc_info=True)
            return

        for row in owed:
            try:
                self._apply_recorded_configuration_after_restore(row)
            except Exception:
                logger.warning("Could not re-apply the recorded configuration for %s", row.id, exc_info=True)

    def reconcile_row(self, row: AgentRestorePoint, *, respect_grace: bool = True) -> None:
        self._reconcile_row(row, respect_grace=respect_grace)

    def wait_until_terminal(
        self,
        agent_id: UUID,
        restore_point_id: UUID,
        *,
        timeout_seconds: int,
        poll_seconds: int = 5,
        on_poll: Callable[[], None] | None = None,
    ) -> AgentRestorePoint:
        """Block until one restore point row resolves to READY or FAILED.

        Drives `reconcile_agent` on every poll — that is what advances a row
        whose Job has finished but which nobody has read yet. A FAILED row is
        returned, not raised: the caller decides what a failed capture means
        for the operation it was backing. `on_poll` runs on every poll, so a
        long wait can show it is still alive.
        """
        deadline = time.monotonic() + timeout_seconds
        while True:
            if on_poll is not None:
                on_poll()
            self.reconcile_agent(agent_id)
            row = self.repository.get_by_id(restore_point_id)
            if row is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Restore point {restore_point_id} not found",
                )
            if row.status in TERMINAL_STATUSES:
                return row
            if time.monotonic() >= deadline:
                raise HTTPException(
                    status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                    detail=(f"Restore point {restore_point_id} did not finish within {timeout_seconds} seconds"),
                )
            time.sleep(poll_seconds)

    def apply_owed_replay(self, row: AgentRestorePoint) -> None:
        self._apply_recorded_configuration_after_restore(row)

    def _reconcile_row(self, row: AgentRestorePoint, *, respect_grace: bool = True) -> None:
        namespace = self.config.k8s_namespace
        if row.status in TERMINAL_STATUSES:
            # The reconciler also claims terminal rows that still owe a configuration
            # replay. There is no Job left to read — mark_ready and mark_restored clear
            # job_name — so resolving one would fail a healthy row and release the
            # archive it is still holding.
            return

        if row.status == RestorePointStatus.DELETING:
            self._finish_interrupted_prune(row, respect_grace)
            return

        if not row.job_name:
            self._resolve_untracked(row, "The restore point has no job to track.", respect_grace)
            return

        job = self.k8s.get_job(row.job_name, namespace)
        if job is None:
            self._resolve_untracked(
                row, "The job that was running this operation is no longer available.", respect_grace
            )
            return

        status_block = job.status
        if status_block is None:
            return

        if status_block.succeeded:
            if row.status == RestorePointStatus.RESTORING:
                # The configuration is not written here. The intent stays on the row
                # and is picked up below, so work is never lost between the two.
                self.repository.mark_restored(row.id)
            else:
                self._succeed(row)
            return

        if status_block.failed:
            self._resolve_failure(row, job, namespace)
            return

        if row.status == RestorePointStatus.PENDING and status_block.active:
            self.repository.update_status(
                row.id, RestorePointStatus.CAPTURING, from_statuses=(RestorePointStatus.PENDING,)
            )

    def _resolve_untracked(self, row: AgentRestorePoint, reason: str, respect_grace: bool = True) -> None:
        """Resolve a row with no Job to read — but only once it has had time to get one.

        A row is committed before its Job is created, so a read landing in that
        window would otherwise fail a healthy operation. Past the grace window a
        missing Job is genuine. A restore target keeps its volume; a capture
        releases the one it never finished writing. The target of a restore the
        user ran without a backup stays restorable, since nothing else can undo it.
        """
        grace = timedelta(seconds=RESTORE_POINT_RECONCILIATION_PENDING_GRACE_SECONDS)
        if respect_grace and row.updated_at > datetime.now(UTC) - grace:
            return
        if row.status == RestorePointStatus.RESTORING and row.backup_skipped_by_user:
            if row.reapply_configuration:
                self.repository.mark_configuration_failed(
                    row.id, "Nothing says the restore finished, so the recorded configuration was not applied."
                )
            self.repository.mark_restore_retryable(row.id, reason[:_MAX_FAILURE_REASON])
        elif row.status == RestorePointStatus.RESTORING:
            self._fail(row, reason)
        else:
            self._fail_capture(row, reason)

    def _resolve_failure(self, row: AgentRestorePoint, job: V1Job, namespace: str) -> None:
        """Split a failed Job across the rows it serves, destroying nothing on doubt.

        A capture's volume holds no usable archive and is always released. A
        restore is judged by which phase failed: if the safety net never finished,
        the Agent volume was never touched; if it did, the backup is the recovery
        path. When the phase cannot be established the backup volume is kept.
        """
        reason = self._failure_reason(row, job, namespace)
        is_restore = row.status == RestorePointStatus.RESTORING or row.origin == RestorePointOrigin.PRE_RESTORE
        if not is_restore:
            self._fail_capture(row, reason)
            return

        outcome = self._restore_outcome(job, row.job_name or "", namespace)
        if row.status == RestorePointStatus.RESTORING:
            # Neither branch replaced the volume, so any configuration owed for this
            # restore is owed no longer. BACKUP_FAILED returns the row to READY
            # because the archive is still good — not because the restore happened.
            if row.reapply_configuration:
                self.repository.mark_configuration_failed(
                    row.id,
                    "The restore did not complete, so the recorded configuration was not applied.",
                )
            if outcome == _RestoreOutcome.BACKUP_FAILED:
                self.repository.mark_restored(row.id)
            elif row.backup_skipped_by_user:
                self.repository.mark_restore_retryable(row.id, reason[:_MAX_FAILURE_REASON])
            else:
                self._fail(row, reason)
            return

        if outcome == _RestoreOutcome.EXTRACTION_FAILED:
            self._succeed(row)
        elif outcome == _RestoreOutcome.BACKUP_FAILED:
            self._fail_capture(row, reason)
        else:
            self._fail(row, reason)

    def _restore_outcome(self, job: V1Job, job_name: str, namespace: str) -> _RestoreOutcome:
        if self.k8s.get_pod_name_for_job(job_name, namespace) is None:
            return _RestoreOutcome.UNKNOWN
        exit_code = self.k8s.get_job_exit_code(job_name, namespace)
        if exit_code == EXIT_BACKUP_FAILED:
            return _RestoreOutcome.BACKUP_FAILED
        if exit_code == EXIT_RESTORE_FAILED:
            return _RestoreOutcome.EXTRACTION_FAILED
        if not _ran_safety_copy(job):
            # The missing manifest below proves the wipe never ran only because
            # the safety copy prints one first. Without that phase nothing runs
            # before the wipe, so a pod killed mid-extraction (OOM, deadline,
            # eviction) looks the same as one that never started.
            return _RestoreOutcome.EXTRACTION_FAILED
        logs = self.k8s.read_job_logs(job_name, namespace)
        if logs is None:
            return _RestoreOutcome.UNKNOWN
        if _parse_manifest(logs):
            return _RestoreOutcome.EXTRACTION_FAILED
        return _RestoreOutcome.BACKUP_FAILED

    def _failure_reason(self, row: AgentRestorePoint, job: V1Job, namespace: str) -> str:
        if _deadline_exceeded(job) and row.origin == RestorePointOrigin.SCHEDULED:
            return SCHEDULED_DID_NOT_RUN_DETAIL
        if _deadline_exceeded(job):
            is_restore = row.status == RestorePointStatus.RESTORING or row.origin == RestorePointOrigin.PRE_RESTORE
            setting = RESTORE_TIMEOUT_SETTING if is_restore else CAPTURE_TIMEOUT_SETTING
            return f"The operation did not finish within its time limit. Raise {setting} for large Agent volumes."
        return self._job_failure_reason(row.job_name or "", namespace)

    def _succeed(self, row: AgentRestorePoint) -> None:
        manifest = self._read_manifest(row)
        self.repository.mark_ready(
            row.id,
            archive_bytes=manifest.get("bytes"),
            file_count=manifest.get("file_count"),
        )

    def _fail(self, row: AgentRestorePoint, reason: str) -> bool:
        return self.repository.mark_failed(row.id, reason[:_MAX_FAILURE_REASON])

    def _fail_capture(self, row: AgentRestorePoint, reason: str) -> None:
        """Fail a capture and release the volume it was writing into.

        A capture that never finished leaves no usable archive, so its destination
        volume is dead weight. A row failing as a *restore target* keeps its
        volume: that archive is intact and is what the retry reads from.

        The volume goes only when this call is the one that failed the row. A
        conditional update that matched nothing means the row was never ours to
        fail, and releasing storage on that basis destroys an archive something
        else still owns.
        """
        if self._fail(row, reason) and row.pvc_name:
            self.k8s.delete_pvc(row.pvc_name, self.config.k8s_namespace)

    def _read_manifest(self, row: AgentRestorePoint) -> dict:
        if not row.job_name:
            return {}
        logs = self.k8s.read_job_logs(row.job_name, self.config.k8s_namespace)
        return _parse_manifest(logs) if logs else {}

    def _job_failure_reason(self, job_name: str, namespace: str) -> str:
        logs = self.k8s.read_job_logs(job_name, namespace)
        if logs:
            lines = [line.strip() for line in logs.splitlines() if line.strip() and _manifest_from_line(line) is None]
            if lines:
                return _without_module_path(lines[-1])
        return "The operation failed. Check the cluster logs for details."

    def get_restore_point(
        self,
        agent_id: UUID,
        restore_point_id: UUID,
        context: CurrentUserContext,
    ) -> AgentRestorePointRead:
        scope = self._read_scope(agent_id, context)
        self.reconcile_agent(agent_id)
        restore_point = self.repository.get_in_scope(restore_point_id, agent_id, scope)
        if restore_point is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Restore point {restore_point_id} not found",
            )
        return AgentRestorePointRead.model_validate(restore_point)

    def create_restore_point(
        self,
        agent_id: UUID,
        payload: AgentRestorePointCreate,
        context: CurrentUserContext,
        *,
        managed_update: bool = False,
    ) -> AgentRestorePointRead:
        """Capture the Agent's volume.

        `managed_update` marks the capture a managed update takes of its own
        Agent: it is recorded as PRE_UPGRADE and is the one capture allowed
        while that update runs.
        """
        agent = self.agent_authorization.require_action(context, agent_id, PermissionKey.AGENT_LIFECYCLE_MANAGE)
        origin = RestorePointOrigin.PRE_UPGRADE if managed_update else RestorePointOrigin.MANUAL

        self._await_agent_volume_release(agent.id)

        with self._locked_agent(agent.id) as current:
            if not managed_update:
                self._refuse_during_managed_update(current)
            self._assert_capturable(current, origin)
            restore_point, delivery_ids = self._begin_backup(
                current,
                origin=origin,
                label=payload.label,
                created_by_user_id=context.user.id,
                actor=resolve_actor_identity(context, current.organization_id),
                actor_display=_display(context),
            )

        self._dispatch(delivery_ids)
        return AgentRestorePointRead.model_validate(restore_point)

    def capture_scheduled(self, agent_id: UUID) -> AgentRestorePoint | None:
        """Take a scheduled snapshot of a running Agent, or None when now is not the moment.

        The capture reads the volume while the Agent keeps writing to it, so a file
        changing mid-capture is caught as it was then. Anything that would make this
        wait or refuse — another operation, a managed update, the lifecycle lock — is a
        skip: the schedule tries again on its next run.

        The cluster reads happen before the lock, so a user's start, stop or delete only
        meets the lock while the capture's volume and Job are created.
        """
        if not self._is_snapshot_candidate(self.agent_repository.get_by_id(agent_id)):
            return None
        if self.k8s.get_pvc(f"agent-{agent_id}", self.config.k8s_namespace) is None:
            return None
        # The capture is placed beside the Agent's running pod. With none (an Agent stuck
        # on quota, or whose pod is still Pending, reads RUNNING) it could never be
        # scheduled, and would hold a concurrency slot until its deadline.
        if self.k8s.get_pod_name_for_deployment(f"agent-{agent_id}", self.config.k8s_namespace) is None:
            return None

        with self.agent_repository.lifecycle_lock(agent_id) as acquired:
            if not acquired:
                return None
            current = self.agent_repository.get_by_id(agent_id)
            if current is None or not self._is_snapshot_candidate(current):
                return None
            try:
                restore_point, delivery_ids = self._begin_backup(
                    current,
                    origin=RestorePointOrigin.SCHEDULED,
                    label=SCHEDULED_LABEL,
                    created_by_user_id=None,
                    actor=self._system_actor(current),
                    actor_display=SYSTEM_ACTOR_DISPLAY,
                    beside_running_agent=True,
                )
            except IntegrityError:
                # Another capture became active between the check and the insert.
                return None

        self._dispatch(delivery_ids)
        return restore_point

    def _is_snapshot_candidate(self, agent: Agent | None) -> bool:
        return (
            agent is not None
            and agent.status == AgentStatus.RUNNING
            and agent.deleted_at is None
            and not managed_update_in_flight(agent)
            and not self.repository.has_agent_volume_operation(agent.id)
            and not self.repository.find_owing_replay_for_agent(agent.id)
        )

    @contextmanager
    def _locked_agent(self, agent_id: UUID) -> Iterator[Agent]:
        """Hold the Agent's lifecycle lock and yield the Agent, read again under it.

        Every operation that starts a Job on the Agent's volume checks the Agent's state and
        starts the Job inside this lock, so a start, a stop or a delete cannot land between the
        two. It refuses rather than waits when something else holds the lock.
        """
        with self.agent_repository.lifecycle_lock(agent_id) as acquired:
            if not acquired:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CAPTURE_IN_FLIGHT_DETAIL)
            current = self.agent_repository.get_by_id(agent_id)
            if current is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found")
            yield current

    def _begin_backup(
        self,
        agent: Agent,
        *,
        origin: RestorePointOrigin,
        label: str | None,
        created_by_user_id: UUID | None,
        actor: ActorIdentity,
        actor_display: str,
        beside_running_agent: bool = False,
    ) -> tuple[AgentRestorePoint, list[UUID]]:
        """Record a capture with its event, then start the Job that writes it.

        The caller dispatches the returned deliveries once it has released the lock.
        """
        restore_point_id = uuid7()
        restore_point = AgentRestorePoint(
            id=restore_point_id,
            agent_id=agent.id,
            created_by_user_id=created_by_user_id,
            label=label,
            status=RestorePointStatus.PENDING,
            origin=origin,
            agent_type=agent.agent_type,
            pvc_name=restore_point_resource_name(restore_point_id),
            job_name=capture_job_name(restore_point_id),
            config_manifest=self._build_config_manifest(agent).model_dump(mode="json"),
        )
        result = self.repository.save_with_event(
            restore_point,
            event_name=AGENT_RESTORE_POINT_CREATED,
            actor=actor,
            payload=self._event_payload(agent, restore_point, actor_display),
        )
        self._provision_backup(agent, restore_point, self._capture_job(agent, restore_point, beside_running_agent))
        return restore_point, result.delivery_ids

    def _system_actor(self, agent: Agent) -> ActorIdentity:
        return ActorIdentity(
            type=ActorIdentityType.SYSTEM, id="restore-point-schedule", organization_id=agent.organization_id
        )

    def _cancel_scheduled_captures(self, agent: Agent) -> None:
        """Stop a scheduled snapshot in progress, so the operation asking for the volume can run.

        One capture runs per Agent at a time, and a restore must not wipe the volume a snapshot
        is reading. A scheduled snapshot is the one operation that is cheaper to drop than to
        wait for. It is removed rather than failed: being replaced says nothing about whether
        the schedule works, and with no row left the next run takes a snapshot again.
        """
        for row in self.repository.find_non_terminal_for_agent(agent.id):
            if row.origin != RestorePointOrigin.SCHEDULED:
                continue
            self._reconcile_row(row)
            current = self.repository.get_by_id(row.id)
            if current is None or current.status not in NON_TERMINAL_STATUSES:
                continue
            if self.repository.mark_deleting(current.id, from_statuses=ACTIVE_CAPTURE_STATUSES):
                self._remove(agent, current)

    def trim_over_retention(self) -> int:
        """Apply retention to every Agent past a limit, and say how many lost a restore point.

        Runs from the reconciliation CronJob, which is on whether or not scheduled snapshots
        are, and never from a request: removing restore points deletes Jobs and volumes.
        """
        agent_ids = self.repository.find_agent_ids_over_retention(
            scheduled_cap=self.config.restore_point_scheduled_max_per_agent,
            manual_cap=self.config.restore_point_max_per_agent,
        )
        trimmed = 0
        for agent_id in agent_ids:
            try:
                trimmed += self.enforce_retention(agent_id) > 0
            except Exception:
                logger.warning("Could not apply restore point retention for agent %s", agent_id, exc_info=True)
        return trimmed

    def enforce_retention(self, agent_id: UUID) -> int:
        """Remove the restore points an Agent keeps beyond its limits, and say how many went.
        Safe to run again.

        Scheduled snapshots keep the newest `RESTORE_POINT_SCHEDULED_MAX_PER_AGENT`, and only
        the newest failed attempt, which is what tells the user the schedule is failing.
        Restore points a user took share `RESTORE_POINT_MAX_PER_AGENT` with the backups taken
        before an update or a restore; past it the oldest of those backups goes, but never the
        newest one and never one a user took. Only READY rows count, so a capture in progress
        never pushes out the snapshot it may yet fail to replace.

        Nothing is removed while a managed update runs: its own backup is its way back. The
        next reconciliation pass removes it once the update is over.
        """
        agent = self.agent_repository.get_by_id(agent_id)
        if agent is None or managed_update_in_flight(agent):
            return 0
        removed = self._prune_oldest(
            agent,
            counted=(RestorePointOrigin.SCHEDULED,),
            removable=(RestorePointOrigin.SCHEDULED,),
            keep=self.config.restore_point_scheduled_max_per_agent,
        )
        removed += self._prune_oldest(
            agent,
            counted=MANUAL_GROUP_ORIGINS,
            removable=AUTOMATIC_BACKUP_ORIGINS,
            keep=self.config.restore_point_max_per_agent,
            spare_newest_removable=True,
        )
        failed = self.repository.find_for_agent_by_origin(
            agent.id, (RestorePointOrigin.SCHEDULED,), (RestorePointStatus.FAILED,)
        )
        for row in failed[:-1]:
            if self.repository.mark_deleting(row.id, from_statuses=(RestorePointStatus.FAILED,)):
                self._remove(agent, row)
                removed += 1
        return removed

    def _prune_oldest(
        self,
        agent: Agent,
        *,
        counted: tuple[RestorePointOrigin, ...],
        removable: tuple[RestorePointOrigin, ...],
        keep: int,
        spare_newest_removable: bool = False,
    ) -> int:
        ready = self.repository.find_for_agent_by_origin(agent.id, counted, (RestorePointStatus.READY,))
        excess = len(ready) - keep
        if excess <= 0:
            return 0
        candidates = [row for row in ready if row.origin in removable and not row.reapply_configuration]
        if spare_newest_removable:
            candidates = candidates[:-1]
        removed = 0
        for row in candidates[:excess]:
            if self.repository.mark_deleting(row.id, from_statuses=(RestorePointStatus.READY,)):
                self._remove(agent, row)
                removed += 1
        return removed

    def _remove(self, agent: Agent, row: AgentRestorePoint) -> None:
        """Delete a DELETING restore point's Job and volume, then its row with its event."""
        self._release(row)
        delivery_ids = self.repository.delete_with_event(
            row,
            event_name=AGENT_RESTORE_POINT_DELETED,
            actor=self._system_actor(agent),
            payload=self._event_payload(agent, row, SYSTEM_ACTOR_DISPLAY),
        )
        self._dispatch(delivery_ids)

    def _release(self, row: AgentRestorePoint) -> None:
        """Delete a restore point's Job and volume. The row goes after, so a removal cut short
        stays DELETING and reconciliation finishes it."""
        namespace = self.config.k8s_namespace
        if row.job_name:
            self.k8s.delete_job(row.job_name, namespace)
        if row.pvc_name:
            self.k8s.delete_pvc(row.pvc_name, namespace)

    def _finish_interrupted_prune(self, row: AgentRestorePoint, respect_grace: bool) -> None:
        grace = timedelta(seconds=RESTORE_POINT_RECONCILIATION_PENDING_GRACE_SECONDS)
        if respect_grace and row.updated_at > datetime.now(UTC) - grace:
            return
        agent = self.agent_repository.get_by_id(row.agent_id)
        if agent is None:
            self._release(row)
            self.repository.delete(row.id)
            return
        self._remove(agent, row)

    def restore_restore_point(
        self,
        agent_id: UUID,
        restore_point_id: UUID,
        payload: AgentRestorePointRestore,
        context: CurrentUserContext,
        *,
        managed_update: bool = False,
    ) -> AgentRestorePointRead:
        """Put a restore point's archive back onto the Agent's volume.

        `managed_update` marks a managed update's rollback: it is the one restore
        allowed while that update runs, and it skips the safety copy (see below).
        """
        agent = self.agent_authorization.require_action(context, agent_id, PermissionKey.AGENT_LIFECYCLE_MANAGE)
        scope = self.agent_authorization.authorization_scope(context, PermissionKey.ACTIVITY_READ)

        self._await_agent_volume_release(agent.id)

        with self.agent_repository.lifecycle_lock(agent.id) as acquired:
            if not acquired:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CAPTURE_IN_FLIGHT_DETAIL)

            current = self.agent_repository.get_by_id(agent.id)
            if current is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found")
            if current.status == AgentStatus.RUNNING:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=AGENT_RUNNING_RESTORE_DETAIL)
            if not managed_update:
                self._refuse_during_managed_update(current)

            target = self.repository.get_in_scope(restore_point_id, agent_id, scope)
            if target is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Restore point {restore_point_id} not found",
                )
            if target.status != RestorePointStatus.READY:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=NOT_READY_DETAIL)
            if self.repository.find_owing_replay_for_agent(agent_id):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CAPTURE_IN_FLIGHT_DETAIL)

            if payload.reapply_configuration:
                # Authorized here, applied later: the write happens in reconciliation
                # once the Job confirms the volume is back, so the permission for it
                # has to be settled while the requester is still on the call.
                self.agent_authorization.require_action_for_visible(context, current, PermissionKey.AGENT_UPDATE)
                # Before the Job, not after it: a configuration that cannot be applied
                # must not cost the Agent its files first.
                self._validate_recorded_configuration(current, target)

            # Last, once nothing else refuses: a refused restore never costs the schedule a snapshot.
            self._cancel_scheduled_captures(current)
            if self.repository.has_agent_volume_operation(agent_id):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CAPTURE_IN_FLIGHT_DETAIL)

            job_name = restore_job_name(target.id)
            # The safety copy of the volume exists for restores whose source
            # archive may be worse than what is on the volume now. A managed-update
            # rollback restores the pre-upgrade archive, which is newer and better
            # by construction than whatever the failed update left behind — so it
            # skips the copy instead of paying ~20s and a confusing row for it.
            # Without the copy a failed extraction has nothing to fall back to;
            # the caller keeps the target restorable instead (see
            # `reopen_failed_restore`).
            skip_backup = managed_update or payload.skip_backup
            backup = None if skip_backup else self._create_pre_restore_row(current, job_name)
            result = self.repository.update_status_with_event(
                target.id,
                RestorePointStatus.RESTORING,
                from_statuses=(RestorePointStatus.READY,),
                job_name=job_name,
                event_name=AGENT_RESTORE_POINT_RESTORED,
                actor=resolve_actor_identity(context, current.organization_id),
                payload=self._event_payload(current, target, _display(context), backup_skipped=payload.skip_backup),
                reapply_configuration=payload.reapply_configuration,
                backup_skipped_by_user=payload.skip_backup and not managed_update,
                restored_by_user_id=context.user.id,
                restored_by_display=context.user.full_name or context.user.email,
            )
            if result is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=NOT_READY_DETAIL)

            self._provision_restore(current, target, backup, job_name)

        self._dispatch(result.delivery_ids)

        refreshed = self.repository.get_in_scope(restore_point_id, agent_id, scope)
        return AgentRestorePointRead.model_validate(refreshed or target)

    def _apply_recorded_configuration_after_restore(self, row: AgentRestorePoint) -> None:
        """Write the recorded configuration once the restore has confirmed success.

        Deferred work, not a request: authorization was settled when the restore was
        asked for, and the actor recorded here is the Member who asked. A failure is
        stored on the row rather than raised — reconciliation runs inside somebody
        else's read and must not fail it, and the volume is already back either way.
        """
        # The lock is what keeps this from running beside a start, a delete, or a
        # second reconciler: once the row is terminal nothing else holds the Agent.
        with self.agent_repository.lifecycle_lock(row.agent_id) as acquired:
            if not acquired:
                return
            agent = self.agent_repository.get_by_id(row.agent_id)
            if agent is None or agent.status == AgentStatus.RUNNING:
                return
            # Re-read under the lifecycle lock: another reconciler may have
            # completed this replay since the sweep loaded its copy.
            pending = self.repository.find_owing_replay_for_agent(row.agent_id)
            refreshed = next((pending_row for pending_row in pending if pending_row.id == row.id), None)
            if refreshed is None:
                return
            row = refreshed
            try:
                self._write_recorded_configuration(
                    agent,
                    row,
                    self._replay_actor(row, agent),
                    row.restored_by_display or "Agent Barn",
                )
            except HTTPException as exc:
                self.repository.mark_configuration_failed(row.id, str(exc.detail)[:_MAX_FAILURE_REASON])
            except Exception:
                logger.warning("Could not re-apply the recorded configuration for %s", row.id, exc_info=True)
                self.repository.mark_configuration_failed(row.id, "The recorded configuration could not be re-applied.")

    def _replay_actor(self, row: AgentRestorePoint, agent: Agent) -> ActorIdentity:
        """The Member who asked for the restore, since they authorized this write."""
        if row.restored_by_user_id is None:
            return ActorIdentity(
                type=ActorIdentityType.SYSTEM, id="restore-points", organization_id=agent.organization_id
            )
        return ActorIdentity(
            type=ActorIdentityType.USER,
            id=row.restored_by_user_id,
            organization_id=agent.organization_id,
        )

    def _write_recorded_configuration(
        self,
        agent: Agent,
        target: AgentRestorePoint,
        actor: ActorIdentity,
        actor_display: str = "Agent Barn",
    ) -> None:
        selection = self._recorded_selection(agent, target)
        # Skills the Agent has now but the manifest does not are dropped, so the
        # replay lands on exactly the recorded set rather than a superset.
        recorded = set(selection.skill_ids)
        selection.removed_skill_ids = [
            row.skill_id for row in self.agent_repository.get_skills_for_agent(agent.id) if row.skill_id not in recorded
        ]
        resolved = self.selection.resolve(agent, selection, agent.organization_id)
        self.override_repository.select_pin(
            agent.id,
            agent.organization_id,
            selection_type=selection.selection_type,
            selected_id=resolved.selected_id,
            expected_agent_updated_at=agent.updated_at,
            actor=actor,
            actor_display=actor_display,
            template_key=resolved.template_key,
            selected_version=resolved.version,
            skill_pins=[(pin.skill_id, pin.version) for pin in resolved.skill_pins],
            removed_skill_ids=resolved.removed_skill_ids,
            scalar_updates=resolved.scalar_updates,
            restored_configuration_id=target.id,
        )

    def apply_recorded_configuration(
        self,
        agent_id: UUID,
        restore_point_id: UUID,
        context: CurrentUserContext,
    ) -> None:
        """Write the configuration this restore point recorded.

        Separate from the restore because the volume comes back first: applying
        before the Job finishes would leave the configuration changed even when the
        files never were. The selection is rebuilt here from the stored manifest
        rather than sent by the client, so what was checked before the Job is what
        gets written after it.
        """
        agent = self.agent_authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        scope = self.agent_authorization.authorization_scope(context, PermissionKey.ACTIVITY_READ)

        with self.agent_repository.lifecycle_lock(agent.id) as acquired:
            if not acquired:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CAPTURE_IN_FLIGHT_DETAIL)
            current = self.agent_repository.get_by_id(agent.id)
            if current is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found")
            if current.status == AgentStatus.RUNNING:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=AGENT_RUNNING_RESTORE_DETAIL)
            self._refuse_during_managed_update(current)

            target = self.repository.get_in_scope(restore_point_id, agent_id, scope)
            if target is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Restore point {restore_point_id} not found",
                )

            if self.repository.has_agent_volume_operation(agent_id) or self.repository.find_owing_replay_for_agent(
                agent_id
            ):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CAPTURE_IN_FLIGHT_DETAIL)

            self._write_recorded_configuration(
                current,
                target,
                resolve_actor_identity(context, current.organization_id),
                context.user.full_name or context.user.email,
            )

    def _recorded_selection(self, agent: Agent, target: AgentRestorePoint):
        selection = selection_from_manifest(target.config_manifest, agent.updated_at)
        if selection is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=NOT_REPLAYABLE_DETAIL)
        return selection

    def _validate_recorded_configuration(self, agent: Agent, target: AgentRestorePoint) -> None:
        self.selection.resolve(agent, self._recorded_selection(agent, target), agent.organization_id)

    def _create_pre_restore_row(self, agent: Agent, job_name: str) -> AgentRestorePoint:
        backup_id = uuid7()
        backup = AgentRestorePoint(
            id=backup_id,
            agent_id=agent.id,
            label=PRE_RESTORE_LABEL,
            status=RestorePointStatus.PENDING,
            origin=RestorePointOrigin.PRE_RESTORE,
            agent_type=agent.agent_type,
            pvc_name=restore_point_resource_name(backup_id),
            job_name=job_name,
            config_manifest=self._build_config_manifest(agent).model_dump(mode="json"),
        )
        return self.repository.save(backup)

    def _provision_restore(
        self,
        agent: Agent,
        target: AgentRestorePoint,
        backup: AgentRestorePoint | None,
        job_name: str,
    ) -> None:
        namespace = self.config.k8s_namespace
        try:
            if backup is not None:
                self.k8s.create_pvc(
                    namespace,
                    build_restore_point_pvc(
                        backup.id,
                        agent.id,
                        agent.organization_id,
                        namespace,
                        self.config.restore_point_size,
                        self.config.storage_class or None,
                    ),
                )
            self.k8s.create_job(
                namespace,
                build_restore_job(
                    job_name=job_name,
                    restore_point_id=target.id,
                    agent_id=agent.id,
                    org_id=agent.organization_id,
                    namespace=namespace,
                    image=self.config.api_image,
                    runtime=agent.agent_type,
                    agent_pvc=f"agent-{agent.id}",
                    backup_pvc=backup.pvc_name if backup is not None else None,
                    archive_pvc=target.pvc_name,
                    timeout_seconds=self.config.restore_point_restore_timeout_seconds,
                    image_pull_secret=self.config.agent_image_pull_secret or None,
                ),
            )
        except Exception as exc:
            # The reason stored on the row is sanitized down to fixed copy; the
            # apiserver's account of what it rejected is kept only in the log.
            logger.exception("Could not provision the restore of restore point %s onto agent %s", target.id, agent.id)
            reason = friendly_k8s_error(exc, operation=AgentProvisioningOperation.RESTORE)
            if backup is not None:
                self.repository.mark_failed(backup.id, reason[:_MAX_FAILURE_REASON])
                self.k8s.delete_pvc(backup.pvc_name, namespace)
            self.repository.mark_restored(target.id, cancel_replay=True)
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=reason) from exc

    def delete_restore_point(
        self,
        agent_id: UUID,
        restore_point_id: UUID,
        context: CurrentUserContext,
    ) -> None:
        self.agent_authorization.require_action(context, agent_id, PermissionKey.AGENT_LIFECYCLE_MANAGE)
        scope = self.agent_authorization.authorization_scope(context, PermissionKey.ACTIVITY_READ)

        self.reconcile_agent(agent_id)
        restore_point = self.repository.get_in_scope(restore_point_id, agent_id, scope)
        if restore_point is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Restore point {restore_point_id} not found",
            )
        if restore_point.status in NON_TERMINAL_STATUSES or restore_point.reapply_configuration:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=DELETE_IN_FLIGHT_DETAIL)

        agent = self.agent_repository.get_by_id(agent_id)
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found")
        # Above all the update's own backup, which its rollback restores from.
        self._refuse_during_managed_update(agent)

        namespace = self.config.k8s_namespace
        if restore_point.job_name:
            self.k8s.delete_job(restore_point.job_name, namespace)
        if restore_point.pvc_name:
            self.k8s.delete_pvc(restore_point.pvc_name, namespace)

        delivery_ids = self.repository.delete_with_event(
            restore_point,
            event_name=AGENT_RESTORE_POINT_DELETED,
            actor=resolve_actor_identity(context, agent.organization_id),
            payload=self._event_payload(agent, restore_point, _display(context)),
        )
        self._dispatch(delivery_ids)

    def _dispatch(self, delivery_ids: list[UUID]) -> None:
        if not delivery_ids:
            return
        try:
            self.event_delivery_dispatcher.enqueue_immediate(delivery_ids)
        except Exception:
            logger.warning("Could not enqueue restore point event deliveries", exc_info=True)

    def has_blocking_operation(self, agent_id: UUID) -> bool:
        """True while volume work or its requested configuration replay is pending.

        Reconciles first so a finished or ttl-reaped Job resolves to terminal
        rather than blocking the Agent — and its Organization — forever. A
        scheduled snapshot blocks nothing: it only reads the volume, beside the
        running Agent, and whatever needs the volume to itself cancels it.
        """
        self.reconcile_agent(agent_id)
        return self.repository.has_agent_volume_operation(agent_id, ignoring=(RestorePointOrigin.SCHEDULED,)) or bool(
            self.repository.find_owing_replay_for_agent(agent_id)
        )

    def purge_agent(self, agent_id: UUID) -> None:
        """Remove every restore point resource belonging to one Agent.

        Restore point PVCs and Jobs are named by restore point id, so the Agent's
        own `agent-<id>` teardown cannot reach them; they are found by label.
        """
        namespace = self.config.k8s_namespace
        selector = f"agentbarn.io/agent-id={agent_id}"

        for job in self.k8s.list_jobs(namespace, selector):
            self.k8s.delete_job(job.metadata.name, namespace)
        for pvc in self.k8s.list_pvcs(namespace, selector):
            self.k8s.delete_pvc(pvc.metadata.name, namespace)
        self.repository.delete_for_agent(agent_id)

    def reopen_failed_restore(self, restore_point_id: UUID) -> bool:
        """Make a restore point restorable again after a restore from it failed.

        A failed restore target keeps its volume, and the restore Job mounts that
        archive read-only, so the archive is intact. A managed-update rollback runs
        without a safety copy, so this archive is the only way back.
        """
        return self.repository.mark_failed_restore_target_ready(restore_point_id)

    def _refuse_during_managed_update(self, agent: Agent) -> None:
        if managed_update_in_flight(agent):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=MANAGED_UPDATE_IN_FLIGHT_DETAIL)

    def _await_agent_volume_release(self, agent_id: UUID) -> None:
        """Block until no Agent pod holds the volume, or refuse.

        Stopping deletes the Deployment and returns; the pod lingers for its grace
        period while the Agent already reads as STOPPED. The volume is ReadWriteOnce
        but local-path is a bind mount, so nothing stops a Job pod mounting it
        alongside a dying Agent and archiving or wiping a directory still being
        written. Waiting outside the lifecycle lock keeps start and stop responsive.
        """
        deadline = time.monotonic() + RESTORE_POINT_POD_TERMINATION_TIMEOUT_SECONDS
        while self.k8s.has_pods_for_deployment(f"agent-{agent_id}", self.config.k8s_namespace):
            if time.monotonic() >= deadline:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=STILL_SHUTTING_DOWN_DETAIL)
            time.sleep(RESTORE_POINT_POD_TERMINATION_POLL_SECONDS)

    def _assert_capturable(self, agent: Agent, origin: RestorePointOrigin) -> None:
        """Refuse a capture, or make room for it. A scheduled snapshot in progress is stopped
        last, once nothing else refuses, so a refused capture never costs the schedule one."""
        if agent.status == AgentStatus.RUNNING:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=AGENT_RUNNING_DETAIL)

        # Only what a user takes is refused at the limit. A backup taken before an update makes
        # room for itself afterwards (see enforce_retention), so an update is never blocked by it.
        cap = self.config.restore_point_max_per_agent
        count = self.repository.count_manual_for_agent(agent.id)
        if origin == RestorePointOrigin.MANUAL and count >= cap:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This Agent has reached its limit of {cap} restore points ({count} of {cap}). Delete one first.",
            )

        if self.k8s.get_pvc(f"agent-{agent.id}", self.config.k8s_namespace) is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=NOTHING_TO_CAPTURE_DETAIL)

        if self.repository.find_owing_replay_for_agent(agent.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CAPTURE_IN_FLIGHT_DETAIL)
        self._cancel_scheduled_captures(agent)
        if self.repository.has_agent_volume_operation(agent.id):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CAPTURE_IN_FLIGHT_DETAIL)

    def _capture_job(self, agent: Agent, restore_point: AgentRestorePoint, beside_running_agent: bool) -> V1Job:
        return build_capture_job(
            job_name=restore_point.job_name or capture_job_name(restore_point.id),
            restore_point_id=restore_point.id,
            agent_id=agent.id,
            org_id=agent.organization_id,
            namespace=self.config.k8s_namespace,
            image=self.config.api_image,
            runtime=agent.agent_type,
            agent_pvc=f"agent-{agent.id}",
            dest_pvc=restore_point.pvc_name,
            timeout_seconds=self.config.restore_point_capture_timeout_seconds,
            image_pull_secret=self.config.agent_image_pull_secret or None,
            beside_running_agent=beside_running_agent,
        )

    def _provision_backup(self, agent: Agent, restore_point: AgentRestorePoint, job: V1Job) -> None:
        """Create the volume a capture is written to, then the Job that writes it."""
        namespace = self.config.k8s_namespace
        try:
            self.k8s.create_pvc(
                namespace,
                build_restore_point_pvc(
                    restore_point.id,
                    agent.id,
                    agent.organization_id,
                    namespace,
                    self.config.restore_point_size,
                    self.config.storage_class or None,
                ),
            )
            self.k8s.create_job(namespace, job)
        except Exception as exc:
            # friendly_k8s_error drops the cluster's own text, and RESOURCE_REJECTED
            # carries no detail, so which field the apiserver refused survives only here.
            logger.exception(
                "Could not provision the capture for restore point %s on agent %s", restore_point.id, agent.id
            )
            restore_point.status = RestorePointStatus.FAILED
            restore_point.failure_reason = friendly_k8s_error(exc, operation=AgentProvisioningOperation.BACKUP)
            self.repository.save(restore_point)
            self.k8s.delete_pvc(restore_point.pvc_name, namespace)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=restore_point.failure_reason,
            ) from exc

    def _build_config_manifest(self, agent: Agent) -> RestorePointConfigManifest:
        """The Agent's pins at capture time, shaped for display and replay.

        Resolved the same way the Agent read DTO resolves them, so a client can
        diff the two without mapping between vocabularies.
        """
        pin = self.template_repository.get_pinned_template_info_for_agents([agent]).get(agent.id)
        template_key, template_version, _, override_version = pin or ("", 0, "", None)
        return RestorePointConfigManifest(
            agent_type=agent.agent_type,
            template_key=template_key,
            template_version=template_version,
            template_selection_type=_selection_type(agent),
            override_version=override_version,
            model=agent.model or "",
            effective_model=agent.running_model or agent.model or "",
            approval_mode=agent.approval_mode,
            verbose_mode=agent.verbose_mode,
            max_turns=agent.max_turns,
            skills=[
                RestorePointSkill(skill_id=skill.id, name=skill.name, pinned_version=row.pinned_version)
                for row, skill in self.skill_repository.get_agent_skills_with_details(agent.id)
            ],
        )

    def _read_scope(self, agent_id: UUID, context: CurrentUserContext):
        agent = self.agent_authorization.require_visible(context, agent_id)
        return self.agent_authorization.require_action_for_visible(context, agent, PermissionKey.ACTIVITY_READ)

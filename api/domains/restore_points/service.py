import enum
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid7

from fastapi import HTTPException, status
from injector import inject, singleton
from kubernetes.client import V1Job

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.builders.restore_point import (
    build_capture_job,
    build_restore_job,
    build_restore_point_pvc,
    restore_point_resource_name,
)
from api.domains.agents.error_messages import friendly_k8s_error
from api.domains.agents.models import Agent, AgentRestorePoint, AgentStatus, RestorePointOrigin, RestorePointStatus
from api.domains.agents.override_repository import AgentOverrideRepository
from api.domains.agents.provisioning_errors import AgentProvisioningOperation
from api.domains.agents.repository import AgentRepository
from api.domains.agents.restore_point_job import EXIT_BACKUP_FAILED, EXIT_RESTORE_FAILED
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
from api.domains.restore_points.models import (
    NON_TERMINAL_STATUSES,
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

RESTORE_POINT_RECONCILIATION_PENDING_GRACE_SECONDS = 60

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


def _capture_job_name(restore_point_id: UUID) -> str:
    return f"rp-cap-{restore_point_id}"


def _restore_job_name(restore_point_id: UUID) -> str:
    return f"rp-res-{restore_point_id}-{secrets.token_hex(3)}"


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


def _deadline_exceeded(job: V1Job) -> bool:
    conditions = job.status.conditions if job.status is not None else None
    return any(c.type == "Failed" and c.status == "True" and c.reason == "DeadlineExceeded" for c in conditions or [])


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
        context: CurrentUserContext,
    ) -> dict:
        return {
            "organization_id": agent.organization_id,
            "agent_id": agent.id,
            "agent_name": agent.name,
            "restore_point_id": restore_point.id,
            "origin": restore_point.origin,
            "label": restore_point.label,
            "actor_display": context.user.full_name or context.user.email,
            "subject_display": agent.name,
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

    def _reconcile_row(self, row: AgentRestorePoint) -> None:
        namespace = self.config.k8s_namespace
        if not row.job_name:
            self._resolve_untracked(row, "The restore point has no job to track.")
            return

        job = self.k8s.get_job(row.job_name, namespace)
        if job is None:
            self._resolve_untracked(row, "The job that was running this operation is no longer available.")
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

    def _resolve_untracked(self, row: AgentRestorePoint, reason: str) -> None:
        """Resolve a row with no Job to read — but only once it has had time to get one.

        A row is committed before its Job is created, so a read landing in that
        window would otherwise fail a healthy operation. Past the grace window a
        missing Job is genuine. A restore target keeps its volume; a capture
        releases the one it never finished writing.
        """
        grace = timedelta(seconds=RESTORE_POINT_RECONCILIATION_PENDING_GRACE_SECONDS)
        if row.updated_at > datetime.now(UTC) - grace:
            return
        if row.status == RestorePointStatus.RESTORING:
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

        outcome = self._restore_outcome(row.job_name or "", namespace)
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
            else:
                self._fail(row, reason)
            return

        if outcome == _RestoreOutcome.EXTRACTION_FAILED:
            self._succeed(row)
        elif outcome == _RestoreOutcome.BACKUP_FAILED:
            self._fail_capture(row, reason)
        else:
            self._fail(row, reason)

    def _restore_outcome(self, job_name: str, namespace: str) -> _RestoreOutcome:
        if self.k8s.get_pod_name_for_job(job_name, namespace) is None:
            return _RestoreOutcome.UNKNOWN
        exit_code = self.k8s.get_job_exit_code(job_name, namespace)
        if exit_code == EXIT_BACKUP_FAILED:
            return _RestoreOutcome.BACKUP_FAILED
        if exit_code == EXIT_RESTORE_FAILED:
            return _RestoreOutcome.EXTRACTION_FAILED
        logs = self.k8s.read_job_logs(job_name, namespace)
        if logs is None:
            return _RestoreOutcome.UNKNOWN
        if _parse_manifest(logs):
            return _RestoreOutcome.EXTRACTION_FAILED
        return _RestoreOutcome.BACKUP_FAILED

    def _failure_reason(self, row: AgentRestorePoint, job: V1Job, namespace: str) -> str:
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

    def _fail(self, row: AgentRestorePoint, reason: str) -> None:
        self.repository.mark_failed(row.id, reason[:_MAX_FAILURE_REASON])

    def _fail_capture(self, row: AgentRestorePoint, reason: str) -> None:
        """Fail a capture and release the volume it was writing into.

        A capture that never finished leaves no usable archive, so its destination
        volume is dead weight. A row failing as a *restore target* keeps its
        volume: that archive is intact and is what the retry reads from.
        """
        self._fail(row, reason)
        if row.pvc_name:
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
                return lines[-1]
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
    ) -> AgentRestorePointRead:
        agent = self.agent_authorization.require_action(context, agent_id, PermissionKey.AGENT_LIFECYCLE_MANAGE)

        with self.agent_repository.lifecycle_lock(agent.id) as acquired:
            if not acquired:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CAPTURE_IN_FLIGHT_DETAIL)

            current = self.agent_repository.get_by_id(agent.id)
            if current is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Agent {agent_id} not found",
                )
            self._assert_capturable(current)

            restore_point_id = uuid7()
            restore_point = AgentRestorePoint(
                id=restore_point_id,
                agent_id=current.id,
                created_by_user_id=context.user.id,
                label=payload.label,
                status=RestorePointStatus.PENDING,
                origin=RestorePointOrigin.MANUAL,
                agent_type=current.agent_type,
                pvc_name=restore_point_resource_name(restore_point_id),
                job_name=_capture_job_name(restore_point_id),
                config_manifest=self._build_config_manifest(current).model_dump(mode="json"),
            )
            result = self.repository.save_with_event(
                restore_point,
                event_name=AGENT_RESTORE_POINT_CREATED,
                actor=resolve_actor_identity(context, current.organization_id),
                payload=self._event_payload(current, restore_point, context),
            )

            self._provision_capture(current, restore_point)

        self._dispatch(result.delivery_ids)
        return AgentRestorePointRead.model_validate(restore_point)

    def restore_restore_point(
        self,
        agent_id: UUID,
        restore_point_id: UUID,
        payload: AgentRestorePointRestore,
        context: CurrentUserContext,
    ) -> AgentRestorePointRead:
        agent = self.agent_authorization.require_action(context, agent_id, PermissionKey.AGENT_LIFECYCLE_MANAGE)
        scope = self.agent_authorization.authorization_scope(context, PermissionKey.ACTIVITY_READ)

        with self.agent_repository.lifecycle_lock(agent.id) as acquired:
            if not acquired:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CAPTURE_IN_FLIGHT_DETAIL)

            current = self.agent_repository.get_by_id(agent.id)
            if current is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Agent {agent_id} not found")
            if current.status == AgentStatus.RUNNING:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=AGENT_RUNNING_RESTORE_DETAIL)

            target = self.repository.get_in_scope(restore_point_id, agent_id, scope)
            if target is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Restore point {restore_point_id} not found",
                )
            if target.status != RestorePointStatus.READY:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=NOT_READY_DETAIL)
            if self.repository.has_non_terminal_operation(agent_id) or self.repository.find_owing_replay_for_agent(
                agent_id
            ):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CAPTURE_IN_FLIGHT_DETAIL)

            if payload.reapply_configuration:
                # Authorized here, applied later: the write happens in reconciliation
                # once the Job confirms the volume is back, so the permission for it
                # has to be settled while the requester is still on the call.
                self.agent_authorization.require_action_for_visible(context, current, PermissionKey.AGENT_UPDATE)
                # Before the Job, not after it: a configuration that cannot be applied
                # must not cost the Agent its files first.
                self._validate_recorded_configuration(current, target)

            job_name = _restore_job_name(target.id)
            backup = self._create_pre_restore_row(current, job_name)
            result = self.repository.update_status_with_event(
                target.id,
                RestorePointStatus.RESTORING,
                from_statuses=(RestorePointStatus.READY,),
                job_name=job_name,
                event_name=AGENT_RESTORE_POINT_RESTORED,
                actor=resolve_actor_identity(context, current.organization_id),
                payload=self._event_payload(current, target, context),
                reapply_configuration=payload.reapply_configuration,
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

            target = self.repository.get_in_scope(restore_point_id, agent_id, scope)
            if target is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Restore point {restore_point_id} not found",
                )

            if self.repository.has_non_terminal_operation(agent_id) or self.repository.find_owing_replay_for_agent(
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
        backup: AgentRestorePoint,
        job_name: str,
    ) -> None:
        namespace = self.config.k8s_namespace
        try:
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
                    agent_id=agent.id,
                    org_id=agent.organization_id,
                    namespace=namespace,
                    image=self.config.api_image,
                    runtime=agent.agent_type,
                    agent_pvc=f"agent-{agent.id}",
                    backup_pvc=backup.pvc_name,
                    archive_pvc=target.pvc_name,
                    timeout_seconds=self.config.restore_point_restore_timeout_seconds,
                    image_pull_secret=self.config.agent_image_pull_secret or None,
                ),
            )
        except Exception as exc:
            reason = friendly_k8s_error(exc, operation=AgentProvisioningOperation.RESTORE)
            self.repository.mark_failed(backup.id, reason[:_MAX_FAILURE_REASON])
            self.repository.mark_restored(target.id, cancel_replay=True)
            self.k8s.delete_pvc(backup.pvc_name, namespace)
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

        namespace = self.config.k8s_namespace
        if restore_point.job_name:
            self.k8s.delete_job(restore_point.job_name, namespace)
        if restore_point.pvc_name:
            self.k8s.delete_pvc(restore_point.pvc_name, namespace)

        delivery_ids = self.repository.delete_with_event(
            restore_point,
            event_name=AGENT_RESTORE_POINT_DELETED,
            actor=resolve_actor_identity(context, agent.organization_id),
            payload=self._event_payload(agent, restore_point, context),
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
        rather than blocking the Agent — and its Organization — forever.
        """
        self.reconcile_agent(agent_id)
        return self.repository.has_non_terminal_operation(agent_id) or bool(
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

    def _assert_capturable(self, agent: Agent) -> None:
        if agent.status == AgentStatus.RUNNING:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=AGENT_RUNNING_DETAIL)

        if self.repository.has_non_terminal_operation(agent.id) or self.repository.find_owing_replay_for_agent(
            agent.id
        ):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CAPTURE_IN_FLIGHT_DETAIL)

        cap = self.config.restore_point_max_per_agent
        count = self.repository.count_manual_for_agent(agent.id)
        if count >= cap:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"This Agent has reached its limit of {cap} restore points ({count} of {cap}). Delete one first.",
            )

        if self.k8s.get_pvc(f"agent-{agent.id}", self.config.k8s_namespace) is None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=NOTHING_TO_CAPTURE_DETAIL)

    def _provision_capture(self, agent: Agent, restore_point: AgentRestorePoint) -> None:
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
            self.k8s.create_job(
                namespace,
                build_capture_job(
                    job_name=restore_point.job_name or _capture_job_name(restore_point.id),
                    agent_id=agent.id,
                    org_id=agent.organization_id,
                    namespace=namespace,
                    image=self.config.api_image,
                    runtime=agent.agent_type,
                    agent_pvc=f"agent-{agent.id}",
                    dest_pvc=restore_point.pvc_name,
                    timeout_seconds=self.config.restore_point_capture_timeout_seconds,
                    image_pull_secret=self.config.agent_image_pull_secret or None,
                ),
            )
        except Exception as exc:
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
            skills=[
                RestorePointSkill(skill_id=skill.id, name=skill.name, pinned_version=row.pinned_version)
                for row, skill in self.skill_repository.get_agent_skills_with_details(agent.id)
            ],
        )

    def _read_scope(self, agent_id: UUID, context: CurrentUserContext):
        agent = self.agent_authorization.require_visible(context, agent_id)
        return self.agent_authorization.require_action_for_visible(context, agent, PermissionKey.ACTIVITY_READ)

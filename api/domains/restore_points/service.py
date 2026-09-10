import json
import logging
import secrets
from dataclasses import dataclass
from uuid import UUID, uuid7

from fastapi import HTTPException, status
from injector import inject, singleton

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
from api.domains.agents.repository import AgentRepository
from api.domains.agents.restore_point_job import EXIT_BACKUP_FAILED, EXIT_RESTORE_FAILED
from api.domains.auth.models import CurrentUserContext
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
    AgentRestorePointRead,
    RestorePointConfigManifest,
)
from api.domains.restore_points.repository import RestorePointRepository
from api.infrastructure.kubernetes import KubernetesClient
from api.infrastructure.shared.models import PaginatedItems, Pagination

logger = logging.getLogger(__name__)

_MAX_FAILURE_REASON = 500

NOTHING_TO_CAPTURE_DETAIL = "This Agent has never run, so there is nothing to capture."
AGENT_RUNNING_DETAIL = "Stop the Agent before capturing a restore point."
AGENT_RUNNING_RESTORE_DETAIL = "Stop the Agent before restoring a restore point."
CAPTURE_IN_FLIGHT_DETAIL = "A restore point operation is already in progress for this Agent."
NOT_READY_DETAIL = "Only a ready restore point can be restored."
DELETE_IN_FLIGHT_DETAIL = "This restore point is still being worked on. Wait for it to finish, then delete it."
PRE_RESTORE_LABEL = "Automatic backup before restore"


def _capture_job_name(restore_point_id: UUID) -> str:
    return f"rp-cap-{restore_point_id}"


def _restore_job_name(restore_point_id: UUID) -> str:
    return f"rp-res-{restore_point_id}-{secrets.token_hex(3)}"


@inject
@singleton
@dataclass
class RestorePointService:
    config: Config
    repository: RestorePointRepository
    agent_repository: AgentRepository
    agent_authorization: AgentAuthorization
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
    ) -> PaginatedItems[AgentRestorePointRead]:
        scope = self._read_scope(agent_id, context)
        self.reconcile_agent(agent_id)
        return self.repository.find_by_agent(agent_id, pagination, scope)

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

    def _reconcile_row(self, row: AgentRestorePoint) -> None:
        namespace = self.config.k8s_namespace
        if not row.job_name:
            self._fail_capture(row, "The restore point has no job to track.")
            return

        job = self.k8s.get_job(row.job_name, namespace)
        if job is None:
            reason = "The job that was running this operation is no longer available."
            if row.status == RestorePointStatus.RESTORING:
                self._fail(row, reason)
            else:
                self._fail_capture(row, reason)
            return

        status_block = job.status
        if status_block is None:
            return

        if status_block.succeeded:
            if row.status == RestorePointStatus.RESTORING:
                self.repository.mark_restored(row.id)
            else:
                self._succeed(row)
            return

        if status_block.failed:
            self._resolve_failure(row, namespace)
            return

        if row.status == RestorePointStatus.PENDING and status_block.active:
            self.repository.update_status(
                row.id, RestorePointStatus.CAPTURING, from_statuses=(RestorePointStatus.PENDING,)
            )

    def _resolve_failure(self, row: AgentRestorePoint, namespace: str) -> None:
        """Split a restore Job's failure across the two rows it serves.

        Exit 2 means the safety-net capture failed and the Agent volume was never
        touched, so the restore point being restored from is still intact. Exit 3
        means the wipe-and-extract failed, leaving the volume mid-restore: the
        safety net exists and is the recovery path.
        """
        exit_code = self.k8s.get_job_exit_code(row.job_name or "", namespace)
        reason = self._job_failure_reason(row.job_name or "", namespace)

        if row.status == RestorePointStatus.RESTORING:
            if exit_code == EXIT_BACKUP_FAILED:
                self.repository.mark_restored(row.id)
            else:
                self._fail(row, reason)
            return

        if row.origin == RestorePointOrigin.PRE_RESTORE and exit_code == EXIT_RESTORE_FAILED:
            self._succeed(row)
            return

        self._fail_capture(row, reason)

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
        if not logs:
            return {}
        for line in reversed(logs.splitlines()):
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                parsed = json.loads(line)
            except ValueError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return {}

    def _job_failure_reason(self, job_name: str, namespace: str) -> str:
        logs = self.k8s.read_job_logs(job_name, namespace)
        if logs:
            lines = [line.strip() for line in logs.splitlines() if line.strip()]
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
            if self.repository.has_non_terminal_operation(agent_id):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=CAPTURE_IN_FLIGHT_DETAIL)

            job_name = _restore_job_name(target.id)
            backup = self._create_pre_restore_row(current, job_name)
            result = self.repository.update_status_with_event(
                target.id,
                RestorePointStatus.RESTORING,
                from_statuses=(RestorePointStatus.READY,),
                event_name=AGENT_RESTORE_POINT_RESTORED,
                actor=resolve_actor_identity(context, current.organization_id),
                payload=self._event_payload(current, target, context),
            )
            if result is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=NOT_READY_DETAIL)
            self.repository.set_job_name(target.id, job_name)

            self._provision_restore(current, target, backup, job_name)

        self._dispatch(result.delivery_ids)

        refreshed = self.repository.get_in_scope(restore_point_id, agent_id, scope)
        return AgentRestorePointRead.model_validate(refreshed or target)

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
            reason = friendly_k8s_error(exc)
            self.repository.mark_failed(backup.id, reason[:_MAX_FAILURE_REASON])
            self.repository.mark_restored(target.id)
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
        if restore_point.status in NON_TERMINAL_STATUSES:
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
        """True when a capture or restore is genuinely still running.

        Reconciles first so a finished or ttl-reaped Job resolves to terminal
        rather than blocking the Agent — and its Organization — forever.
        """
        self.reconcile_agent(agent_id)
        return self.repository.has_non_terminal_operation(agent_id)

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

        if self.repository.has_non_terminal_operation(agent.id):
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
            restore_point.failure_reason = friendly_k8s_error(exc)
            self.repository.save(restore_point)
            self.k8s.delete_pvc(restore_point.pvc_name, namespace)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=restore_point.failure_reason,
            ) from exc

    def _build_config_manifest(self, agent: Agent) -> RestorePointConfigManifest:
        return RestorePointConfigManifest(
            agent_type=agent.agent_type,
            model=agent.model or "",
            effective_model=agent.running_model or agent.model or "",
            approval_mode=agent.approval_mode,
            verbose_mode=agent.verbose_mode,
        )

    def _read_scope(self, agent_id: UUID, context: CurrentUserContext):
        agent = self.agent_authorization.require_visible(context, agent_id)
        return self.agent_authorization.require_action_for_visible(context, agent, PermissionKey.ACTIVITY_READ)

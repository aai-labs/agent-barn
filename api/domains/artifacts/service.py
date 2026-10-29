import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.artifacts.buckets import ArtifactBucketRepository
from api.domains.artifacts.models import Artifact, ArtifactCreate, ArtifactLinkRead, ArtifactRead, ArtifactStorageRead
from api.domains.artifacts.repository import ArtifactRepository, PublicationBusy
from api.domains.artifacts.storage import (
    ArtifactCredentialsUnavailable,
    ArtifactDownload,
    ArtifactStorage,
    DownloadDenied,
    PreviousArtifactStorage,
)
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import AuthorizationScope
from api.domains.workflows.repository import WorkflowConflict
from api.infrastructure.shared.models import PaginatedItems

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class ArtifactService:
    repository: ArtifactRepository
    authorization: AgentAuthorization
    storage: ArtifactStorage
    config: Config
    buckets: ArtifactBucketRepository

    def scope(self, agent_id: UUID, context: CurrentUserContext, write: bool = False) -> AuthorizationScope:
        if write:
            self.authorization.require_action(context, agent_id, PermissionKey.AGENT_UPDATE)
        else:
            self.authorization.require_visible(context, agent_id)
        return self.authorization.authorization_scope(
            context, PermissionKey.AGENT_UPDATE if write else PermissionKey.AGENT_READ
        )

    def storage_status(self, agent_id: UUID, context: CurrentUserContext) -> ArtifactStorageRead:
        scope = self.scope(agent_id, context)
        if not self.config.artifact_s3_endpoint_url:
            return ArtifactStorageRead(state="NOT_CONFIGURED")
        row = self.buckets.status(agent_id, scope.organization_id)
        if row is None or row.state == "DELETED":
            return ArtifactStorageRead(state="NOT_PROVISIONED")
        if row.state == "READY":
            return ArtifactStorageRead(state="READY")
        return ArtifactStorageRead(state="FAILED" if row.last_error or row.state == "DELETING" else "PROVISIONING")

    def request_storage(self, agent_id: UUID, context: CurrentUserContext) -> ArtifactStorageRead:
        scope = self.scope(agent_id, context, True)
        self.enabled()
        try:
            self.buckets.reserve(agent_id, scope.organization_id)
        except ValueError:
            raise HTTPException(409, "Agent storage cannot be provisioned") from None
        return self.storage_status(agent_id, context)

    def runtime_scope(self, token: str) -> tuple[UUID, AuthorizationScope]:
        agent = self.repository.authenticate(token)
        return agent.id, AuthorizationScope(organization_id=agent.organization_id)

    def enabled(self) -> None:
        if not self.config.artifact_s3_endpoint_url:
            raise HTTPException(503, "Artifact storage is not configured; text-only operation remains available")

    def create(
        self,
        agent_id: UUID,
        scope: AuthorizationScope,
        payload: ArtifactCreate,
        *,
        user_id: UUID | None = None,
        attempt_id: UUID | None = None,
    ) -> ArtifactRead:
        self.enabled()
        if payload.size > self.config.artifact_max_bytes:
            raise HTTPException(413, "Artifact exceeds the configured file limit")
        try:
            row = self.repository.create(
                agent_id,
                scope,
                payload,
                "workflow" if attempt_id else "human" if user_id else "chat",
                user_id,
                attempt_id,
            )
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        return ArtifactRead.model_validate(row)

    def upload_limit(
        self, artifact_id: UUID, agent_id: UUID, scope: AuthorizationScope, *, runtime: bool = False
    ) -> int:
        self.enabled()
        row = self.repository.get(artifact_id, agent_id, scope)
        if row.attempt_id and not runtime:
            raise HTTPException(403, "Workflow publication requires the owning runtime credential")
        if row.state == "UPLOADING" and row.expires_at <= datetime.now(UTC):
            raise HTTPException(409, "Upload expired")
        if row.size > self.config.artifact_max_bytes:
            raise HTTPException(413, "Artifact exceeds the configured file limit")
        return row.size

    def publish(
        self,
        artifact_id: UUID,
        agent_id: UUID,
        scope: AuthorizationScope,
        content: bytes,
        *,
        runtime_token: str | None = None,
        human_context: CurrentUserContext | None = None,
    ) -> ArtifactRead:
        self.enabled()

        def revalidate() -> None:
            # Check rotated/stopped runtime credentials again after the byte boundary.
            if runtime_token is not None:
                self.repository.authenticate(runtime_token)
            if human_context is not None:
                membership_id = human_context.require_current_user_organization().id
                for permission in (PermissionKey.AGENT_READ, PermissionKey.AGENT_UPDATE):
                    current_scope = self.authorization.membership_scope(membership_id, permission)
                    if current_scope is None:
                        raise HTTPException(403, "Publication authority was revoked")
                    self.repository.get(artifact_id, agent_id, current_scope)

        admitted = False
        try:
            with self.repository.publication(
                artifact_id, agent_id, scope, runtime=runtime_token is not None, revalidate=revalidate
            ) as row:
                admitted = True
                if (
                    len(content) > self.config.artifact_max_bytes
                    or len(content) != row.size
                    or hashlib.sha256(content).hexdigest() != row.checksum
                ):
                    raise HTTPException(422, "File bytes do not match the declared size and SHA-256")
                if row.state != "READY":
                    self.storage.put(row, content)
            return ArtifactRead.model_validate(row)
        except PublicationBusy:
            raise
        except (HTTPException, WorkflowConflict) as exc:
            if admitted:
                self.repository.failed(artifact_id)
            if isinstance(exc, WorkflowConflict):
                raise HTTPException(409, str(exc)) from exc
            raise
        except Exception as exc:
            self.repository.failed(artifact_id)
            logger.warning("Artifact upload failed for %s (%s)", artifact_id, type(exc).__name__)
            raise HTTPException(503, "Artifact storage is unavailable; upload a new artifact to retry") from exc

    def list_ready(
        self,
        agent_id: UUID,
        scope: AuthorizationScope,
        page: int,
        size: int,
        run_id: UUID | None = None,
        step_id: UUID | None = None,
    ) -> PaginatedItems[ArtifactRead]:
        rows, total = self.repository.list_ready(agent_id, scope, page, size, run_id, step_id)
        return PaginatedItems(page, size, total, [ArtifactRead.model_validate(row) for row in rows])

    def ready(self, artifact_id: UUID, agent_id: UUID, scope: AuthorizationScope) -> Artifact:
        row = self.repository.get(artifact_id, agent_id, scope)
        if row.state != "READY":
            raise HTTPException(409, "Artifact is not ready")
        return row

    def link(
        self,
        artifact_id: UUID,
        agent_id: UUID,
        scope: AuthorizationScope,
        seconds: int = 900,
        *,
        attempt_id: UUID | None = None,
    ) -> ArtifactLinkRead:
        if attempt_id is not None:
            try:
                self.repository.authorize_workflow_read(artifact_id, attempt_id, agent_id)
            except WorkflowConflict as exc:
                raise HTTPException(409, str(exc)) from exc
        self.enabled()
        row = self.ready(artifact_id, agent_id, scope)
        if not 1 <= seconds <= self.config.artifact_link_max_seconds:
            raise HTTPException(422, "Download lifetime exceeds the configured bound")
        try:
            access = self.storage.issue_download(row, seconds)
        except PreviousArtifactStorage:
            raise HTTPException(
                409,
                "This file uses the previous storage layout and has not been migrated. "
                "It must be migrated or uploaded again before downloading. Newer files are unaffected.",
            ) from None
        except ArtifactCredentialsUnavailable:
            raise HTTPException(
                503,
                "Storage credentials for this file are unavailable. Ask an administrator to check Agent storage provisioning.",
            ) from None
        except Exception as exc:
            raise HTTPException(503, "Artifact storage is unavailable") from exc
        return ArtifactLinkRead(
            artifact=ArtifactRead.model_validate(row),
            url=(
                self.config.web_app_url.rstrip("/")
                + f"/api/v1/agent-artifacts/{row.organization_id}/{row.agent_id}/{row.id}?"
                + urlencode({"access": access})
            ),
            expires_at=datetime.now(UTC) + timedelta(seconds=seconds),
        )

    def download(self, organization_id: UUID, agent_id: UUID, artifact_id: UUID, access: str) -> ArtifactDownload:
        self.enabled()
        # This is a provider-capability read, not a user-authenticated metadata
        # route. Resolve only this persisted tenant target, then let the byte
        # store validate download authority before returning any file data.
        try:
            row = self.ready(artifact_id, agent_id, AuthorizationScope(organization_id=organization_id))
        except HTTPException:
            raise HTTPException(403, "Invalid or unavailable artifact download") from None
        try:
            return self.storage.download(row, access)
        except DownloadDenied:
            raise HTTPException(403, "Invalid or expired artifact download") from None
        except Exception:
            raise HTTPException(503, "Artifact storage is unavailable") from None

    def delete(self, artifact_id: UUID, agent_id: UUID, context: CurrentUserContext) -> None:
        self.repository.delete(artifact_id, agent_id, self.scope(agent_id, context, True))

    def purge(self, limit: int = 100) -> int:
        self.enabled()
        deleted = 0
        for artifact_id in self.repository.cleanup_candidates(limit):
            try:
                with self.repository.purge_target(artifact_id) as row:
                    if row is not None:
                        self.storage.delete(row)
                        deleted += 1
            except Exception as exc:
                logger.warning("Artifact purge will retry %s (%s)", artifact_id, type(exc).__name__)
        return deleted

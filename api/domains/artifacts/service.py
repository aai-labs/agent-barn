import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from injector import inject, singleton

from api.core.config import Config
from api.domains.agents.authorization import AgentAuthorization
from api.domains.artifacts.models import Artifact, ArtifactCreate, ArtifactLinkRead, ArtifactRead
from api.domains.artifacts.repository import ArtifactRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import AuthorizationScope
from api.domains.workflows.repository import WorkflowConflict
from api.infrastructure.s3.client import ArtifactStorage
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

    def scope(self, agent_id: UUID, context: CurrentUserContext, write: bool = False) -> AuthorizationScope:
        self.authorization.require_action(
            context, agent_id, PermissionKey.AGENT_UPDATE
        ) if write else self.authorization.require_visible(context, agent_id)
        return self.authorization.authorization_scope(
            context, PermissionKey.AGENT_UPDATE if write else PermissionKey.AGENT_READ
        )

    def runtime_scope(self, token: str) -> tuple[UUID, AuthorizationScope]:
        agent = self.repository.authenticate(token)
        return agent.id, AuthorizationScope(organization_id=agent.organization_id)

    def enabled(self) -> None:
        if not self.config.artifact_s3_bucket:
            raise HTTPException(503, "Artifact storage is not configured; text-only operation remains available")

    def create(
        self,
        agent_id: UUID,
        scope: AuthorizationScope,
        payload: ArtifactCreate,
        *,
        user_id: UUID | None = None,
        attempt_id: UUID | None = None,
        attempt_token: str = "",
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
                attempt_token,
            )
        except WorkflowConflict as exc:
            raise HTTPException(409, str(exc)) from exc
        return ArtifactRead.model_validate(row)

    def publish(
        self,
        artifact_id: UUID,
        agent_id: UUID,
        scope: AuthorizationScope,
        content: bytes,
        *,
        attempt_token: str = "",
        runtime_token: str | None = None,
        human_context: CurrentUserContext | None = None,
    ) -> ArtifactRead:
        self.enabled()
        admitted = False
        try:
            with self.repository.publication(artifact_id, agent_id, scope, attempt_token) as row:
                admitted = True
                if (
                    len(content) > self.config.artifact_max_bytes
                    or len(content) != row.size
                    or hashlib.sha256(content).hexdigest() != row.checksum
                ):
                    raise HTTPException(422, "File bytes do not match the declared size and SHA-256")
                if row.state != "READY":
                    self.storage.put(row, content)
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
            return ArtifactRead.model_validate(row)
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
        self, artifact_id: UUID, agent_id: UUID, scope: AuthorizationScope, seconds: int = 900
    ) -> ArtifactLinkRead:
        self.enabled()
        row = self.ready(artifact_id, agent_id, scope)
        if not 1 <= seconds <= self.config.artifact_link_max_seconds:
            raise HTTPException(422, "Download lifetime exceeds the configured bound")
        try:
            url = self.storage.link(row, seconds)
        except Exception as exc:
            raise HTTPException(503, "Artifact storage is unavailable") from exc
        return ArtifactLinkRead(
            artifact=ArtifactRead.model_validate(row),
            url=url,
            expires_at=datetime.now(UTC) + timedelta(seconds=seconds),
        )

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

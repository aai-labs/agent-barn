import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import Agent
from api.domains.auth.models import CurrentUserContext
from api.domains.events import EventDeliveryDispatcher, resolve_actor_identity
from api.domains.playbooks.models import (
    PlaybookExtraction,
    PlaybookExtractionCreate,
    PlaybookExtractionDetailRead,
    PlaybookExtractionError,
    PlaybookExtractionFilter,
    PlaybookExtractionRead,
)
from api.domains.playbooks.repository import ActiveExtractionExists, PlaybookExtractionRepository
from api.domains.playbooks.transport import PlaybookExtractionQueue
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.policy import AuthorizationScope, PermissionPolicy
from api.domains.skills.service import SkillService
from api.infrastructure.shared.models import PaginatedItems, Pagination

logger = logging.getLogger(__name__)

_NO_SKILL_MANAGE = "Only Organization Owners and Admins can extract playbooks."
_NO_ACTIVITY_READ = "You don't have permission to read this Agent's activity."


@inject
@singleton
@dataclass
class PlaybookExtractionService:
    """Playbook Extractions read an Agent's transcripts and write an Organization Skill.

    Every operation therefore needs both the Agent Permission ``activity.read`` on the
    source Agent and the Organization Permission ``skill.manage``.
    """

    repository: PlaybookExtractionRepository
    authorization: AgentAuthorization
    policy: PermissionPolicy
    skills: SkillService
    queue: PlaybookExtractionQueue
    event_delivery_dispatcher: EventDeliveryDispatcher

    def create(
        self, agent_id: UUID, data: PlaybookExtractionCreate, context: CurrentUserContext
    ) -> PlaybookExtractionRead:
        agent, _ = self._require_extractor(context, agent_id)
        if data.skill_id is not None:
            skill_name = self.skills.require_playbook_target(agent.organization_id, data.skill_id).name
        else:
            skill_name = data.skill_name or ""
            self.skills.require_available_organization_skill_name(agent.organization_id, skill_name)
        membership = context.require_current_user_organization()
        now = datetime.now(UTC)
        extraction = PlaybookExtraction(
            organization_id=agent.organization_id,
            source_agent_id=agent.id,
            requested_by_membership_id=membership.id,
            requested_by_user_id=context.user.id,
            skill_id=data.skill_id,
            skill_name=skill_name,
            window_start=now - timedelta(days=data.window_days),
            window_end=now,
            max_sessions=data.max_sessions,
            created_at=now,
            updated_at=now,
        )
        try:
            created = self.repository.create_with_event(
                extraction,
                window_days=data.window_days,
                actor=resolve_actor_identity(context, agent.organization_id),
                actor_display=context.user.full_name or context.user.email,
                subject_display=agent.name,
            )
        except ActiveExtractionExists:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A playbook extraction is already running for this Agent.",
            ) from None
        self.event_delivery_dispatcher.enqueue_immediate(created.delivery_ids)
        try:
            self.queue.enqueue(created.extraction.id)
        except Exception as exc:
            logger.warning("Playbook extraction %s could not be queued: %s", created.extraction.id, type(exc).__name__)
            self.repository.fail(created.extraction.id, PlaybookExtractionError.ENQUEUE_FAILED)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The playbook extraction could not be started. Try again later.",
            ) from None
        return PlaybookExtractionRead.model_validate(created.extraction)

    def list_for_agent(
        self, agent_id: UUID, pagination: Pagination, context: CurrentUserContext
    ) -> PaginatedItems[PlaybookExtractionRead]:
        agent, scope = self._require_extractor(context, agent_id)
        return self.repository.find_for_agent(agent.id, pagination, scope)

    def list_for_organization(
        self, extraction_filter: PlaybookExtractionFilter, pagination: Pagination, context: CurrentUserContext
    ) -> PaginatedItems[PlaybookExtractionRead]:
        organization_id = context.require_current_user_organization().organization_id
        self.policy.require_organization(context, organization_id, PermissionKey.SKILL_MANAGE, detail=_NO_SKILL_MANAGE)
        scope = self.authorization.authorization_scope(context, PermissionKey.ACTIVITY_READ)
        return self.repository.find_in_organization(extraction_filter, pagination, scope)

    def get(self, agent_id: UUID, extraction_id: UUID, context: CurrentUserContext) -> PlaybookExtractionDetailRead:
        agent, scope = self._require_extractor(context, agent_id)
        return PlaybookExtractionDetailRead.model_validate(self._get_or_404(extraction_id, agent.id, scope))

    def cancel(self, agent_id: UUID, extraction_id: UUID, context: CurrentUserContext) -> PlaybookExtractionRead:
        agent, scope = self._require_extractor(context, agent_id)
        self._get_or_404(extraction_id, agent.id, scope)
        cancelled = self.repository.cancel(extraction_id)
        if cancelled is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This playbook extraction has already finished.",
            )
        return PlaybookExtractionRead.model_validate(cancelled)

    def _require_extractor(self, context: CurrentUserContext, agent_id: UUID) -> tuple[Agent, AuthorizationScope]:
        agent = self.authorization.require_action(
            context, agent_id, PermissionKey.ACTIVITY_READ, detail=_NO_ACTIVITY_READ
        )
        self.policy.require_organization(
            context, agent.organization_id, PermissionKey.SKILL_MANAGE, detail=_NO_SKILL_MANAGE
        )
        return agent, self.authorization.authorization_scope(context, PermissionKey.ACTIVITY_READ)

    def _get_or_404(self, extraction_id: UUID, agent_id: UUID, scope: AuthorizationScope) -> PlaybookExtraction:
        extraction = self.repository.get_in_scope(extraction_id, agent_id, scope)
        if extraction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Playbook extraction {extraction_id} not found",
            )
        return extraction

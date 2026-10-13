import logging
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.repository import AgentRepository
from api.domains.playbooks.models import PlaybookExtraction, PlaybookExtractionError
from api.domains.playbooks.pipeline import PlaybookExtractionFailed, PlaybookPipeline
from api.domains.playbooks.repository import PlaybookExtractionRepository
from api.domains.rbac.catalog import PermissionKey, organization_role_allows

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class PlaybookExtractionProcessor:
    """Runs one accepted extraction in the worker.

    A person started the run, so it is not background work under the RBAC brief: it
    acts only while the requesting Membership still holds both Permissions the
    request needed, checked when the run starts.
    """

    repository: PlaybookExtractionRepository
    agents: AgentRepository
    authorization: AgentAuthorization
    pipeline: PlaybookPipeline

    def process(self, extraction_id: UUID) -> None:
        extraction = self.repository.claim(extraction_id)
        if extraction is None:
            return
        try:
            self._require_authority(extraction)
            self.pipeline.run(extraction)
        except PlaybookExtractionFailed as exc:
            self.repository.fail(extraction.id, exc.error)
            logger.info("Playbook extraction %s failed: %s", extraction.id, exc.error.value)
        except Exception as exc:
            # Exception text can quote transcripts or model output; log only its type.
            logger.error("Playbook extraction %s failed unexpectedly: %s", extraction.id, type(exc).__name__)
            self.repository.fail(extraction.id, PlaybookExtractionError.INTERNAL_ERROR)

    def _require_authority(self, extraction: PlaybookExtraction) -> None:
        agent = self.agents.get_by_id(extraction.source_agent_id)
        if agent is None or agent.organization_id != extraction.organization_id:
            raise PlaybookExtractionFailed(PlaybookExtractionError.SOURCE_AGENT_UNAVAILABLE)
        membership_id = extraction.requested_by_membership_id
        found = self.agents.find_membership_with_user(membership_id) if membership_id else None
        if (
            found is None
            or found[1] is None
            or found[0].organization_id != extraction.organization_id
            or not organization_role_allows(found[0].role, PermissionKey.SKILL_MANAGE)
            or not self.authorization.membership_has_permission(
                found[0].id, extraction.source_agent_id, PermissionKey.ACTIVITY_READ
            )
        ):
            raise PlaybookExtractionFailed(PlaybookExtractionError.REQUESTER_LOST_ACCESS)

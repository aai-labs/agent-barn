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
from api.domains.rbac.policy import AuthorizationScope

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
            # A redelivered message after a worker died: fail the run it left behind.
            self.repository.expire_abandoned(extraction_id=extraction_id)
            return
        try:
            self.pipeline.run(extraction, self._require_authority(extraction))
        except PlaybookExtractionFailed as exc:
            self.repository.fail(extraction.id, exc.error, **exc.values)
            logger.info("Playbook extraction %s failed: %s", extraction.id, exc.error.value)
        except Exception as exc:
            # Exception text can quote transcripts or model output; log only its type.
            logger.error("Playbook extraction %s failed unexpectedly: %s", extraction.id, type(exc).__name__)
            self.repository.fail(extraction.id, PlaybookExtractionError.INTERNAL_ERROR)
        except BaseException as exc:
            # Dramatiq's time limit and worker shutdown raise BaseException subclasses.
            # Record the run as interrupted, then let the worker handle the interruption.
            logger.warning("Playbook extraction %s interrupted: %s", extraction.id, type(exc).__name__)
            self.repository.fail(extraction.id, PlaybookExtractionError.INTERRUPTED)
            raise

    def _require_authority(self, extraction: PlaybookExtraction) -> AuthorizationScope:
        """The requester's Agent visibility scope, if they still hold both Permissions."""
        agent = self.agents.get_by_id(extraction.source_agent_id)
        if agent is None or agent.organization_id != extraction.organization_id:
            raise PlaybookExtractionFailed(PlaybookExtractionError.SOURCE_AGENT_UNAVAILABLE)
        membership_id = extraction.requested_by_membership_id
        found = self.agents.find_membership_with_user(membership_id) if membership_id else None
        scope = (
            self.authorization.membership_scope(found[0].id, PermissionKey.ACTIVITY_READ)
            if found is not None and found[0].organization_id == extraction.organization_id
            else None
        )
        if (
            found is None
            or scope is None
            or not organization_role_allows(found[0].role, PermissionKey.SKILL_MANAGE)
            or self.agents.get_active_in_scope(extraction.source_agent_id, scope) is None
        ):
            raise PlaybookExtractionFailed(PlaybookExtractionError.REQUESTER_LOST_ACCESS)
        return scope

"""System-owned LiteLLM team provisioning and deployment-policy reconciliation."""

import logging
from dataclasses import dataclass
from uuid import UUID

from injector import inject, singleton

from api.core.config import Config
from api.domains.organizations.repository import OrganizationRepository
from api.infrastructure.litellm.client import LiteLLMClient

logger = logging.getLogger(__name__)


@inject
@singleton
@dataclass
class OrganizationLLMService:
    config: Config
    litellm: LiteLLMClient
    organization_repository: OrganizationRepository

    @property
    def enabled(self) -> bool:
        return bool(self.config.litellm_base_url and self.config.litellm_secret_name)

    def provision_after_commit(self, organization_id: UUID) -> None:
        if not self.enabled:
            return
        try:
            self.litellm.ensure_organization_team(str(organization_id))
        except Exception as exc:
            # The Organization transaction already committed. Do not report its
            # creation as failed or leak credential-bearing HTTP exceptions.
            # Key creation retries and refuses to issue an unassigned key.
            logger.error(
                "LiteLLM team provisioning deferred for Organization %s (%s)", organization_id, type(exc).__name__
            )

    def reconcile(self) -> None:
        if not self.enabled:
            return
        for organization_id in self.organization_repository.list_ids_for_llm_reconciliation():
            self.litellm.ensure_organization_team(str(organization_id))
        logger.info("Organization LiteLLM teams and budgets reconciled")

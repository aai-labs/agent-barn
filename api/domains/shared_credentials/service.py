from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from pydantic import ValidationError

from api.core.config import Config
from api.domains.agents.models import (
    decrypt_content,
    encrypt_content,
    validate_content,
)
from api.domains.auth.models import CurrentUserContext
from api.domains.shared_credentials.models import (
    SHARED_CREDENTIAL_ALLOWED_PROVIDERS,
    SharedCredential,
    SharedCredentialBrief,
    SharedCredentialCreate,
    SharedCredentialFilter,
    SharedCredentialRead,
    SharedCredentialUpdate,
)
from api.domains.shared_credentials.repository import SharedCredentialRepository
from api.domains.rbac.catalog import IMPLICIT_AGENT_OWNER_ROLES
from api.infrastructure.integration_validators import (
    PROVIDER_VALIDATORS,
    format_validation_result,
)
from api.infrastructure.shared.models import PaginatedItems, Pagination


@inject
@singleton
@dataclass
class SharedCredentialService:
    repository: SharedCredentialRepository
    config: Config

    def _org_id(self, context: CurrentUserContext) -> UUID:
        return context.require_current_user_organization().organization_id

    def _require_manager(self, context: CurrentUserContext) -> UUID:
        org_id = self._org_id(context)
        context.require_org_role(org_id, IMPLICIT_AGENT_OWNER_ROLES, detail="Admin access required")
        return org_id

    def _get_or_404(self, credential_id: UUID, org_id: UUID) -> SharedCredential:
        credential = self.repository.get_by_id_and_org(credential_id, org_id)
        if credential is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Shared credential {credential_id} not found",
            )
        return credential

    def create_shared_credential(
        self, data: SharedCredentialCreate, context: CurrentUserContext
    ) -> SharedCredentialRead:
        org_id = self._require_manager(context)

        if data.provider not in SHARED_CREDENTIAL_ALLOWED_PROVIDERS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Provider {data.provider.value} is not supported for shared credentials",
            )

        try:
            validated = validate_content(data.provider, data.content)
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=e.errors(),
            )
        encrypted = encrypt_content(validated, self.config.agent_token_encryption_key)

        credential = SharedCredential(
            organization_id=org_id,
            provider=data.provider,
            name=data.name,
            content=encrypted,
            created_by=context.user.id,
        )
        self.repository.save(credential)
        return self._to_read(credential, agent_count=0)

    def update_shared_credential(
        self,
        credential_id: UUID,
        data: SharedCredentialUpdate,
        context: CurrentUserContext,
    ) -> SharedCredentialRead:
        org_id = self._require_manager(context)
        credential = self._get_or_404(credential_id, org_id)

        updated = data.model_dump(exclude_unset=True)
        if "name" in updated and updated["name"] is not None:
            credential.name = updated["name"]
        if "content" in updated and updated["content"] is not None:
            try:
                validated = validate_content(credential.provider, updated["content"])
            except ValidationError as e:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=e.errors(),
                )
            credential.content = encrypt_content(validated, self.config.agent_token_encryption_key)

        self.repository.save(credential)
        agent_count = self.repository.count_agent_references(credential.id, org_id)
        return self._to_read(credential, agent_count=agent_count)

    def delete_shared_credential(self, credential_id: UUID, context: CurrentUserContext) -> None:
        org_id = self._require_manager(context)
        credential = self._get_or_404(credential_id, org_id)

        self.repository.delete_orphaned_references(credential.id, org_id)

        agent_count = self.repository.count_agent_references(credential.id, org_id)
        if agent_count > 0:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Shared credential is attached to {agent_count} agent(s). "
                    "Detach it from all agents before deleting."
                ),
            )
        self.repository.delete(credential)

    def get_shared_credential(self, credential_id: UUID, context: CurrentUserContext) -> SharedCredentialRead:
        org_id = self._org_id(context)
        credential = self._get_or_404(credential_id, org_id)
        agent_count = self.repository.count_agent_references(credential.id, org_id)
        return self._to_read(credential, agent_count=agent_count)

    def list_shared_credentials(
        self,
        cred_filter: SharedCredentialFilter,
        pagination: Pagination,
        context: CurrentUserContext,
    ) -> PaginatedItems[SharedCredentialRead]:
        org_id = self._org_id(context)
        credentials, total = self.repository.find_all_for_org(org_id, cred_filter, pagination)
        counts = self.repository.count_agent_references_for_ids([c.id for c in credentials], org_id)
        reads = [self._to_read(cred, agent_count=counts.get(cred.id, 0)) for cred in credentials]
        return PaginatedItems(
            page=pagination.page,
            page_size=pagination.size,
            total=total,
            items=reads,
        )

    def list_shared_credential_briefs(self, context: CurrentUserContext) -> list[SharedCredentialBrief]:
        org_id = self._org_id(context)
        credentials = self.repository.find_all_briefs_for_org(org_id)
        return [SharedCredentialBrief.model_validate(c) for c in credentials]

    def validate_shared_credential(self, credential_id: UUID, context: CurrentUserContext) -> dict:
        org_id = self._require_manager(context)
        credential = self._get_or_404(credential_id, org_id)

        validator = PROVIDER_VALIDATORS.get(credential.provider)
        if validator is None:
            return {
                "validation_status": "unsupported",
                "validation_identity": None,
                "validation_error": "Live validation is not available for this provider",
                "missing_scopes": [],
            }
        content = decrypt_content(
            credential.provider,
            credential.content,
            self.config.agent_token_encryption_key,
        )
        result = validator(content)  # type: ignore[arg-type]
        return format_validation_result(result)

    @staticmethod
    def _to_read(credential: SharedCredential, *, agent_count: int) -> SharedCredentialRead:
        return SharedCredentialRead(
            id=credential.id,
            organization_id=credential.organization_id,
            provider=credential.provider,
            name=credential.name,
            created_by=credential.created_by,
            agent_count=agent_count,
            created_at=credential.created_at,
            updated_at=credential.updated_at,
        )

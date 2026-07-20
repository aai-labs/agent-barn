from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import (
    Agent,
    AgentAccessGrantRequest,
    AgentAccessMemberRead,
)
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.users.models import User
from api.domains.users.organization_users.models import (
    OrganizationRole,
    OrganizationUser,
)
from api.domains.users.organization_users.repository import OrganizationUserRepository


@inject
@singleton
@dataclass
class AgentAccessService:
    repository: AgentRepository
    authorization: AgentAuthorization
    membership_repository: OrganizationUserRepository

    def list_assigned_members(
        self, agent_id: UUID, context: CurrentUserContext
    ) -> list[AgentAccessMemberRead]:
        agent = self._require_manage_access(context, agent_id)
        assigned_ids = self.repository.find_access_membership_ids(
            agent.id, agent.organization_id
        )
        return [
            self._to_read(agent, membership, user)
            for membership, user in self.membership_repository.get_members_with_users(
                agent.organization_id
            )
            if membership.id in assigned_ids
        ]

    def list_eligible_members(
        self, agent_id: UUID, context: CurrentUserContext
    ) -> list[AgentAccessMemberRead]:
        agent = self._require_manage_access(context, agent_id)
        assigned_ids = self.repository.find_access_membership_ids(
            agent.id, agent.organization_id
        )
        return [
            self._to_read(agent, membership, user)
            for membership, user in self.membership_repository.get_members_with_users(
                agent.organization_id
            )
            if membership.id not in assigned_ids
            and membership.role == OrganizationRole.MEMBER
            and user.email_verified_at is not None
        ]

    def grant_access(
        self,
        agent_id: UUID,
        data: AgentAccessGrantRequest,
        context: CurrentUserContext,
    ) -> tuple[AgentAccessMemberRead, bool]:
        agent = self._require_manage_access(context, agent_id)
        membership, user = self._require_target_member(
            data.user_id, agent.organization_id
        )
        if membership.role != OrganizationRole.MEMBER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent Access can only be granted to organization members",
            )
        if user.email_verified_at is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Pending members must accept their invite before receiving Agent Access",
            )

        result = self.repository.grant_access(
            agent.id, membership.id, agent.organization_id
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent or member is no longer available",
            )
        _, created = result
        return self._to_read(agent, membership, user), created

    def revoke_access(
        self, agent_id: UUID, user_id: UUID, context: CurrentUserContext
    ) -> None:
        agent = self._require_manage_access(context, agent_id)
        membership, user = self._require_target_member(user_id, agent.organization_id)
        if agent.created_by_user_id == context.user.id == user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="An Agent creator cannot revoke their own access",
            )
        if not self.repository.revoke_access(
            agent.id, membership.id, agent.organization_id
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent Access not found",
            )

    def _require_manage_access(
        self, context: CurrentUserContext, agent_id: UUID
    ) -> Agent:
        return self.authorization.require_action(
            context,
            agent_id,
            PermissionKey.AGENT_ACCESS_MANAGE,
            detail="You don't have permission to manage access to this Agent.",
        )

    def _require_target_member(
        self, user_id: UUID, organization_id: UUID
    ) -> tuple[OrganizationUser, User]:
        result = self.membership_repository.get_member_with_user(
            user_id, organization_id
        )
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found in this organization",
            )
        return result

    @staticmethod
    def _to_read(
        agent: Agent, membership: OrganizationUser, user: User
    ) -> AgentAccessMemberRead:
        return AgentAccessMemberRead(
            user_id=user.id,
            email=str(user.email),
            full_name=user.full_name,
            role=membership.role,
            is_pending=user.email_verified_at is None,
            is_creator=agent.created_by_user_id == user.id,
        )

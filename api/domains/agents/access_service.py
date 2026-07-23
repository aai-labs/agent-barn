from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton

from api.domains.agents.authorization import AgentAuthorization
from api.domains.agents.models import (
    Agent,
    AgentAccessCandidateRead,
    AgentAccessMemberRead,
    AgentAccessRoleRead,
    AgentAccessSettingsRead,
    AgentAccessSettingsUpdate,
    AgentGeneralAccessRead,
)
from api.domains.agents.repository import AgentRepository
from api.domains.auth.models import CurrentUserContext
from api.domains.rbac.catalog import PermissionKey
from api.domains.rbac.models import AgentAccessRole
from api.domains.rbac.repository import RbacRepository
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
    rbac_repository: RbacRepository

    def list_roles(self, context: CurrentUserContext) -> list[AgentAccessRoleRead]:
        organization_id = context.require_current_user_organization().organization_id
        return [
            self._role_to_read(role, permissions)
            for role, permissions in self.rbac_repository.list_agent_access_roles(organization_id)
        ]

    def get_access_settings(self, agent_id: UUID, context: CurrentUserContext) -> AgentAccessSettingsRead:
        agent = self._require_manage_access(context, agent_id)
        return AgentAccessSettingsRead(
            general_access=AgentGeneralAccessRead(role=self._general_access_role_read(agent)),
            assignments=self._assigned_members_for_agent(agent),
        )

    def replace_access_settings(
        self,
        agent_id: UUID,
        data: AgentAccessSettingsUpdate,
        context: CurrentUserContext,
    ) -> AgentAccessSettingsRead:
        agent = self._require_manage_access(context, agent_id)
        general_role_read = self._require_general_access_role(data.general_access_role_id, agent.organization_id)

        seen_user_ids: set[UUID] = set()
        assignment_roles: dict[UUID, UUID] = {}
        assignments: list[AgentAccessMemberRead] = []
        for assignment in data.assignments:
            if assignment.user_id in seen_user_ids:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Each member can appear only once in Agent access settings",
                )
            seen_user_ids.add(assignment.user_id)
            role, role_read = self._require_access_role(assignment.access_role_id, agent.organization_id)
            membership, user = self._require_accepted_member(assignment.user_id, agent.organization_id)
            assignment_roles[membership.id] = role.id
            assignments.append(self._to_assignment(agent, membership, user, role_read))

        if not self.repository.replace_access_settings(
            agent.id,
            agent.organization_id,
            general_access_role_id=data.general_access_role_id,
            assignment_roles=assignment_roles,
        ):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Agent or member is no longer available",
            )
        return AgentAccessSettingsRead(
            general_access=AgentGeneralAccessRead(role=general_role_read),
            assignments=assignments,
        )

    def _require_general_access_role(self, role_id: UUID | None, organization_id: UUID) -> AgentAccessRoleRead | None:
        if role_id is None:
            return None
        role, role_read = self._require_access_role(role_id, organization_id)
        permissions = self.rbac_repository.get_agent_access_role_permissions(role.id)
        if PermissionKey.AGENT_READ not in permissions:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent General Access requires an Agent Access Role that grants agent.read",
            )
        return role_read

    def _general_access_role_read(self, agent: Agent) -> AgentAccessRoleRead | None:
        if agent.general_access_role_id is None:
            return None
        role = self.rbac_repository.get_agent_access_role(agent.general_access_role_id, agent.organization_id)
        if role is None:
            return None
        permissions = self.rbac_repository.get_agent_access_role_permissions(role.id)
        return self._role_to_read(role, permissions)

    def _assigned_members_for_agent(self, agent: Agent) -> list[AgentAccessMemberRead]:
        assignments = {
            access.membership_id: access
            for access in self.repository.find_access_assignments(agent.id, agent.organization_id)
        }
        roles = {
            role.id: self._role_to_read(role, permissions)
            for role, permissions in self.rbac_repository.list_agent_access_roles(agent.organization_id)
        }
        result = []
        for membership, user in self.membership_repository.get_members_with_users(agent.organization_id):
            access = assignments.get(membership.id)
            if access is None:
                continue
            role = roles.get(access.access_role_id)
            if role is None:
                continue
            result.append(self._to_assignment(agent, membership, user, role))
        return result

    def _require_manage_access(self, context: CurrentUserContext, agent_id: UUID) -> Agent:
        return self.authorization.require_action(
            context,
            agent_id,
            PermissionKey.AGENT_ACCESS_MANAGE,
            detail="You don't have permission to manage access to this Agent.",
        )

    def _require_access_role(self, role_id: UUID, organization_id: UUID) -> tuple[AgentAccessRole, AgentAccessRoleRead]:
        role = self.rbac_repository.get_agent_access_role(role_id, organization_id)
        if role is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Agent Access Role is not available in this organization",
            )
        permissions = self.rbac_repository.get_agent_access_role_permissions(role.id)
        return role, self._role_to_read(role, permissions)

    def _require_accepted_member(self, user_id: UUID, organization_id: UUID) -> tuple[OrganizationUser, User]:
        membership, user = self._require_target_member(user_id, organization_id)
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
        return membership, user

    def _require_target_member(self, user_id: UUID, organization_id: UUID) -> tuple[OrganizationUser, User]:
        result = self.membership_repository.get_member_with_user(user_id, organization_id)
        if result is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found in this organization",
            )
        return result

    @staticmethod
    def _role_to_read(role: AgentAccessRole, permissions: set[PermissionKey]) -> AgentAccessRoleRead:
        return AgentAccessRoleRead(
            id=role.id,
            name=role.name,
            permissions=sorted(permissions, key=lambda permission: permission.value),
            is_locked=role.is_system,
        )

    @staticmethod
    def _to_candidate(agent: Agent, membership: OrganizationUser, user: User) -> AgentAccessCandidateRead:
        return AgentAccessCandidateRead(
            user_id=user.id,
            email=str(user.email),
            full_name=user.full_name,
            organization_role=membership.role,
            is_pending=user.email_verified_at is None,
            is_creator=agent.created_by_user_id == user.id,
        )

    @classmethod
    def _to_assignment(
        cls,
        agent: Agent,
        membership: OrganizationUser,
        user: User,
        access_role: AgentAccessRoleRead,
    ) -> AgentAccessMemberRead:
        candidate = cls._to_candidate(agent, membership, user)
        return AgentAccessMemberRead(
            **candidate.model_dump(),
            access_role=access_role,
        )

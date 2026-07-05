from dataclasses import dataclass
from uuid import UUID

from fastapi import HTTPException, status
from injector import inject, singleton
from sqlmodel import Session

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.service import AuthService
from api.domains.organizations.repository import OrganizationRepository
from api.domains.users.organization_users.exceptions import (
    UserAlreadyPartOfOrganizationException,
)
from api.domains.users.organization_users.models import (
    AddMemberRequest,
    ChangeMemberRoleRequest,
    OrganizationMemberRead,
    OrganizationRole,
    OrganizationUser,
    OrganizationUserRead,
    TransferOwnershipRequest,
)
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.repository import UserRepository


@inject
@singleton
@dataclass
class OrganizationUserService:
    organization_user_repository: OrganizationUserRepository
    organization_repository: OrganizationRepository
    auth_service: AuthService
    user_repository: UserRepository

    def find_by_user_id_and_organization_id(
        self, user_id: UUID, organization_id: UUID
    ) -> OrganizationUserRead:
        organization_user = (
            self.organization_user_repository.get_by_user_id_and_organization_id(
                user_id, organization_id
            )
        )
        if not organization_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Organization user with user ID {user_id} and organization ID {organization_id} not found",
            )

        organization = self.organization_repository.get_read(
            organization_user.organization_id
        )
        if not organization:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
            )

        return OrganizationUserRead(
            **organization_user.model_dump(),
            organization=organization,
        )

    def create_user_organization(
        self, user_data: OrganizationUser
    ) -> OrganizationUserRead:
        try:
            organization = self.organization_repository.get_read(
                user_data.organization_id
            )
            if not organization:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Organization not found",
                )

            organization_user = self.organization_user_repository.save(user_data)
            return OrganizationUserRead(
                **organization_user.model_dump(),
                organization=organization,
            )
        except UserAlreadyPartOfOrganizationException as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"User {e.user_id} is already part of organization {e.organization_id}",
            )

    def add_membership_with_session(
        self, membership: OrganizationUser, session: Session
    ) -> OrganizationUser:
        """Stage a membership insert in the caller's transaction (so it commits
        atomically with org creation / an invite). Raises the same domain exceptions as
        the non-session save on constraint violation."""
        return self.organization_user_repository.save_with_session(membership, session)

    def find_by_user_id(self, user_id: UUID) -> list[OrganizationUserRead]:
        organization_users = self.organization_user_repository.get_by_user_id(user_id)
        if not organization_users:
            return []

        organization_reads: list[OrganizationUserRead] = []
        for organization_user in organization_users:
            organization = self.organization_repository.get_read(
                organization_user.organization_id
            )
            if not organization:
                continue

            organization_reads.append(
                OrganizationUserRead(
                    **organization_user.model_dump(),
                    organization=organization,
                )
            )

        return organization_reads

    # --- Member management (org-scoped) ---

    def _ensure_can_manage_members(
        self, context: CurrentUserContext, organization_id: UUID
    ) -> None:
        context.require_org_role(
            organization_id,
            {OrganizationRole.OWNER, OrganizationRole.ADMIN},
            detail="You don't have permission to manage this organization's members",
        )

    def _ensure_is_owner(
        self, context: CurrentUserContext, organization_id: UUID
    ) -> None:
        context.require_org_role(
            organization_id,
            {OrganizationRole.OWNER},
            detail="Only the organization owner can transfer ownership",
        )

    def _require_membership(
        self, user_id: UUID, organization_id: UUID
    ) -> OrganizationUser:
        membership = (
            self.organization_user_repository.get_by_user_id_and_organization_id(
                user_id, organization_id
            )
        )
        if membership is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Member not found in this organization",
            )
        return membership

    def _to_member_read(self, membership: OrganizationUser) -> OrganizationMemberRead:
        user = (
            self.user_repository.get(membership.user_id) if membership.user_id else None
        )
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Member user not found"
            )
        return OrganizationMemberRead(
            user_id=user.id,
            email=user.email,
            full_name=user.full_name,
            role=membership.role,
            is_pending=user.email_verified_at is None,
        )

    def list_members(
        self, context: CurrentUserContext, organization_id: UUID
    ) -> list[OrganizationMemberRead]:
        self._ensure_can_manage_members(context, organization_id)
        rows = self.organization_user_repository.get_members_with_users(organization_id)
        return [
            OrganizationMemberRead(
                user_id=user.id,
                email=user.email,
                full_name=user.full_name,
                role=membership.role,
                is_pending=user.email_verified_at is None,
            )
            for membership, user in rows
        ]

    def add_member(
        self,
        context: CurrentUserContext,
        organization_id: UUID,
        data: AddMemberRequest,
    ) -> tuple[OrganizationMemberRead, str | None]:
        self._ensure_can_manage_members(context, organization_id)
        if data.role == OrganizationRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Use transfer-ownership to assign an owner",
            )
        if self.organization_repository.get(organization_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Organization not found"
            )

        # Invite (user + token) and membership commit together; the email is sent only
        # after commit. So a duplicate-member 409 rolls the invite back — no ghost user,
        # no rotated token, no email — instead of the previous fire-then-fail order.
        with Session(
            self.organization_user_repository.delegate.engine, expire_on_commit=False
        ) as session:
            prepared = self.auth_service.prepare_invite(
                session, email=str(data.email), full_name=data.full_name
            )
            try:
                membership = self.organization_user_repository.save_with_session(
                    OrganizationUser(
                        user_id=prepared.user.id,
                        organization_id=organization_id,
                        role=data.role,
                    ),
                    session,
                )
            except UserAlreadyPartOfOrganizationException as e:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User {e.user_id} is already part of organization {e.organization_id}",
                )
            session.commit()

        self.auth_service.send_prepared_invite(prepared)
        return self._to_member_read(membership), prepared.invite_link

    def change_role(
        self,
        context: CurrentUserContext,
        organization_id: UUID,
        user_id: UUID,
        data: ChangeMemberRoleRequest,
    ) -> OrganizationMemberRead:
        self._ensure_can_manage_members(context, organization_id)
        if data.role == OrganizationRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Use transfer-ownership to assign an owner",
            )
        membership = self._require_membership(user_id, organization_id)
        if membership.role == OrganizationRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot change the owner's role; transfer ownership instead",
            )
        # Promoting to or demoting from ADMIN is reserved for owners/superusers; a plain
        # admin can manage members but not other admins (nor mint new ones).
        touches_admin = OrganizationRole.ADMIN in (membership.role, data.role)
        if touches_admin and not context.has_org_role(
            organization_id, {OrganizationRole.OWNER}
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only an owner can promote or demote admins",
            )
        membership.role = data.role
        self.organization_user_repository.save(membership)
        return self._to_member_read(membership)

    def remove_member(
        self, context: CurrentUserContext, organization_id: UUID, user_id: UUID
    ) -> None:
        self._ensure_can_manage_members(context, organization_id)
        membership = self._require_membership(user_id, organization_id)
        if membership.role == OrganizationRole.OWNER:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot remove the owner; transfer ownership first",
            )
        self.organization_user_repository.delete(membership)

        # Rescinding a still-pending member's access must also kill their invite link,
        # which otherwise stays valid (it's tied to the user, not the membership).
        user = self.user_repository.get(user_id)
        if user is not None and user.email_verified_at is None:
            self.auth_service.revoke_pending_invites(user_id)

    def transfer_ownership(
        self,
        context: CurrentUserContext,
        organization_id: UUID,
        data: TransferOwnershipRequest,
    ) -> None:
        self._ensure_is_owner(context, organization_id)
        new_owner_membership = self._require_membership(data.user_id, organization_id)
        current_owner = self.user_repository.get_organization_owner(organization_id)
        if current_owner is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization has no current owner",
            )
        if current_owner.id == new_owner_membership.user_id:
            return
        self.organization_user_repository.transfer_ownership(
            organization_id=organization_id,
            current_owner_id=current_owner.id,
            new_owner_id=data.user_id,
        )

    def resend_invite(
        self, context: CurrentUserContext, organization_id: UUID, user_id: UUID
    ) -> str:
        self._ensure_can_manage_members(context, organization_id)
        self._require_membership(user_id, organization_id)
        user = self.user_repository.get(user_id)
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Member user not found"
            )
        if user.email_verified_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Member has already accepted their invite",
            )
        _, invite_link = self.auth_service.invite_user(
            email=user.email, full_name=user.full_name
        )
        if invite_link is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to generate invite link",
            )
        return invite_link

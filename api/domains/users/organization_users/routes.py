from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.users.organization_users.models import (
    AddMemberRequest,
    ChangeMemberRoleRequest,
    InviteLinkResult,
    MemberInviteResult,
    OrganizationMemberRead,
    TransferOwnershipRequest,
)
from api.domains.users.organization_users.service import OrganizationUserService

member_router = APIRouter(prefix="/organizations", tags=["organization-members"])


@member_router.get("/{organization_id}/members", response_model=list[OrganizationMemberRead])
def list_members(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[OrganizationUserService, Injected(OrganizationUserService)],
    search: Annotated[str | None, Query()] = None,
    limit: Annotated[int | None, Query(ge=1, le=200)] = None,
):
    return service.list_members(context, organization_id, search=search, limit=limit)


@member_router.post(
    "/{organization_id}/members",
    response_model=MemberInviteResult,
    status_code=status.HTTP_201_CREATED,
)
def add_member(
    organization_id: UUID,
    data: AddMemberRequest,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[OrganizationUserService, Injected(OrganizationUserService)],
):
    member, invite_link = service.add_member(context, organization_id, data)
    return MemberInviteResult(member=member, invite_link=invite_link)


@member_router.patch("/{organization_id}/members/{user_id}", response_model=OrganizationMemberRead)
def change_member_role(
    organization_id: UUID,
    user_id: UUID,
    data: ChangeMemberRoleRequest,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[OrganizationUserService, Injected(OrganizationUserService)],
):
    return service.change_role(context, organization_id, user_id, data)


@member_router.delete(
    "/{organization_id}/members/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member(
    organization_id: UUID,
    user_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[OrganizationUserService, Injected(OrganizationUserService)],
):
    service.remove_member(context, organization_id, user_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@member_router.post(
    "/{organization_id}/transfer-ownership",
    status_code=status.HTTP_204_NO_CONTENT,
)
def transfer_ownership(
    organization_id: UUID,
    data: TransferOwnershipRequest,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[OrganizationUserService, Injected(OrganizationUserService)],
):
    service.transfer_ownership(context, organization_id, data)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@member_router.post(
    "/{organization_id}/members/{user_id}/resend-invite",
    response_model=InviteLinkResult,
)
def resend_invite(
    organization_id: UUID,
    user_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[OrganizationUserService, Injected(OrganizationUserService)],
):
    invite_link = service.resend_invite(context, organization_id, user_id)
    return InviteLinkResult(invite_link=invite_link)

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import require_platform_admin
from api.domains.users.models import (
    PlatformPrivilegeUpdate,
    PlatformUserCreate,
    PlatformUserCreateResult,
    PlatformUserInviteResult,
    UserFilter,
    UserRead,
    get_user_filter,
)
from api.domains.users.service import UserService
from api.infrastructure.shared.models import PaginatedItems

users_router = APIRouter(prefix="/platform/users", tags=["platform-users"])


@users_router.post("", response_model=PlatformUserCreateResult, status_code=status.HTTP_201_CREATED)
def create_user(
    data: PlatformUserCreate,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    user_service: UserService = Injected(UserService),
):
    return user_service.create_platform_user(data)


@users_router.get("", response_model=PaginatedItems[UserRead])
def list_users(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    filters: Annotated[UserFilter, Depends(get_user_filter)],
    page: int = 1,
    page_size: int = 15,
    user_service: UserService = Injected(UserService),
):
    return user_service.get_paginated_users(filters=filters, context=context, page=page, page_size=page_size)


@users_router.get("/{user_id}", response_model=UserRead)
def get_user(
    user_id: UUID,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    user_service: UserService = Injected(UserService),
):
    return user_service.to_user_read(user_service.get_user(user_id))


@users_router.patch("/{user_id}/platform-privilege", response_model=UserRead)
def change_platform_privilege(
    user_id: UUID,
    data: PlatformPrivilegeUpdate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    user_service: UserService = Injected(UserService),
):
    return user_service.change_platform_privilege(
        actor=context,
        user_id=user_id,
        is_platform_admin=data.is_platform_admin,
        reason=data.reason,
    )


@users_router.post(
    "/{user_id}/resend-invite",
    response_model=PlatformUserInviteResult,
)
def resend_user_invite(
    user_id: UUID,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    user_service: UserService = Injected(UserService),
):
    return user_service.resend_platform_user_invite(user_id)

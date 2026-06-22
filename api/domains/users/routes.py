from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.users.models import AdminUserCreate, UserFilter, UserRead, get_user_filter
from api.domains.users.service import UserService
from api.infrastructure.shared.models import PaginatedItems

users_router = APIRouter(prefix="/users", tags=["users"])


@users_router.get("", response_model=PaginatedItems[UserRead])
def list_users(
    _: Annotated[CurrentUserContext, Depends(get_current_user(check_superuser=True))],
    filters: Annotated[UserFilter, Depends(get_user_filter)],
    page: int = 1,
    page_size: int = 15,
    user_service: UserService = Injected(UserService),
):
    return user_service.get_paginated_users(
        filters=filters, page=page, page_size=page_size
    )


@users_router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    data: AdminUserCreate,
    context: Annotated[
        CurrentUserContext, Depends(get_current_user(check_superuser=True))
    ],
    user_service: UserService = Injected(UserService),
):
    user = user_service.create_user(data)
    return user_service.to_user_read(user)


@users_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID,
    context: Annotated[
        CurrentUserContext, Depends(get_current_user(check_superuser=True))
    ],
    user_service: UserService = Injected(UserService),
):
    user_service.delete_user(user_id, context.user.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

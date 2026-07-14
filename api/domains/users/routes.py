from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from fastapi_injector import Injected

from api.domains.audit_logs.models import AuditAction, TargetType
from api.domains.audit_logs.service import AuditLogService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.users.models import (
    AdminPasswordReset,
    AdminUserCreate,
    UserFilter,
    UserRead,
    get_user_filter,
)
from api.domains.users.service import UserService
from api.infrastructure.shared.models import PaginatedItems

users_router = APIRouter(prefix="/users", tags=["users"])


@users_router.get("", response_model=PaginatedItems[UserRead])
def list_users(
    context: Annotated[
        CurrentUserContext, Depends(get_current_user(check_superuser=True))
    ],
    filters: Annotated[UserFilter, Depends(get_user_filter)],
    page: int = 1,
    page_size: int = 15,
    user_service: UserService = Injected(UserService),
):
    return user_service.get_paginated_users(
        filters=filters, context=context, page=page, page_size=page_size
    )


@users_router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
def create_user(
    data: AdminUserCreate,
    context: Annotated[
        CurrentUserContext, Depends(get_current_user(check_superuser=True))
    ],
    user_service: UserService = Injected(UserService),
    audit_log_service: AuditLogService = Injected(AuditLogService),
):
    user = user_service.create_user(data)
    # Superuser admin action over a global (org-less) user record → NULL org.
    audit_log_service.record(
        action=AuditAction.USER_CREATE,
        context=context,
        organization_id=None,
        target_type=TargetType.USER,
        target_id=user.id,
        target_label=user.email,
    )
    return user_service.to_user_read(user)


@users_router.post("/{user_id}/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_user_password(
    user_id: UUID,
    data: AdminPasswordReset,
    context: Annotated[
        CurrentUserContext, Depends(get_current_user(check_superuser=True))
    ],
    user_service: UserService = Injected(UserService),
    audit_log_service: AuditLogService = Injected(AuditLogService),
):
    user_service.reset_user_password(user_id, data.new_password)
    target = user_service.get_user(user_id)
    audit_log_service.record(
        action=AuditAction.USER_PASSWORD_RESET,
        context=context,
        organization_id=None,
        target_type=TargetType.USER,
        target_id=user_id,
        target_label=target.email if target else None,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@users_router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(
    user_id: UUID,
    context: Annotated[
        CurrentUserContext, Depends(get_current_user(check_superuser=True))
    ],
    user_service: UserService = Injected(UserService),
    audit_log_service: AuditLogService = Injected(AuditLogService),
):
    # Capture the email before deletion so the audit row stays readable.
    target = user_service.get_user(user_id)
    target_email = target.email if target else None
    user_service.delete_user(user_id, context.user.id)
    audit_log_service.record(
        action=AuditAction.USER_DELETE,
        context=context,
        organization_id=None,
        target_type=TargetType.USER,
        target_id=user_id,
        target_label=target_email,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

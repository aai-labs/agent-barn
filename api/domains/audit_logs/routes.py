import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi_injector import Injected

from api.domains.audit_logs.models import (
    AuditAction,
    AuditLogFilter,
    AuditLogRead,
    get_audit_log_filter,
)
from api.domains.audit_logs.service import AuditLogService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.users.organization_users.models import ORG_MANAGER_ROLES
from api.infrastructure.shared.models import PaginatedItems, Pagination

audit_logs_router = APIRouter(prefix="/audit-logs", tags=["audit-logs"])


@audit_logs_router.get("", response_model=PaginatedItems[AuditLogRead])
def list_audit_logs(
    context: Annotated[
        CurrentUserContext,
        Depends(get_current_user(organization_roles=ORG_MANAGER_ROLES)),
    ],
    service: Annotated[AuditLogService, Injected(AuditLogService)],
    filters: Annotated[AuditLogFilter, Depends(get_audit_log_filter)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 25,
):
    result = service.list_logs(context, filters, Pagination(page=page, size=page_size))
    service.record(action=AuditAction.AUDIT_LOG_VIEW, context=context)
    return result


@audit_logs_router.get("/actions", response_model=list[str])
def list_audit_actions(
    context: Annotated[
        CurrentUserContext,
        Depends(get_current_user(organization_roles=ORG_MANAGER_ROLES)),
    ],
):
    return sorted(action.value for action in AuditAction)


@audit_logs_router.get("/export")
def export_audit_logs(
    context: Annotated[
        CurrentUserContext,
        Depends(get_current_user(organization_roles=ORG_MANAGER_ROLES)),
    ],
    service: Annotated[AuditLogService, Injected(AuditLogService)],
    filters: Annotated[AuditLogFilter, Depends(get_audit_log_filter)],
):
    service.record(action=AuditAction.AUDIT_LOG_EXPORT, context=context)
    filename = f"audit-logs-{datetime.date.today().isoformat()}.csv"
    return StreamingResponse(
        service.iter_export_rows(context, filters),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.shared_credentials.models import (
    SharedCredentialBrief,
    SharedCredentialCreate,
    SharedCredentialFilter,
    SharedCredentialRead,
    SharedCredentialUpdate,
    get_shared_credential_filter,
)
from api.domains.shared_credentials.service import SharedCredentialService
from api.domains.users.organization_users.models import ORG_MANAGER_ROLES
from api.infrastructure.shared.models import PaginatedItems, Pagination

shared_credentials_router = APIRouter(prefix="/shared-credentials", tags=["shared-credentials"])


@shared_credentials_router.post("", response_model=SharedCredentialRead, status_code=status.HTTP_201_CREATED)
def create_shared_credential(
    data: SharedCredentialCreate,
    context: Annotated[
        CurrentUserContext,
        Depends(get_current_user(organization_roles=ORG_MANAGER_ROLES)),
    ],
    service: Annotated[SharedCredentialService, Injected(SharedCredentialService)],
):
    return service.create_shared_credential(data, context)


@shared_credentials_router.get("", response_model=PaginatedItems[SharedCredentialRead])
def list_shared_credentials(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SharedCredentialService, Injected(SharedCredentialService)],
    cred_filter: Annotated[SharedCredentialFilter, Depends(get_shared_credential_filter)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 15,
):
    return service.list_shared_credentials(
        cred_filter=cred_filter,
        pagination=Pagination(page=page, size=page_size),
        context=context,
    )


@shared_credentials_router.get("/briefs", response_model=list[SharedCredentialBrief])
def list_shared_credential_briefs(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SharedCredentialService, Injected(SharedCredentialService)],
):
    return service.list_shared_credential_briefs(context)


@shared_credentials_router.get("/{credential_id}", response_model=SharedCredentialRead)
def get_shared_credential(
    credential_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SharedCredentialService, Injected(SharedCredentialService)],
):
    return service.get_shared_credential(credential_id, context)


@shared_credentials_router.patch("/{credential_id}", response_model=SharedCredentialRead)
def update_shared_credential(
    credential_id: UUID,
    data: SharedCredentialUpdate,
    context: Annotated[
        CurrentUserContext,
        Depends(get_current_user(organization_roles=ORG_MANAGER_ROLES)),
    ],
    service: Annotated[SharedCredentialService, Injected(SharedCredentialService)],
):
    return service.update_shared_credential(credential_id, data, context)


@shared_credentials_router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_shared_credential(
    credential_id: UUID,
    context: Annotated[
        CurrentUserContext,
        Depends(get_current_user(organization_roles=ORG_MANAGER_ROLES)),
    ],
    service: Annotated[SharedCredentialService, Injected(SharedCredentialService)],
):
    service.delete_shared_credential(credential_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@shared_credentials_router.post("/{credential_id}/validate")
def validate_shared_credential(
    credential_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[SharedCredentialService, Injected(SharedCredentialService)],
):
    return service.validate_shared_credential(credential_id, context)

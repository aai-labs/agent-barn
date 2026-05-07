from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.organizations.models import (
    OrganizationFilter,
    OrganizationRead,
    OrganizationUpdate,
    get_organization_filter,
)
from api.domains.organizations.service import OrganizationService
from api.infrastructure.shared.models import PaginatedItems

org_router = APIRouter(prefix="/organizations", tags=["organizations"])


@org_router.get("/{organization_id}", response_model=OrganizationRead)
def get_organization(
    organization_id: UUID,
    _: Annotated[CurrentUserContext, Depends(get_current_user())],
    organization_service: Annotated[OrganizationService, Injected(OrganizationService)],
):
    return organization_service.get_organization(organization_id)


@org_router.get("", response_model=PaginatedItems[OrganizationRead])
def get_organizations(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    filters: Annotated[OrganizationFilter, Depends(get_organization_filter)],
    organization_service: Annotated[OrganizationService, Injected(OrganizationService)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 15,
):
    return organization_service.get_paginated_organizations(
        context=context,
        org_filter=filters,
        page_size=page_size,
        page=page,
    )


@org_router.patch("/{organization_id}", response_model=OrganizationRead)
def update_organization(
    organization_id: UUID,
    organization_update: OrganizationUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    organization_service: Annotated[OrganizationService, Injected(OrganizationService)],
):
    return organization_service.update_organization(
        organization_id, organization_update, context
    )


@org_router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    organization_service: Annotated[OrganizationService, Injected(OrganizationService)],
):
    organization_service.delete_organization(organization_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)

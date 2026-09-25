from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user, require_platform_admin
from api.domains.organizations.llm_budget_service import OrganizationLlmBudgetService
from api.domains.organizations.models import (
    OrganizationCreate,
    OrganizationFilter,
    OrganizationLlmBudgetRead,
    OrganizationLlmBudgetUpdate,
    OrganizationLlmCoverageRead,
    OrganizationOwnLlmBudgetUpdate,
    OrganizationRead,
    OrganizationUpdate,
    PlatformOrganizationRead,
    get_organization_filter,
)
from api.domains.organizations.service import OrganizationService
from api.infrastructure.shared.models import PaginatedItems

org_router = APIRouter(prefix="/organizations", tags=["organizations"])
platform_org_router = APIRouter(prefix="/platform/organizations", tags=["platform-organizations"])


@org_router.post("", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
def create_organization_for_current_user(
    data: OrganizationCreate,
    context: Annotated[
        CurrentUserContext,
        Depends(get_current_user(require_organization=False)),
    ],
    organization_service: Annotated[OrganizationService, Injected(OrganizationService)],
):
    return organization_service.create_organization_for_current_user(data, context)


@org_router.get("/{organization_id}", response_model=OrganizationRead)
def get_organization(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    organization_service: Annotated[OrganizationService, Injected(OrganizationService)],
):
    return organization_service.get_organization(organization_id, context)


@platform_org_router.get("", response_model=PaginatedItems[PlatformOrganizationRead])
def get_organizations(
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
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


@platform_org_router.get("/{organization_id}", response_model=PlatformOrganizationRead)
def get_platform_organization(
    organization_id: UUID,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    organization_service: Annotated[OrganizationService, Injected(OrganizationService)],
):
    return organization_service.get_platform_organization(organization_id)


@org_router.patch("/{organization_id}", response_model=OrganizationRead)
def update_organization(
    organization_id: UUID,
    organization_update: OrganizationUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    organization_service: Annotated[OrganizationService, Injected(OrganizationService)],
):
    return organization_service.update_organization(organization_id, organization_update, context)


@org_router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_organization(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    organization_service: Annotated[OrganizationService, Injected(OrganizationService)],
):
    organization_service.delete_organization(organization_id, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@platform_org_router.put("/{organization_id}/llm-budget", response_model=PlatformOrganizationRead)
def set_organization_llm_budget(
    organization_id: UUID,
    budget: OrganizationLlmBudgetUpdate,
    context: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    budget_service: Annotated[OrganizationLlmBudgetService, Injected(OrganizationLlmBudgetService)],
):
    """Set an Organization's LLM spend ceiling.

    Platform-administered: an Organization cannot raise its own cap, which is the
    whole point of it as a cost control. It can only set a lower limit of its own.
    """
    return budget_service.set_llm_budget(organization_id, budget.budget_usd, budget.budget_duration, context)


@platform_org_router.get("/{organization_id}/llm-budget/coverage", response_model=OrganizationLlmCoverageRead)
def get_organization_llm_coverage(
    organization_id: UUID,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    budget_service: Annotated[OrganizationLlmBudgetService, Injected(OrganizationLlmBudgetService)],
):
    """Which of the Organization's Agents a spend limit would actually bind.

    Agents created before the Organization had a LiteLLM team carry no team on their
    key, so a limit does not apply to them until they are enrolled.
    """
    return budget_service.get_llm_coverage(organization_id)


@platform_org_router.post("/{organization_id}/llm-budget/enroll", response_model=OrganizationLlmCoverageRead)
def enroll_organization_llm_keys(
    organization_id: UUID,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    budget_service: Annotated[OrganizationLlmBudgetService, Injected(OrganizationLlmBudgetService)],
):
    """Attach the Organization's existing Agent keys to its team.

    Returns the resulting coverage rather than a success flag: partial enrollment is
    an ordinary outcome and the administrator needs to see what is still uncovered.
    """
    return budget_service.enroll_llm_keys(organization_id)


@org_router.get("/{organization_id}/llm-budget", response_model=OrganizationLlmBudgetRead)
def get_organization_llm_budget(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    budget_service: Annotated[OrganizationLlmBudgetService, Injected(OrganizationLlmBudgetService)],
):
    """The Organization's own view of its spend limit: the ceiling, its own limit
    beneath it, and what it has spent."""
    return budget_service.get_organization_llm_budget(organization_id, context)


@org_router.put("/{organization_id}/llm-budget", response_model=OrganizationLlmBudgetRead)
def set_organization_own_llm_budget(
    organization_id: UUID,
    budget: OrganizationOwnLlmBudgetUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    budget_service: Annotated[OrganizationLlmBudgetService, Injected(OrganizationLlmBudgetService)],
):
    """Set or clear the Organization's own spend limit, at or below its ceiling."""
    return budget_service.set_own_llm_budget(organization_id, budget.budget_usd, context)

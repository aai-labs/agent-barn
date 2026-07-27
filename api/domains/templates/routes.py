from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.templates.models import (
    TemplateCreate,
    TemplateFilter,
    TemplateRead,
    TemplateUpdate,
    get_template_filter,
)
from api.domains.templates.service import TemplateService
from api.infrastructure.shared.models import PaginatedItems, Pagination

templates_router = APIRouter(prefix="/templates", tags=["templates"])


@templates_router.get("", response_model=PaginatedItems[TemplateRead])
def list_templates(
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[TemplateService, Injected(TemplateService)],
    template_filter: Annotated[TemplateFilter, Depends(get_template_filter)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1)] = 15,
):
    return service.list_templates(
        template_filter=template_filter,
        pagination=Pagination(page=page, size=page_size),
        context=context,
    )


@templates_router.post("", response_model=TemplateRead, status_code=status.HTTP_201_CREATED)
def create_template(
    data: TemplateCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.create_template(data, context)


@templates_router.get("/{slug}", response_model=TemplateRead)
def get_template(
    slug: str,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.get_template(slug, context)


@templates_router.get("/{slug}/versions", response_model=list[TemplateRead])
def list_template_versions(
    slug: str,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.list_template_versions(slug, context)


@templates_router.patch("/{slug}", response_model=TemplateRead)
def update_template(
    slug: str,
    data: TemplateUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.update_template(slug, data, context)

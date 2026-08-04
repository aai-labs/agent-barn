from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user, require_platform_admin
from api.domains.templates.models import (
    PlatformTemplateAdminSummary,
    PlatformTemplateDraftCreate,
    PlatformTemplateDraftRead,
    PlatformTemplateDraftUpdate,
    TemplateCreate,
    TemplateFilter,
    TemplateRead,
    TemplateUpdate,
    get_template_filter,
)
from api.domains.templates.service import TemplateService
from api.infrastructure.shared.models import PaginatedItems, Pagination

templates_router = APIRouter(prefix="/organizations/{organization_id}/templates", tags=["templates"])
platform_templates_router = APIRouter(prefix="/platform/templates", tags=["platform-templates"])


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


@templates_router.get("/{template_key}", response_model=TemplateRead)
def get_template(
    template_key: str,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.get_template(template_key, context)


@templates_router.get("/{template_key}/versions", response_model=list[TemplateRead])
def list_template_versions(
    template_key: str,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.list_template_versions(template_key, context)


@templates_router.patch("/{template_key}", response_model=TemplateRead)
def update_template(
    template_key: str,
    data: TemplateUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.update_template(template_key, data, context)


@templates_router.post(
    "/{template_key}/platform-update", response_model=TemplateRead, status_code=status.HTTP_201_CREATED
)
def update_from_platform(
    template_key: str,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.update_from_platform(template_key, context)


@templates_router.delete("/{template_key}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_key: str,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    service.delete_template(template_key, context)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- Platform Admin authoring: Draft Template Version ---


@platform_templates_router.get("", response_model=list[PlatformTemplateAdminSummary])
def list_platform_lineages(
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.list_platform_lineages_for_admin()


@platform_templates_router.get("/{template_key}", response_model=TemplateRead)
def get_published_platform_template(
    template_key: str,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.get_published_platform_template_for_admin(template_key)


@platform_templates_router.get("/{template_key}/versions", response_model=list[TemplateRead])
def list_published_platform_template_versions(
    template_key: str,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.list_published_platform_template_versions_for_admin(template_key)


@platform_templates_router.post("", response_model=PlatformTemplateDraftRead, status_code=status.HTTP_201_CREATED)
def create_new_template_draft(
    data: PlatformTemplateDraftCreate,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.create_new_template_draft(data)


@platform_templates_router.get("/{template_key}/draft", response_model=PlatformTemplateDraftRead)
def get_draft(
    template_key: str,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.get_draft(template_key)


@platform_templates_router.post(
    "/{template_key}/draft", response_model=PlatformTemplateDraftRead, status_code=status.HTTP_201_CREATED
)
def start_draft(
    template_key: str,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TemplateService, Injected(TemplateService)],
    source_version: Annotated[int | None, Query(ge=1)] = None,
):
    return service.start_draft_for_existing_lineage(template_key, source_version)


@platform_templates_router.patch("/{template_key}/draft", response_model=PlatformTemplateDraftRead)
def update_draft(
    template_key: str,
    data: PlatformTemplateDraftUpdate,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.update_draft(template_key, data)


@platform_templates_router.delete("/{template_key}/draft", status_code=status.HTTP_204_NO_CONTENT)
def discard_draft(
    template_key: str,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    service.discard_draft(template_key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@platform_templates_router.post(
    "/{template_key}/draft/publish", response_model=TemplateRead, status_code=status.HTTP_201_CREATED
)
def publish_draft(
    template_key: str,
    _: Annotated[CurrentUserContext, Depends(require_platform_admin())],
    service: Annotated[TemplateService, Injected(TemplateService)],
):
    return service.publish_draft(template_key)

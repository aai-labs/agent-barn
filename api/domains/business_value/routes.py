from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi_injector import Injected

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user
from api.domains.business_value.models import ValueSettingsRead, ValueSettingsUpdate
from api.domains.business_value.service import BusinessValueService

business_value_router = APIRouter(prefix="/organizations/{organization_id}", tags=["business-value"])


@business_value_router.get("/value-settings", response_model=ValueSettingsRead)
def get_value_settings(
    organization_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[BusinessValueService, Injected(BusinessValueService)],
):
    return service.get_settings(organization_id, context)


@business_value_router.put("/value-settings", response_model=ValueSettingsRead)
def update_value_settings(
    organization_id: UUID,
    data: ValueSettingsUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    service: Annotated[BusinessValueService, Injected(BusinessValueService)],
):
    return service.update_settings(organization_id, data, context)

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response, status
from fastapi_injector import Injected

from api.domains.api_keys.models import ApiKeyCreate, ApiKeyCreated, ApiKeyRead
from api.domains.api_keys.service import ApiKeyService
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.utils import get_current_user

router = APIRouter(prefix="/auth/me/api-keys", tags=["api-keys"])


@router.post("", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
def create_api_key(
    data: ApiKeyCreate,
    context: Annotated[CurrentUserContext, Depends(get_current_user(require_organization=False))],
    response: Response,
    service: Annotated[ApiKeyService, Injected(ApiKeyService)],
):
    response.headers["Cache-Control"] = "no-store"
    return service.create(context, data)


@router.get("", response_model=list[ApiKeyRead])
def list_api_keys(
    context: Annotated[CurrentUserContext, Depends(get_current_user(require_organization=False))],
    service: Annotated[ApiKeyService, Injected(ApiKeyService)],
):
    return service.list_owned(context)


@router.delete("/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_api_key(
    key_id: UUID,
    context: Annotated[CurrentUserContext, Depends(get_current_user(require_organization=False))],
    service: Annotated[ApiKeyService, Injected(ApiKeyService)],
):
    service.revoke(context, key_id)

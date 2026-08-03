from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi_injector import Injected
from pydantic import BaseModel as PydanticBaseModel
from pydantic import Field

from api.domains.auth.models import CurrentUserContext
from api.domains.auth.token_service import SlackConfigTokenService
from api.domains.auth.utils import get_current_user
from api.infrastructure.slack.config_token import create_slack_app
from api.infrastructure.slack.manifest import build_slack_app_manifest

slack_router = APIRouter(prefix="/organizations/{organization_id}/slack", tags=["slack"])


class CreateSlackAppRequest(PydanticBaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(max_length=300, default="")
    background_color: str = Field(default="#4A154B", max_length=7)


class CreateSlackAppResponse(PydanticBaseModel):
    app_id: str
    bot_token_url: str
    app_token_url: str


@slack_router.post(
    "/apps",
    response_model=CreateSlackAppResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_slack_app_route(
    body: CreateSlackAppRequest,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    token_service: SlackConfigTokenService = Injected(SlackConfigTokenService),
) -> CreateSlackAppResponse:
    access_token = token_service.get_usable_access_token(context.user.id)
    manifest = build_slack_app_manifest(
        name=body.name,
        description=body.description,
        background_color=body.background_color,
    )
    app_id = create_slack_app(access_token, manifest)
    return CreateSlackAppResponse(
        app_id=app_id,
        bot_token_url=f"https://api.slack.com/apps/{app_id}/install-on-team",
        app_token_url=f"https://api.slack.com/apps/{app_id}/general",
    )

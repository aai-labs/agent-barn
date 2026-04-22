import uuid
from typing import Annotated, Callable

import jwt
from fastapi import Depends, HTTPException, Request
from fastapi.security import OAuth2PasswordBearer
from fastapi_injector import Injected
from injector import inject
from jwt.exceptions import InvalidTokenError

from api.core.config import Config
from api.domains.auth.exceptions import (
    CredentialsException,
    EmailNotVerifiedException,
    ForbiddenException,
)
from api.domains.auth.models import CurrentUserContext
from api.domains.auth.service import JWT_ENCODING_ALGORITHM
from api.domains.users.organization_users.models import OrganizationRole
from api.domains.users.organization_users.repository import OrganizationUserRepository
from api.domains.users.repository import UserRepository

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


def get_organization_id(request: Request) -> uuid.UUID | None:
    org_id = request.path_params.get("organization_id")
    if not org_id:
        return None
    try:
        if isinstance(org_id, uuid.UUID):
            return org_id
        return uuid.UUID(org_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid organization ID")


def get_authenticated_user(
    token: str,
    config: Config,
    user_repository: UserRepository,
    organization_user_repository: OrganizationUserRepository,
    organization_id: uuid.UUID | None = None,
    organization_roles: list[OrganizationRole] | None = None,
    verified_required: bool = False,
) -> CurrentUserContext:
    try:
        payload = jwt.decode(token, config.secret_signing_key, algorithms=[JWT_ENCODING_ALGORITHM])
        current_user_id: str | None = payload.get("user_id")
        token_type: str | None = payload.get("token_type")

        if current_user_id is None or token_type != "access":
            raise CredentialsException()
    except InvalidTokenError:
        raise CredentialsException()

    user = user_repository.get(uuid.UUID(current_user_id))
    if user is None:
        raise CredentialsException()

    if verified_required and user.email_verified_at is None:
        raise EmailNotVerifiedException()

    user_organizations = organization_user_repository.get_by_user_id(user.id)
    user_organization_map = {user_org.organization_id: user_org for user_org in user_organizations}
    organization_ids = list(user_organization_map.keys())
    user_organization = None

    if organization_id:
        user_organization = user_organization_map.get(organization_id, None)
        if not user_organization and not user.is_superuser:
            raise ForbiddenException(detail=f"User {user.id} does not have access to organization {organization_id}")

    if organization_roles and not user.is_superuser:
        if not user_organization or user_organization.role not in organization_roles:
            raise ForbiddenException(
                detail=f"User {user.id} does not have the required roles: {[role.value for role in organization_roles]}"
            )

    return CurrentUserContext(
        user=user,
        organization_ids=organization_ids,
        user_organization_map=user_organization_map,
        current_user_organization=user_organization,
    )


def get_current_user(
    organization_roles: list[OrganizationRole] | None = None,
    check_superuser: bool = False,
    verified_required: bool = False,
) -> Callable[..., CurrentUserContext]:
    @inject
    def wrapper(
        request: Request,
        token: Annotated[str, Depends(oauth2_scheme)],
        user_repository: UserRepository = Injected(UserRepository),
        organization_user_repository: OrganizationUserRepository = Injected(OrganizationUserRepository),
        config: Config = Injected(Config),
    ) -> CurrentUserContext:
        organization_id = get_organization_id(request)
        context = get_authenticated_user(
            token=token,
            config=config,
            user_repository=user_repository,
            organization_user_repository=organization_user_repository,
            organization_id=organization_id,
            organization_roles=organization_roles,
            verified_required=verified_required,
        )
        if check_superuser and not context.user.is_superuser:
            raise ForbiddenException(detail=f"User {context.user.id} is not a superuser")
        return context

    return wrapper

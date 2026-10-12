from typing import Annotated
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import RedirectResponse
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_injector import Injected
from pydantic import BaseModel

from api.core.config import Config
from api.domains.auth.google_sign_in import STATE_TTL_SECONDS, GoogleSignInService
from api.domains.auth.hashing import check_hash
from api.domains.auth.models import (
    AcceptInviteRequest,
    CredentialClass,
    CurrentUserContext,
    ForgotPasswordRequest,
    PasswordResetRequest,
    RefreshTokenRequest,
    Token,
    TokenData,
)
from api.domains.auth.service import AuthService
from api.domains.auth.utils import get_current_user
from api.domains.users.models import UserPasswordChange, UserRead, UserUpdate
from api.domains.users.service import UserService

auth_router = APIRouter(prefix="/auth", tags=["authentication"])

REFRESH_TOKEN_COOKIE_KEY = "refresh_token"
GOOGLE_SIGN_IN_COOKIE_KEY = "google_sign_in_nonce"
# Sent only to the Google sign-in routes, never to the rest of the API.
GOOGLE_SIGN_IN_COOKIE_PATH = "/api/v1/auth/google"


class ApiContextOrganization(BaseModel):
    organization_id: UUID
    role: str


class ApiContextRead(BaseModel):
    user_id: UUID
    credential_class: CredentialClass
    api_key_id: UUID | None
    api_key_access_mode: str | None
    is_platform_admin: bool
    organizations: list[ApiContextOrganization]
    openapi_url: str = "/api/v1/openapi.json"
    docs_url: str = "/api/v1/docs"
    llms_url: str = "/api/v1/llms.txt"


def _set_refresh_token_cookie(response: Response, refresh_token: str, config: Config):
    is_local_like = config.environment in {"local", "test"}
    response.set_cookie(
        key=REFRESH_TOKEN_COOKIE_KEY,
        value=refresh_token,
        httponly=True,
        secure=not is_local_like,
        samesite="lax" if is_local_like else "none",
        max_age=15 * 24 * 60 * 60,
    )


@auth_router.post("/login", response_model=Token)
def login_for_access_token(
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    user_service: UserService = Injected(UserService),
    auth_service: AuthService = Injected(AuthService),
    config: Config = Injected(Config),
):
    credential_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect email or password",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        user = user_service.get_user_by_email(form_data.username)
    except HTTPException:
        raise credential_exception
    if not user or not check_hash(form_data.password, user.hashed_password):
        raise credential_exception

    token_data = TokenData(
        user_id=str(user.id), stamp=user.security_stamp, credential_class=CredentialClass.USER_SESSION
    )
    token_pair = auth_service.create_token_pair(token_data)
    _set_refresh_token_cookie(response, token_pair.refresh_token, config)
    return token_pair


@auth_router.post("/refresh", response_model=Token)
def refresh_access_token(
    response: Response,
    request: Request,
    refresh_request: RefreshTokenRequest | None = None,
    user_service: UserService = Injected(UserService),
    auth_service: AuthService = Injected(AuthService),
    config: Config = Injected(Config),
):
    refresh_token = refresh_request.refresh_token if refresh_request else None
    if not refresh_token:
        refresh_token = request.cookies.get(REFRESH_TOKEN_COOKIE_KEY)

    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is required",
        )

    token = auth_service.verify_refresh_token(refresh_token)
    user = user_service.get_user(token.user_id)

    if user.security_stamp != token.stamp:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )

    auth_service.revoke_refresh_token(token)

    token_data = TokenData(
        user_id=str(user.id), stamp=user.security_stamp, credential_class=CredentialClass.USER_SESSION
    )
    new_access_token = auth_service.create_access_token(token_data)
    new_refresh_token = auth_service.create_refresh_token(token_data)

    _set_refresh_token_cookie(response, new_refresh_token, config)

    return Token(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
    )


@auth_router.get("/me", response_model=UserRead)
def get_current_user_context(
    context: Annotated[
        CurrentUserContext,
        Depends(get_current_user(verified_required=False, require_organization=False)),
    ],
    user_service: UserService = Injected(UserService),
):
    return user_service.to_user_read(context.user)


@auth_router.get("/context", response_model=ApiContextRead)
def get_api_context(
    context: Annotated[CurrentUserContext, Depends(get_current_user(require_organization=False))],
    response: Response,
):
    response.headers["Cache-Control"] = "no-store"
    return ApiContextRead(
        user_id=context.user.id,
        credential_class=context.credential_class,
        api_key_id=context.api_key_id,
        api_key_access_mode=context.api_key_access_mode.value if context.api_key_access_mode else None,
        is_platform_admin=context.user.is_platform_admin,
        organizations=[
            ApiContextOrganization(organization_id=membership.organization_id, role=membership.role.value)
            for membership in context.user_organization_map.values()
        ],
    )


@auth_router.post("/me", response_model=UserRead)
def update_current_user_profile(
    user_update: UserUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user(require_organization=False))],
    user_service: UserService = Injected(UserService),
):
    return user_service.update_current_user(context.user.id, user_update)


@auth_router.post("/me/change-password", response_model=Token)
def change_current_user_password(
    password_data: UserPasswordChange,
    response: Response,
    context: Annotated[CurrentUserContext, Depends(get_current_user(require_organization=False))],
    user_service: UserService = Injected(UserService),
    auth_service: AuthService = Injected(AuthService),
    config: Config = Injected(Config),
):
    user_service.change_password(context.user.id, password_data)
    user = user_service.get_user(context.user.id)
    token_data = TokenData(
        user_id=str(user.id), stamp=user.security_stamp, credential_class=CredentialClass.USER_SESSION
    )
    token_pair = auth_service.create_token_pair(token_data)
    _set_refresh_token_cookie(response, token_pair.refresh_token, config)
    return token_pair


@auth_router.post("/forgot-password")
def forgot_password(
    request: ForgotPasswordRequest,
    auth_service: AuthService = Injected(AuthService),
):
    auth_service.forgot_password(request)
    return {"message": "Password reset email sent if user exists."}


@auth_router.post("/signup")
def signup():
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Sign up with Google instead.",
    )


@auth_router.get("/google/start")
def start_google_sign_in(
    origin: str = Query(default="signup"),
    service: GoogleSignInService = Injected(GoogleSignInService),
    config: Config = Injected(Config),
):
    started = service.start(origin)
    response = RedirectResponse(started.redirect_url, status_code=status.HTTP_302_FOUND)
    if started.nonce is not None:
        # Lax, not None: the browser must send it on Google's top-level redirect back to
        # us, and nowhere else.
        response.set_cookie(
            key=GOOGLE_SIGN_IN_COOKIE_KEY,
            value=started.nonce,
            max_age=STATE_TTL_SECONDS,
            path=GOOGLE_SIGN_IN_COOKIE_PATH,
            httponly=True,
            secure=config.environment not in {"local", "test"},
            samesite="lax",
        )
    return response


@auth_router.get("/google/callback")
def finish_google_sign_in(
    request: Request,
    code: str | None = Query(default=None),
    state: str | None = Query(default=None),
    error: str | None = Query(default=None),
    service: GoogleSignInService = Injected(GoogleSignInService),
    config: Config = Injected(Config),
):
    outcome = service.complete(
        code=code, state=state, error=error, nonce=request.cookies.get(GOOGLE_SIGN_IN_COOKIE_KEY)
    )
    response = RedirectResponse(outcome.redirect_url, status_code=status.HTTP_302_FOUND)
    # Single use: whatever happened, this browser's attempt is over.
    response.delete_cookie(
        key=GOOGLE_SIGN_IN_COOKIE_KEY,
        path=GOOGLE_SIGN_IN_COOKIE_PATH,
        httponly=True,
        secure=config.environment not in {"local", "test"},
        samesite="lax",
    )
    if outcome.refresh_token is not None:
        _set_refresh_token_cookie(response, outcome.refresh_token, config)
    return response


@auth_router.post("/reset-password")
def reset_password(
    reset_request: PasswordResetRequest,
    auth_service: AuthService = Injected(AuthService),
):
    auth_service.reset_password(reset_request)
    return {"message": "Password reset successfully."}


@auth_router.post("/set-password")
def set_password(
    request: AcceptInviteRequest,
    auth_service: AuthService = Injected(AuthService),
):
    auth_service.accept_invite(request)
    return {"message": "Password set successfully."}


@auth_router.post("/logout")
def logout(response: Response, config: Config = Injected(Config)):
    is_local_like = config.environment in {"local", "test"}
    response.delete_cookie(
        key=REFRESH_TOKEN_COOKIE_KEY,
        httponly=True,
        secure=not is_local_like,
        samesite="lax" if is_local_like else "none",
    )
    return {"message": "Successfully logged out"}

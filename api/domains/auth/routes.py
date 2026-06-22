from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    status,
)
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_injector import Injected

from api.core.config import Config
from api.domains.auth.hashing import check_hash
from api.domains.auth.models import (
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

    token_data = TokenData(user_id=str(user.id), stamp=user.security_stamp)
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

    token_data = TokenData(user_id=str(user.id), stamp=user.security_stamp)
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
        CurrentUserContext, Depends(get_current_user(verified_required=False))
    ],
    user_service: UserService = Injected(UserService),
):
    return user_service.to_user_read(context.user)


@auth_router.post("/me", response_model=UserRead)
def update_current_user_profile(
    user_update: UserUpdate,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    user_service: UserService = Injected(UserService),
):
    return user_service.update_current_user(context.user.id, user_update)


@auth_router.post("/me/change-password", response_model=Token)
def change_current_user_password(
    password_data: UserPasswordChange,
    response: Response,
    context: Annotated[CurrentUserContext, Depends(get_current_user())],
    user_service: UserService = Injected(UserService),
    auth_service: AuthService = Injected(AuthService),
    config: Config = Injected(Config),
):
    user_service.change_password(context.user.id, password_data)
    user = user_service.get_user(context.user.id)
    token_data = TokenData(user_id=str(user.id), stamp=user.security_stamp)
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
        detail="Self-registration is disabled. Contact an administrator.",
    )


@auth_router.post("/reset-password")
def reset_password(
    reset_request: PasswordResetRequest,
    auth_service: AuthService = Injected(AuthService),
):
    auth_service.reset_password(reset_request)
    return {"message": "Password reset successfully."}


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

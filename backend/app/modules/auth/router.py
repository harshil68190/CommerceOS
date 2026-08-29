"""
modules/auth/router.py

Responsibility
--------------
HTTP layer only: request validation (via Pydantic schemas, handled
automatically by FastAPI), calling exactly one `AuthService` method, and
shaping the response. No business logic lives here ? if you find
yourself writing an `if` statement that isn't about HTTP status codes in
this file, it belongs in `service.py` instead.
"""

from fastapi import APIRouter, Depends, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from redis import Redis

from app.core.config import get_settings
from app.db.redis_client import get_redis
from app.models.user import User
from app.modules.auth.dependencies import get_current_active_user
from app.modules.auth.rate_limit import enforce_rate_limit
from app.modules.auth.service import AuthService, get_auth_service
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])


def _refresh_cookie_name() -> str:
    return settings.REFRESH_TOKEN_COOKIE_NAME


def _refresh_request_from_cookie(request: Request) -> RefreshRequest:
    """Refresh tokens are cookie-only and never accepted in JSON bodies."""
    return RefreshRequest(refresh_token=request.cookies.get(_refresh_cookie_name(), ""))


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new customer account",
)
def register(
    request: Request,
    payload: RegisterRequest,
    redis: Redis = Depends(get_redis),
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """Creates a new user account. Always registers as CUSTOMER ? role
    escalation is a separate, explicitly-admin-gated action, not
    something this public endpoint accepts as input."""
    enforce_rate_limit(
        redis,
        request=request,
        scope="register",
        identifier=payload.email,
        limit=settings.AUTH_REGISTER_RATE_LIMIT,
    )
    user = auth_service.register(payload)
    return UserResponse.model_validate(user)


@router.post("/login")
def login(
    request: Request,
    form_data: OAuth2PasswordRequestForm = Depends(),
    redis: Redis = Depends(get_redis),
    auth_service: AuthService = Depends(get_auth_service),
):
    payload = LoginRequest(email=form_data.username, password=form_data.password)
    enforce_rate_limit(
        redis,
        request=request,
        scope="login",
        identifier=payload.email,
        limit=settings.AUTH_LOGIN_RATE_LIMIT,
    )
    token_response = auth_service.login(payload)
    response = JSONResponse(content=TokenResponse(access_token=token_response.access_token).model_dump())
    response.set_cookie(
        key=_refresh_cookie_name(),
        value=token_response.refresh_token,
        httponly=True,
        secure=settings.REFRESH_TOKEN_COOKIE_SECURE,
        samesite=settings.REFRESH_TOKEN_COOKIE_SAME_SITE,
        path="/",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )
    return response


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange a valid refresh token for a new token pair",
)
def refresh(
    request: Request,
    redis: Redis = Depends(get_redis),
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Rotates the given refresh token: the old one is invalidated and a
    brand-new access + refresh pair is returned. See
    `AuthService.refresh` for the rotation mechanics."""
    normalized_payload = _refresh_request_from_cookie(request)
    enforce_rate_limit(
        redis,
        request=request,
        scope="refresh",
        limit=settings.AUTH_REFRESH_RATE_LIMIT,
    )
    token_response = auth_service.refresh(normalized_payload)
    response = JSONResponse(content=TokenResponse(access_token=token_response.access_token).model_dump())
    response.set_cookie(
        key=_refresh_cookie_name(),
        value=token_response.refresh_token,
        httponly=True,
        secure=settings.REFRESH_TOKEN_COOKIE_SECURE,
        samesite=settings.REFRESH_TOKEN_COOKIE_SAME_SITE,
        path="/",
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
    )
    return response


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token",
)
def logout(
    request: Request,
    _current_user: User = Depends(get_current_active_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> Response:
    """Revokes the given refresh token so it can no longer be used to
    obtain new access tokens. The caller's current access token is left
    to expire naturally (it's stateless and short-lived by design ? see
    the architecture doc's JWT Lifecycle section)."""
    normalized_payload = _refresh_request_from_cookie(request)
    auth_service.logout(normalized_payload)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(key=_refresh_cookie_name(), path="/")
    return response


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the currently authenticated user's profile",
)
def get_me(current_user: User = Depends(get_current_active_user)) -> UserResponse:
    """Returns the profile of whoever the presented access token
    belongs to. No service-layer call needed ? `get_current_active_user`
    has already done all the work of resolving and validating the
    user."""
    return UserResponse.model_validate(current_user)

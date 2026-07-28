"""
modules/auth/router.py

Responsibility
--------------
HTTP layer only: request validation (via Pydantic schemas, handled
automatically by FastAPI), calling exactly one `AuthService` method, and
shaping the response. No business logic lives here — if you find
yourself writing an `if` statement that isn't about HTTP status codes in
this file, it belongs in `service.py` instead.
"""

from fastapi import APIRouter, Depends, status

from app.models.user import User
from app.modules.auth.dependencies import get_current_active_user
from app.modules.auth.service import AuthService, get_auth_service
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from fastapi.security import OAuth2PasswordRequestForm

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new customer account",
)
def register(
    payload: RegisterRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> UserResponse:
    """Creates a new user account. Always registers as CUSTOMER — role
    escalation is a separate, explicitly-admin-gated action, not
    something this public endpoint accepts as input."""
    user = auth_service.register(payload)
    return UserResponse.model_validate(user)


@router.post("/login")
def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    auth_service: AuthService = Depends(get_auth_service),
):
    payload = LoginRequest(
        email=form_data.username,
        password=form_data.password,
    )
    return auth_service.login(payload)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    summary="Exchange a valid refresh token for a new token pair",
)
def refresh(
    payload: RefreshRequest,
    auth_service: AuthService = Depends(get_auth_service),
) -> TokenResponse:
    """Rotates the given refresh token: the old one is invalidated and a
    brand-new access + refresh pair is returned. See
    `AuthService.refresh` for the rotation mechanics."""
    return auth_service.refresh(payload)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Revoke a refresh token",
)
def logout(
    payload: RefreshRequest,
    # Requiring a valid access token here (not just the refresh token in
    # the body) ensures logout is itself an authenticated action — an
    # attacker who merely intercepted a refresh token, with no valid
    # access token, cannot use this endpoint as an oracle to probe
    # tokens.
    _current_user: User = Depends(get_current_active_user),
    auth_service: AuthService = Depends(get_auth_service),
) -> None:
    """Revokes the given refresh token so it can no longer be used to
    obtain new access tokens. The caller's current access token is left
    to expire naturally (it's stateless and short-lived by design — see
    the architecture doc's JWT Lifecycle section)."""
    auth_service.logout(payload)


@router.get(
    "/me",
    response_model=UserResponse,
    status_code=status.HTTP_200_OK,
    summary="Get the currently authenticated user's profile",
)
def get_me(current_user: User = Depends(get_current_active_user)) -> UserResponse:
    """Returns the profile of whoever the presented access token
    belongs to. No service-layer call needed — `get_current_active_user`
    has already done all the work of resolving and validating the
    user."""
    return UserResponse.model_validate(current_user)

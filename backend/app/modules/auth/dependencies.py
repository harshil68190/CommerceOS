"""
modules/auth/dependencies.py

Responsibility
--------------
FastAPI dependencies that other endpoints (in this module and, in future
milestones, catalog/orders/admin/etc.) use to require authentication
and/or a specific role:

    def some_admin_only_endpoint(user: User = Depends(require_admin)): ...

`get_current_user` does the actual work: extract the bearer token,
decode/validate it as an access token, load the corresponding `User`.
Everything else in this file builds on top of it.

Note this is intentionally the ONLY place a raw JWT access token is
turned into a `User` object — no other module should decode a token
itself.
"""

import uuid

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import TokenType, decode_token
from app.db.session import get_db
from app.models.user import User, UserRole
from app.modules.auth.repository import UserRepository

settings = get_settings()

# `tokenUrl` here is only used by Swagger UI to know which endpoint to
# redirect to from its "Authorize" button — it does NOT force
# /auth/login to accept form-encoded input. The actual login endpoint
# takes a JSON body (`LoginRequest`); this scheme only extracts whatever
# bearer token is present in the `Authorization` header on protected
# requests, regardless of how the token was originally obtained.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Decodes the bearer access token and loads the corresponding user.

    Raises `UnauthorizedError` if the token is missing/invalid/expired,
    of the wrong type (e.g. a refresh token presented here), or no
    longer corresponds to an existing user (e.g. the account was
    deleted after the token was issued).

    Deliberately does NOT check `is_active` here — that's
    `get_current_active_user`'s job, kept separate so a future endpoint
    that genuinely needs to identify a deactivated user (e.g. an appeal/
    reactivation flow) can depend on `get_current_user` alone.
    """
    claims = decode_token(token, expected_type=TokenType.ACCESS)

    try:
        user_id = uuid.UUID(claims["sub"])
    except (KeyError, ValueError) as exc:
        raise UnauthorizedError("Invalid or expired token.") from exc

    repository = UserRepository(db)
    user = repository.get_by_id(user_id)
    if user is None:
        raise UnauthorizedError("Invalid or expired token.")

    return user


def get_current_active_user(user: User = Depends(get_current_user)) -> User:
    """Same as `get_current_user`, but additionally rejects deactivated
    accounts. This is the dependency the large majority of protected
    endpoints should use."""
    if not user.is_active:
        raise ForbiddenError("This account has been deactivated.")
    return user


def _require_role(user: User, *allowed_roles: UserRole) -> User:
    """Shared role-check used by the three role-specific dependencies
    below, so the "wrong role" error is raised identically everywhere
    rather than reimplemented per role."""
    if user.role not in allowed_roles:
        raise ForbiddenError(
            f"This action requires one of the following roles: "
            f"{', '.join(role.value for role in allowed_roles)}."
        )
    return user


def require_admin(user: User = Depends(get_current_active_user)) -> User:
    """Dependency for endpoints restricted to admins only."""
    return _require_role(user, UserRole.ADMIN)


def require_seller(user: User = Depends(get_current_active_user)) -> User:
    """Dependency for endpoints restricted to sellers. Admins are
    intentionally NOT included here — an admin acting as a seller (e.g.
    to manage a seller's listing) should go through an explicit admin
    endpoint, not silently pass a seller-only check."""
    return _require_role(user, UserRole.SELLER)


def require_customer(user: User = Depends(get_current_active_user)) -> User:
    """Dependency for endpoints restricted to customers only (e.g.
    placing an order)."""
    return _require_role(user, UserRole.CUSTOMER)

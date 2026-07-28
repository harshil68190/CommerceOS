"""
modules/auth/service.py

Responsibility
--------------
`AuthService` holds every piece of business logic for authentication:
registration rules, credential verification, token issuance, refresh
rotation, and logout revocation. `router.py` calls exactly one method
per endpoint and does nothing else — this is the Service Layer pattern
from the architecture doc, applied concretely.

Two collaborators are injected (Dependency Inversion, not constructed
internally):
  - `UserRepository` for persistence
  - a Redis client for refresh-token tracking

Refresh-token design
---------------------
JWTs can't be "unsigned" once issued, so revocation (logout, or
detecting a stolen/reused refresh token) needs external state. Rather
than adding a new `refresh_tokens` Postgres table (out of scope for this
milestone — only a `User` model was requested), active refresh tokens
are tracked in Redis as `refresh_token:{jti} -> user_id`, with a TTL
matching the token's own expiry. This gives us:
  - O(1) validity check on every refresh
  - single-use rotation: each refresh call deletes the old key and
    issues a brand-new refresh token with a new jti and key
  - instant logout: deleting the key makes that refresh token
    unusable immediately, even though the JWT itself would otherwise
    still verify until its `exp` claim passes
Access tokens remain fully stateless (per the architecture doc) — no
Redis lookup happens on ordinary authenticated requests, only on the
much rarer refresh/logout calls.
"""

import uuid
from datetime import datetime, timezone

from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, ForbiddenError, UnauthorizedError
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.redis_client import get_redis
from app.db.session import get_db
from app.models.user import User
from app.modules.auth.repository import UserRepository
from app.schemas.auth import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse

settings = get_settings()

# A precomputed dummy hash used solely to keep `authenticate()`'s runtime
# roughly constant whether or not the email exists. Without this, a
# nonexistent email returns almost instantly (no hash comparison ever
# runs) while a real email takes bcrypt's full verification time — an
# attacker measuring response latency could use that to enumerate valid
# accounts. Generated once at import time, never persisted anywhere.
_DUMMY_HASH = hash_password("dummy-password-for-timing-parity-only!1")

# Redis key prefix for tracked (valid, unrevoked) refresh tokens.
_REFRESH_TOKEN_KEY_PREFIX = "refresh_token:"


class AuthService:
    """Business logic for registration, login, token refresh, and
    logout. Holds no HTTP concepts — see `modules/auth/router.py` for
    the thin HTTP-facing layer that calls into this class."""

    def __init__(self, repository: UserRepository, db: Session, redis: Redis) -> None:
        self.repository = repository
        self.db = db
        self.redis = redis

    # --- Registration ---------------------------------------------------

    def register(self, payload: RegisterRequest) -> User:
        """
        Registers a new user.

        Uniqueness is checked proactively (clear, specific errors for
        the honest case) with the database's own unique constraints on
        `email`/`username` as the final safety net against a race
        between two concurrent registrations with the same value.
        """
        if self.repository.exists(email=payload.email):
            raise ConflictError("An account with this email already exists.")
        if self.repository.exists(username=payload.username):
            raise ConflictError("This username is already taken.")

        user = User(
            email=payload.email,
            username=payload.username,
            hashed_password=hash_password(payload.password),
            first_name=payload.first_name,
            last_name=payload.last_name,
            phone=payload.phone,
        )
        # role defaults to CUSTOMER (see User model) — registration
        # through this public endpoint can never self-assign ADMIN or
        # SELLER; role escalation is an explicit admin action in a
        # future milestone, never something a request body controls.

        created = self.repository.create(user)
        self.db.commit()
        return created

    # --- Authentication / login ---------------------------------------------------

    def authenticate(self, payload: LoginRequest) -> User:
        """
        Verifies email + password, returning the authenticated `User`.

        Raises `UnauthorizedError` for any credential mismatch (unknown
        email OR wrong password) with the exact same message either way
        — distinguishing the two in the response would let an attacker
        enumerate which emails are registered.
        """
        user = self.repository.get_by_email(payload.email)

        if user is None:
            # Still run a (discarded) password verification against the
            # dummy hash so this branch takes comparable time to the
            # "user exists but password is wrong" branch below. See
            # `_DUMMY_HASH` module comment.
            verify_password(payload.password, _DUMMY_HASH)
            raise UnauthorizedError("Invalid email or password.")

        if not verify_password(payload.password, user.hashed_password):
            raise UnauthorizedError("Invalid email or password.")

        if not user.is_active:
            raise ForbiddenError("This account has been deactivated.")

        self.repository.update(user, last_login=datetime.now(timezone.utc))
        self.db.commit()
        return user

    def login(self, payload: LoginRequest) -> TokenResponse:
        """Authenticates the user and issues a fresh access/refresh
        token pair."""
        user = self.authenticate(payload)
        return self._issue_token_pair(user)

    # --- Refresh ---------------------------------------------------

    def refresh(self, payload: RefreshRequest) -> TokenResponse:
        """
        Exchanges a valid, unrevoked refresh token for a brand-new
        access/refresh pair.

        Implements rotation: the presented refresh token's Redis entry
        is deleted (single use) before the new pair is issued, so a
        captured-and-replayed old refresh token stops working the
        moment the legitimate client refreshes once.
        """
        claims = decode_token(payload.refresh_token, expected_type=TokenType.REFRESH)
        jti = claims["jti"]
        redis_key = f"{_REFRESH_TOKEN_KEY_PREFIX}{jti}"

        if self.redis.get(redis_key) is None:
            # Either never issued by us, already used once (rotated
            # away), or explicitly revoked via logout.
            raise UnauthorizedError("Invalid or expired token.")

        self.redis.delete(redis_key)

        user = self.repository.get_by_id(uuid.UUID(claims["sub"]))
        if user is None or not user.is_active:
            raise UnauthorizedError("Invalid or expired token.")

        return self._issue_token_pair(user)

    # --- Logout ---------------------------------------------------

    def logout(self, payload: RefreshRequest) -> None:
        """
        Revokes the given refresh token so it can no longer be used to
        obtain new access tokens.

        Deliberately tolerant of an already-invalid/expired/unknown
        token: logout is idempotent by design — calling it twice, or
        with a token that already expired naturally, should never
        surface an error to the client. The one exception is a
        structurally invalid token (wrong signature/type), which still
        indicates the caller sent something wrong.
        """
        claims = decode_token(payload.refresh_token, expected_type=TokenType.REFRESH)
        redis_key = f"{_REFRESH_TOKEN_KEY_PREFIX}{claims['jti']}"
        self.redis.delete(redis_key)  # no-op if the key is already gone

    # --- Internal helpers ---------------------------------------------------

    def _issue_token_pair(self, user: User) -> TokenResponse:
        """Shared by `login` and `refresh`: creates a new access +
        refresh token pair and tracks the new refresh token in Redis."""
        access = create_access_token(subject=str(user.id), role=user.role.value)
        refresh_token = create_refresh_token(subject=str(user.id), role=user.role.value)

        redis_key = f"{_REFRESH_TOKEN_KEY_PREFIX}{refresh_token.jti}"
        ttl_seconds = settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60
        self.redis.set(redis_key, str(user.id), ex=ttl_seconds)

        return TokenResponse(access_token=access.token, refresh_token=refresh_token.token)


# --- FastAPI dependency providers ---------------------------------------------------
#
# These small factory functions are what make AuthService's dependencies
# (repository, db, redis) injectable via FastAPI's `Depends()` chain
# rather than constructed ad hoc inside each route. This is the
# Dependency Injection pattern from the architecture doc in its most
# direct form: `get_auth_service` is the one place that knows how to
# assemble an `AuthService`; routers only ever ask for the finished
# object via `Depends(get_auth_service)`.
#
# Chaining `Depends()` calls like this (get_db -> get_user_repository ->
# get_auth_service) means FastAPI resolves and shares a single request-
# scoped `Session`/`Redis` client across the whole dependency graph for
# one request, and the exact same chain can be overridden wholesale in
# tests via `app.dependency_overrides[get_auth_service] = ...`.

from fastapi import Depends  # noqa: E402  (kept near point of use for readability)


def get_user_repository(db: Session = Depends(get_db)) -> UserRepository:
    """FastAPI dependency: builds a `UserRepository` bound to the
    current request's DB session."""
    return UserRepository(db)


def get_auth_service(
    repository: UserRepository = Depends(get_user_repository),
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> AuthService:
    """FastAPI dependency: builds a fully-wired `AuthService` for the
    current request. This is the single function `router.py` depends on
    — it never constructs `AuthService` or `UserRepository` itself."""
    return AuthService(repository=repository, db=db, redis=redis)

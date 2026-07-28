"""
core/security.py

Responsibility
--------------
The single place in the application that knows how to hash/verify
passwords and create/decode JWTs. No router, service, or repository
should import `pwdlib` or `jwt` directly — they call the functions in
this module instead. This keeps a future change (e.g. swapping bcrypt
for argon2, or HS256 for RS256) to exactly one file.

Two independent concerns live here, kept in clearly separated sections:
  1. Password hashing (pwdlib + bcrypt)
  2. JWT access/refresh token creation and decoding (PyJWT)

Both are pure functions with no DB/Redis/HTTP dependencies — they are
easy to unit test in isolation and safe to call from any layer.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import get_settings
from app.core.exceptions import UnauthorizedError

settings = get_settings()

# --- Password hashing ---------------------------------------------------
#
# Explicitly configured with only `BcryptHasher` (per this milestone's
# spec: "Use pwdlib or Passlib with bcrypt"), rather than
# `PasswordHash.recommended()` — pwdlib's recommended default is
# actually Argon2, which pulls in an extra `argon2-cffi` dependency this
# milestone deliberately doesn't add. Bcrypt is a well-understood,
# battle-tested choice and exactly what was asked for; Argon2 can be
# introduced later as a deliberate upgrade, not a default pulled in
# incidentally.
#
# Centralizing this as a module-level singleton (not re-constructed per
# call) avoids the (small but real) cost of re-reading hasher config on
# every single login/registration request.
_password_hasher = PasswordHash([BcryptHasher()])


def hash_password(plain_password: str) -> str:
    """
    Hashes a plaintext password for storage.

    The plaintext password is NEVER stored, logged, or returned anywhere
    past this function call — only the resulting hash is persisted, on
    `User.hashed_password`.
    """
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plaintext password attempt against a stored hash.

    Returns False on any mismatch (including a malformed/corrupted hash)
    rather than raising, so callers (AuthService.authenticate) can treat
    "wrong password" and "verification error" identically — both should
    produce the same generic "invalid credentials" response to the
    client, never a different error that would help an attacker
    distinguish a bad password from a bad hash format.
    """
    try:
        return _password_hasher.verify(plain_password, hashed_password)
    except Exception:
        return False


# --- JWT ---------------------------------------------------------------


class TokenType(str, Enum):
    """
    Distinguishes access vs. refresh tokens inside the JWT payload itself
    (the `type` claim). This matters because both token types are signed
    with the same secret and algorithm — without an explicit `type`
    claim, nothing would stop a client from presenting a refresh token
    where an access token is expected (or vice versa), which would be a
    real privilege/security bug, not just a bookkeeping one.
    """

    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True)
class IssuedToken:
    """Return value of the token-creation functions below: the encoded
    JWT string plus the metadata the caller (AuthService) needs to
    persist/track it (its `jti` and expiry)."""

    token: str
    jti: str
    expires_at: datetime


def _create_token(
    *, subject: str, role: str, token_type: TokenType, expires_delta: timedelta
) -> IssuedToken:
    """
    Shared internal builder for both access and refresh tokens — access
    and refresh tokens differ only in claimed `type` and lifetime, so the
    actual encoding logic is written once here rather than duplicated.

    Included claims:
      sub  - the user's id (str form of the UUID)
      role - the user's role at the time of issuance (used by
             authorization dependencies without a DB round-trip on every
             request)
      type - "access" or "refresh", see `TokenType` above
      iat  - issued-at time, standard JWT claim, useful for auditing
      exp  - expiry time, enforced automatically by PyJWT on decode
      jti  - a unique token ID. For refresh tokens, this is what
             AuthService stores in Redis to support single-use rotation
             and logout/revocation, since a JWT's signature alone cannot
             be "un-signed" once issued.
    """
    now = datetime.now(timezone.utc)
    expires_at = now + expires_delta
    jti = str(uuid.uuid4())

    payload = {
        "sub": subject,
        "role": role,
        "type": token_type.value,
        "iat": now,
        "exp": expires_at,
        "jti": jti,
    }
    encoded = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return IssuedToken(token=encoded, jti=jti, expires_at=expires_at)


def create_access_token(*, subject: str, role: str) -> IssuedToken:
    """Issues a short-lived access token (15 minutes by default, see
    Settings.ACCESS_TOKEN_EXPIRE_MINUTES) used to authenticate ordinary
    API requests."""
    return _create_token(
        subject=subject,
        role=role,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(*, subject: str, role: str) -> IssuedToken:
    """Issues a long-lived refresh token (7 days by default, see
    Settings.REFRESH_TOKEN_EXPIRE_DAYS) used solely to obtain new access
    tokens via POST /auth/refresh — never accepted as authentication on
    any other endpoint (enforced by the `type` claim check in
    `decode_token` callers)."""
    return _create_token(
        subject=subject,
        role=role,
        token_type=TokenType.REFRESH,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def decode_token(token: str, *, expected_type: TokenType) -> dict:
    """
    Decodes and validates a JWT, returning its claims as a dict.

    Raises `UnauthorizedError` (a plain domain exception, not
    `fastapi.HTTPException` — see `core/exceptions.py` for why) if the
    token is expired, malformed, signed with the wrong key, or of the
    wrong `type` (e.g. a refresh token presented where an access token
    is required). Callers never need to know *why* a token was
    rejected beyond that — returning different errors for "expired" vs
    "tampered with" would leak information useful to an attacker probing
    the auth system.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.PyJWTError as exc:
        raise UnauthorizedError("Invalid or expired token.") from exc

    if payload.get("type") != expected_type.value:
        raise UnauthorizedError("Invalid or expired token.")

    return payload

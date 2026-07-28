"""
schemas/auth.py

Responsibility
--------------
Every request/response shape the auth module's API exposes. Kept
separate per-purpose (register vs. login vs. token response) rather than
one bloated "UserSchema" with every field optional, so each endpoint's
contract is explicit and FastAPI/Swagger documents exactly what each
endpoint actually needs and returns.

Password strength and confirmation-matching validation live here (at the
schema/input-validation layer) rather than in `AuthService`, because
these are pure request-shape rules ("is this input well-formed") as
opposed to business rules that need the database ("is this email already
taken") — that distinction is exactly why the architecture doc separates
schema validation from service-layer business logic.
"""

import re
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

from app.models.user import UserRole

# Minimum acceptable password length. Called out as a named constant
# (not a magic number in the validator) so the policy is easy to find
# and change in one place.
MIN_PASSWORD_LENGTH = 8

# A strong password must contain at least one lowercase letter, one
# uppercase letter, one digit, and one special character. This is
# expressed as one compiled pattern per requirement rather than one
# giant regex, so a failing password can be told exactly what it's
# missing instead of a single opaque "invalid password" message.
_LOWERCASE_RE = re.compile(r"[a-z]")
_UPPERCASE_RE = re.compile(r"[A-Z]")
_DIGIT_RE = re.compile(r"\d")
_SPECIAL_CHAR_RE = re.compile(r"[!@#$%^&*()\-_=+\[\]{};:'\",.<>/?\\|`~]")


def _validate_password_strength(password: str) -> str:
    """Shared password-policy check used by RegisterRequest below.

    Raises `ValueError` (which Pydantic converts into a 422 validation
    error automatically) with a message describing exactly what
    requirement was not met.
    """
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters long.")
    if not _LOWERCASE_RE.search(password):
        raise ValueError("Password must contain at least one lowercase letter.")
    if not _UPPERCASE_RE.search(password):
        raise ValueError("Password must contain at least one uppercase letter.")
    if not _DIGIT_RE.search(password):
        raise ValueError("Password must contain at least one digit.")
    if not _SPECIAL_CHAR_RE.search(password):
        raise ValueError("Password must contain at least one special character.")
    return password


class RegisterRequest(BaseModel):
    """Request body for POST /auth/register."""

    email: EmailStr
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_]+$")
    password: str
    confirm_password: str
    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)

    @field_validator("password")
    @classmethod
    def _check_password_strength(cls, value: str) -> str:
        return _validate_password_strength(value)

    @model_validator(mode="after")
    def _check_passwords_match(self) -> "RegisterRequest":
        # A model-level (not field-level) validator, since this rule
        # depends on two fields at once — Pydantic only allows
        # field_validator to see the single field it's declared for.
        if self.password != self.confirm_password:
            raise ValueError("password and confirm_password do not match.")
        return self


class LoginRequest(BaseModel):
    """Request body for POST /auth/login."""

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Request body for POST /auth/refresh and POST /auth/logout — both
    operate on a refresh token, so they share this shape."""

    refresh_token: str


class UserResponse(BaseModel):
    """Public-facing representation of a User, returned by
    /auth/register and GET /auth/me. Deliberately excludes
    `hashed_password` — it is never serialized to a client under any
    circumstance."""

    model_config = ConfigDict(from_attributes=True)  # allows building this
    # schema directly from a SQLAlchemy `User` ORM instance:
    # UserResponse.model_validate(user_orm_object)

    id: uuid.UUID
    email: EmailStr
    username: str
    first_name: str
    last_name: str
    phone: str | None
    is_active: bool
    is_verified: bool
    role: UserRole
    created_at: datetime
    last_login: datetime | None


class TokenResponse(BaseModel):
    """Response body for POST /auth/login and POST /auth/refresh."""

    access_token: str
    refresh_token: str
    token_type: str = "bearer"

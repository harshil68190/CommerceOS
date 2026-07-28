"""
models/user.py

Responsibility
--------------
Defines the `User` ORM model — the persisted account record for every
customer, seller, and admin in CommerceOS — and the `UserRole` enum that
drives authorization decisions throughout the auth module.

This is a pure persistence-layer artifact: it has no knowledge of
passwords being "hashed correctly," no knowledge of JWTs, and no
knowledge of HTTP. Those concerns belong to `core/security.py` and the
auth module's service layer, respectively. Keeping the model this "dumb"
is a direct application of Single Responsibility: this class's only job
is describing what a user record looks like in the database.

Uses SQLAlchemy 2.0's typed declarative style (`Mapped[...]` /
`mapped_column(...)`) rather than the legacy `Column(...)` style, so
static type checkers (mypy/pyright) and IDEs can verify attribute types
against actual Python types, not just infer them from the database type.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum as SAEnum
from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserRole(str, enum.Enum):
    """
    The three account roles CommerceOS supports, per the architecture
    doc's decision to use a single `users` table with a `role` column
    rather than separate customer/seller/admin tables — a role is an
    attribute of a user, not a fundamentally different entity.

    Inherits from `str` as well as `enum.Enum` so the enum value
    serializes as a plain string in JSON responses and compares equal to
    its string value (`UserRole.ADMIN == "admin"`), which keeps Pydantic
    schemas and JWT claims (which must be plain strings/JSON) simple.
    """

    ADMIN = "admin"
    SELLER = "seller"
    CUSTOMER = "customer"


class User(Base):
    """
    ORM model for a CommerceOS user account.

    Notes on specific column choices:
    - `id` is a UUID (not an auto-increment int) generated client-side
      via `uuid.uuid4`, consistent with the architecture doc's decision
      to avoid sequential, enumerable public-facing IDs.
    - `email` and `username` each carry a unique index — enforced at the
      database level as the final source of truth, even though the
      service layer also checks uniqueness proactively (defense in
      depth: a race between two concurrent registrations with the same
      email must still be impossible, not just "checked for").
    - `hashed_password` is named explicitly (not `password`) so it is
      never mistaken for a plaintext field by anyone reading calling
      code — the raw password is never stored or logged anywhere.
    - `created_at`/`updated_at` use `server_default=func.now()` (a
      database-computed default), not a Python-side `datetime.utcnow()`
      default, so the timestamp is authoritative even if multiple app
      servers with slightly skewed clocks are writing concurrently.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )

    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    username: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)

    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)
    is_verified: Mapped[bool] = mapped_column(default=False, nullable=False)

    role: Mapped[UserRole] = mapped_column(
        SAEnum(
            UserRole,
            name="user_role",
            native_enum=True,
            # SQLAlchemy's default behavior persists a Python Enum's
            # *member name* (e.g. "ADMIN") in the database, not its
            # *value* (e.g. "admin"). Since `UserRole` values are what
            # get serialized into JWT claims and API responses
            # everywhere else, leaving the default would mean the raw
            # database representation ("ADMIN") silently disagrees with
            # every other representation of the same role in the system
            # ("admin") — confusing for anyone querying the DB directly,
            # and a footgun for future raw-SQL migrations/reports.
            # `values_callable` makes the DB store the lowercase value
            # instead, matching UserRole.value everywhere else.
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        default=UserRole.CUSTOMER,
        nullable=False,
    )

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )
    last_login: Mapped[datetime | None] = mapped_column(nullable=True)

    def __repr__(self) -> str:
        # Deliberately excludes hashed_password from the repr — even a
        # hash showing up in a stray log/debugger dump is avoidable risk
        # for zero benefit.
        return f"<User id={self.id} email={self.email} role={self.role}>"

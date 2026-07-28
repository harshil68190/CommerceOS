"""
modules/auth/repository.py

Responsibility
--------------
`UserRepository` is the ONLY place in the codebase that writes
SQLAlchemy queries against the `users` table. `AuthService` depends on
this class's methods, never on a raw `Session.query(...)`/`select(...)`
call of its own — this is the Repository Pattern's whole point: swap
Postgres for something else, or change how a "get by email" lookup is
optimized (e.g. add a covering index, change case-sensitivity), and
exactly one file changes.

Every method takes/returns plain domain objects (`User` ORM instances or
primitives) — no HTTP concepts, no Pydantic schemas. This keeps the
repository usable from contexts other than a web request (e.g. a future
seed script in `scripts/`).
"""

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    """Data-access layer for `User` records."""

    def __init__(self, db: Session) -> None:
        # The session is injected (Dependency Inversion), not constructed
        # here — this repository never decides how to obtain a DB
        # connection, it only uses the one it's handed. This is what
        # makes it trivially fake-able in service-layer unit tests.
        self.db = db

    def create(self, user: User) -> User:
        """
        Persists a new `User` row.

        Takes an already-constructed `User` instance (built by
        `AuthService.register`, which is responsible for hashing the
        password and assigning the default role) rather than raw field
        arguments — the repository shouldn't need to know which fields
        exist on `User` to do its job of "add this row and give it back
        with its generated id/timestamps."
        """
        self.db.add(user)
        self.db.flush()  # assigns `id`/server defaults without committing
        # the whole transaction yet — committing is the service layer's
        # decision (it may need to do more within the same transaction
        # in a future milestone, e.g. writing an audit log row).
        self.db.refresh(user)
        return user

    def get_by_email(self, email: str) -> User | None:
        """Returns the user with the given email, or None if not found.
        Comparison is exact (case-sensitive at the DB level); email
        normalization (e.g. lowercasing) is a service-layer decision,
        not this repository's concern."""
        stmt = select(User).where(User.email == email)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_username(self, username: str) -> User | None:
        """Returns the user with the given username, or None if not
        found."""
        stmt = select(User).where(User.username == username)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_id(self, user_id: uuid.UUID) -> User | None:
        """Returns the user with the given primary key, or None if not
        found."""
        return self.db.get(User, user_id)

    def update(self, user: User, **fields: Any) -> User:
        """
        Applies the given field updates to an already-loaded `User`
        instance and flushes them.

        Accepting `**fields` (rather than a whole replacement object)
        lets callers update exactly the fields they changed (e.g. just
        `last_login`) without needing to reconstruct an entire User —
        SQLAlchemy's unit-of-work will only emit an UPDATE for the
        columns that actually changed.
        """
        for field_name, value in fields.items():
            setattr(user, field_name, value)
        self.db.flush()
        self.db.refresh(user)
        return user

    def exists(self, *, email: str | None = None, username: str | None = None) -> bool:
        """
        Returns True if a user with the given email and/or username
        already exists.

        Used by `AuthService.register` to proactively reject duplicate
        registrations with a clear error before ever attempting an
        INSERT — the database's own unique constraints remain the final
        safety net against a race between two concurrent registrations,
        but checking here means the common case (an honest duplicate
        attempt) gets a clean, specific error instead of a generic
        integrity-error translation.

        Note on usage: `AuthService.register` calls this once per field
        (`exists(email=...)`, then `exists(username=...)`) rather than
        both at once, specifically so it can tell the caller *which*
        field collided ("email already registered" vs. "username
        already taken"). Passing both here still works and returns True
        if *either* matches, for callers that only need a yes/no answer.
        """
        if email is None and username is None:
            return False

        conditions = []
        if email is not None:
            conditions.append(User.email == email)
        if username is not None:
            conditions.append(User.username == username)

        stmt = select(User.id).where(or_(*conditions))
        return self.db.execute(stmt).first() is not None

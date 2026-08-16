#!/usr/bin/env python3
"""Create or upgrade a local admin user without exposing admin registration in the public UI.

This is intentionally a development bootstrap tool rather than a public API. It creates
an `ADMIN` user with a known password and optionally upgrades an existing account to the
admin role if that email already exists.
"""

from __future__ import annotations

import argparse

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.user import User, UserRole


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a local CommerceOS admin account.")
    parser.add_argument("--email", required=True, help="Admin email address.")
    parser.add_argument("--password", required=True, help="Password for the admin account.")
    parser.add_argument("--username", help="Optional username; defaults to the email local-part.")
    parser.add_argument("--first-name", default="Admin", help="First name for the admin account.")
    parser.add_argument("--last-name", default="User", help="Last name for the admin account.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    email = args.email.strip()
    username = (args.username or email.split("@", 1)[0]).strip()

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email).one_or_none()

        if existing is not None:
            existing.role = UserRole.ADMIN
            existing.is_active = True
            existing.is_verified = True
            if not existing.username:
                existing.username = username
            db.commit()
            print(f"Admin account ready: {email} (role={existing.role.value})")
            return 0

        user = User(
            email=email,
            username=username,
            hashed_password=hash_password(args.password),
            first_name=args.first_name,
            last_name=args.last_name,
            role=UserRole.ADMIN,
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        db.commit()
        print(f"Created admin user: {email} (role=admin)")
        return 0
    except Exception as exc:  # pragma: no cover - CLI bootstrap safety net.
        db.rollback()
        print(f"Failed to create admin user: {exc}")
        return 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())

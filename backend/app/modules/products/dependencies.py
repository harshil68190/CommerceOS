"""
modules/products/dependencies.py

Responsibility
--------------
Authorization for catalog-management endpoints, built entirely on top of
the existing `modules/auth/dependencies` — this module does not decode
tokens, does not touch `User`/DB access for authentication, and does not
add a new role to `UserRole`.

Important note on role naming (flagging this deliberately rather than
quietly working around it): this milestone's spec calls for "ADMIN and
MANAGER" to manage the catalog. The current `UserRole` enum (from
Milestone 3, which this milestone must not modify) only defines `ADMIN`,
`SELLER`, and `CUSTOMER` — there is no `MANAGER` role. Rather than adding
one (which would mean modifying `models/user.py` and the auth module,
explicitly out of scope here), catalog-management access is granted to
`ADMIN` and `SELLER` — `SELLER` being the closest existing equivalent to
someone who manages product listings. If/when a dedicated `MANAGER` role
is introduced in a future auth milestone, only the tuple passed to
`_require_role` below needs to change.
"""

from fastapi import Depends

from app.models.user import User, UserRole
from app.modules.auth.dependencies import _require_role, get_current_active_user


def require_catalog_manager(user: User = Depends(get_current_active_user)) -> User:
    """Dependency for endpoints that create/update/delete/archive
    products or adjust stock. See the module docstring above for why
    this checks `ADMIN`/`SELLER` rather than a `MANAGER` role."""
    return _require_role(user, UserRole.ADMIN, UserRole.SELLER)

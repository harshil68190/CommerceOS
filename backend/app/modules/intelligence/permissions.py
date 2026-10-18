"""
modules/intelligence/permissions.py

Responsibility
--------------
Authorization for intelligence endpoints. Everything here is ADMIN only:
the module exposes cross-warehouse demand and purchasing guidance, which
is a system-administration concern. Follows the same `_require_role`
pattern as the inventory and orders modules.
"""

from fastapi import Depends

from app.models.user import User, UserRole
from app.modules.auth.dependencies import _require_role, get_current_active_user


def require_intelligence_admin(user: User = Depends(get_current_active_user)) -> User:
    """Dependency for all /intelligence endpoints. ADMIN only."""
    return _require_role(user, UserRole.ADMIN)

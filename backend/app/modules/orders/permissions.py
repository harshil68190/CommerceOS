"""
modules/orders/permissions.py

Responsibility
--------------
Authorization dependencies for order endpoints, built on top of
`modules/auth/dependencies`.

Four access levels:
1. ADMIN only: delete orders, refund orders.
2. ADMIN + CUSTOMER: create orders.
3. ADMIN + SELLER: view orders, update shipping.
4. ADMIN + CUSTOMER: view own orders.

This follows the same pattern as `modules/inventory/permissions.py`.
"""

from fastapi import Depends

from app.models.user import User, UserRole
from app.modules.auth.dependencies import _require_role, get_current_active_user


def require_order_admin(user: User = Depends(get_current_active_user)) -> User:
    """Dependency for order admin operations (delete, refund).
    Restricted to ADMIN only."""
    return _require_role(user, UserRole.ADMIN)


def require_order_creator(user: User = Depends(get_current_active_user)) -> User:
    """Dependency for creating orders. Accessible to ADMIN and CUSTOMER."""
    return _require_role(user, UserRole.ADMIN, UserRole.CUSTOMER)


def require_order_read(user: User = Depends(get_current_active_user)) -> User:
    """Dependency for read-only order operations (view orders).
    Accessible to ADMIN and SELLER."""
    return _require_role(user, UserRole.ADMIN, UserRole.SELLER)


def require_order_shipping(user: User = Depends(get_current_active_user)) -> User:
    """Dependency for updating shipping status (process, ship, deliver).
    Accessible to ADMIN and SELLER."""
    return _require_role(user, UserRole.ADMIN, UserRole.SELLER)


def require_order_cancel(user: User = Depends(get_current_active_user)) -> User:
    """Dependency for cancelling orders. Accessible to ADMIN and CUSTOMER."""
    return _require_role(user, UserRole.ADMIN, UserRole.CUSTOMER)


def require_order_return(user: User = Depends(get_current_active_user)) -> User:
    """Dependency for processing returns. Accessible to ADMIN and SELLER."""
    return _require_role(user, UserRole.ADMIN, UserRole.SELLER)

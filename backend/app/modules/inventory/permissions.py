"""
modules/inventory/permissions.py

Responsibility
--------------
Authorization dependencies for inventory endpoints, built on top of
`modules/auth/dependencies`.

Three access levels:
1. ADMIN only: warehouse CRUD (create/update/deactivate warehouses).
2. ADMIN + INVENTORY_MANAGER: stock mutation (add, remove, adjust,
   reserve, release, transfer, bulk import).
3. ADMIN + INVENTORY_MANAGER + CUSTOMER: read-only (list inventory,
   view transactions, low stock reports).

This follows the same pattern as `modules/products/dependencies.py`.
"""

from fastapi import Depends

from app.models.user import User, UserRole
from app.modules.auth.dependencies import _require_role, get_current_active_user


def require_warehouse_admin(user: User = Depends(get_current_active_user)) -> User:
    """Dependency for warehouse management endpoints (CRUD, deactivate).
    Restricted to ADMIN only — warehouse configuration is a
    system-administration concern."""
    return _require_role(user, UserRole.ADMIN)


def require_inventory_manager(user: User = Depends(get_current_active_user)) -> User:
    """Dependency for stock mutation endpoints (add, remove, adjust,
    reserve, release, transfer, bulk import).

    Accessible to ADMIN and INVENTORY_MANAGER — inventory management is
    a day-to-day operational role, distinct from system administration."""
    return _require_role(user, UserRole.ADMIN, UserRole.INVENTORY_MANAGER)


def require_inventory_read(user: User = Depends(get_current_active_user)) -> User:
    """Dependency for read-only inventory endpoints (list inventory,
    view transactions, low stock reports).

    Accessible to ADMIN, INVENTORY_MANAGER, and CUSTOMER — customers can
    view stock availability for products."""
    return _require_role(
        user, UserRole.ADMIN, UserRole.INVENTORY_MANAGER, UserRole.CUSTOMER
    )


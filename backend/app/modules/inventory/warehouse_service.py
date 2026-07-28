"""
modules/inventory/warehouse_service.py

Responsibility
--------------
Business logic for Warehouse CRUD operations. Handles:
- Uniqueness of warehouse code.
- Soft-delete (is_active = False) instead of physical delete.
- Blocking deactivation when inventory still exists in the warehouse.
- Search and pagination.

Warehouse management is admin-only (see permissions.py).
"""

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.modules.inventory.exceptions import (
    DuplicateWarehouseCodeError,
    WarehouseHasInventoryError,
)
from app.modules.inventory.models import Warehouse
from app.modules.inventory.repository import (
    InventoryRepository,
    WarehouseFilters,
    WarehouseRepository,
)
from app.modules.inventory.schemas import WarehouseCreateRequest, WarehouseUpdateRequest


class WarehouseService:
    """Business logic for managing warehouses."""

    def __init__(
        self,
        db: Session,
        warehouse_repo: WarehouseRepository,
        inventory_repo: InventoryRepository,
    ) -> None:
        self.db = db
        self.warehouse_repo = warehouse_repo
        self.inventory_repo = inventory_repo

    # --- Create ---------------------------------------------------

    def create_warehouse(self, payload: WarehouseCreateRequest) -> Warehouse:
        """
        Creates a new warehouse.

        Validates that:
        - The warehouse code is unique (case-insensitive).
        """
        if self.warehouse_repo.exists_code(payload.code):
            raise DuplicateWarehouseCodeError(
                f"A warehouse with code '{payload.code}' already exists."
            )

        warehouse = Warehouse(
            name=payload.name,
            code=payload.code,
            address=payload.address,
            city=payload.city,
            state=payload.state,
            country=payload.country,
            postal_code=payload.postal_code,
            contact_number=payload.contact_number,
            email=payload.email,
            is_active=True,
        )

        created = self.warehouse_repo.create(warehouse)
        self.db.commit()
        return created

    # --- Update ---------------------------------------------------

    def update_warehouse(
        self, warehouse_id: uuid.UUID, payload: WarehouseUpdateRequest
    ) -> Warehouse:
        """
        Updates an existing warehouse. Partial update — only supplied
        fields are changed.

        Validates that:
        - The warehouse exists.
        - If changing code, the new code is unique.
        """
        warehouse = self._get_warehouse_or_404(warehouse_id)

        updates = payload.model_dump(exclude_unset=True)

        # If code is changing, check uniqueness.
        if "code" in updates and updates["code"] != warehouse.code:
            if self.warehouse_repo.exists_code(
                updates["code"], exclude_id=warehouse.id
            ):
                raise DuplicateWarehouseCodeError(
                    f"A warehouse with code '{updates['code']}' already exists."
                )

        updated = self.warehouse_repo.update(warehouse, **updates)
        self.db.commit()
        return updated

    # --- Deactivate (soft-delete) ---------------------------------------------------

    def deactivate_warehouse(self, warehouse_id: uuid.UUID) -> Warehouse:
        """
        Deactivates a warehouse (soft-delete: sets is_active = False).

        Validates:
        - The warehouse exists and is currently active.
        - The warehouse has no inventory items (block deactivation
          if stock exists).
        """
        warehouse = self._get_warehouse_or_404(warehouse_id)

        if not warehouse.is_active:
            raise ConflictError("This warehouse is already deactivated.")

        # Check for existing inventory.
        inventory_count = self.inventory_repo.count_by_warehouse(warehouse_id)
        if inventory_count > 0:
            raise WarehouseHasInventoryError(
                f"Cannot deactivate warehouse '{warehouse.code}': "
                f"it contains {inventory_count} product(s) with inventory. "
                f"Transfer or remove all stock before deactivating."
            )

        updated = self.warehouse_repo.soft_delete(warehouse)
        self.db.commit()
        return updated

    # --- Reactivate ---------------------------------------------------

    def reactivate_warehouse(self, warehouse_id: uuid.UUID) -> Warehouse:
        """Reactivates a previously deactivated warehouse."""
        warehouse = self._get_warehouse_or_404(warehouse_id)

        if warehouse.is_active:
            raise ConflictError("This warehouse is already active.")

        updated = self.warehouse_repo.update(warehouse, is_active=True)
        self.db.commit()
        return updated

    # --- Read ---------------------------------------------------

    def get_warehouse_by_id(self, warehouse_id: uuid.UUID) -> Warehouse:
        """Returns a warehouse by ID, or raises NotFoundError."""
        return self._get_warehouse_or_404(warehouse_id)

    def list_warehouses(
        self, *, filters: WarehouseFilters, page: int, page_size: int
    ) -> tuple[list[Warehouse], int]:
        """Returns paginated, filtered warehouse list."""
        return self.warehouse_repo.list_paginated(
            filters=filters, page=page, page_size=page_size
        )

    # --- Internal helpers ---------------------------------------------------

    def _get_warehouse_or_404(self, warehouse_id: uuid.UUID) -> Warehouse:
        """Returns a warehouse or raises NotFoundError."""
        warehouse = self.warehouse_repo.get_by_id(warehouse_id)
        if warehouse is None:
            raise NotFoundError(
                f"No warehouse found with id '{warehouse_id}'."
            )
        return warehouse


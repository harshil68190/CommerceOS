"""
modules/inventory/repository.py

Responsibility
--------------
Three repository classes — WarehouseRepository, InventoryRepository,
TransactionRepository — following the exact same patterns as
UserRepository (auth module) and ProductRepository (products module).

Key architectural guarantees:
- Inventory rows are ALWAYS locked with SELECT ... FOR UPDATE when
  being modified, preventing concurrency races (overselling).
- TransactionRepository is append-only: it creates records but never
  updates or deletes them (immutable audit trail).
- Repositories are pure data-access: no business rules, no HTTP concepts.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.orm import Session, joinedload

from app.models.product import Product
from app.modules.inventory.constants import InventoryTransactionType, StockStatus
from app.modules.inventory.exceptions import ConcurrencyConflictError
from app.modules.inventory.models import Inventory, InventoryTransaction, Warehouse


# =========================================================================
# Filter Dataclasses
# =========================================================================


@dataclass
class WarehouseFilters:
    """Structured filter parameters for warehouse listing/search."""

    query: str | None = None  # free-text: name, code, city
    is_active: bool | None = None
    city: str | None = None
    country: str | None = None
    sort: str | None = None


@dataclass
class InventoryFilters:
    """Structured filter parameters for inventory listing."""

    product_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID | None = None
    warehouse_city: str | None = None
    stock_status: StockStatus | None = None
    reorder_level_min: int | None = None
    reorder_level_max: int | None = None
    query: str | None = None  # free-text: product name, SKU
    sort: str | None = None


@dataclass
class TransactionFilters:
    """Structured filter parameters for transaction history."""

    product_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID | None = None
    transaction_type: InventoryTransactionType | None = None
    created_by: uuid.UUID | None = None
    reference_number: str | None = None
    correlation_id: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    sort: str | None = None


# Sort option maps
_WAREHOUSE_SORT_OPTIONS: dict[str, tuple[Any, bool]] = {
    "name_asc": (Warehouse.name, False),
    "name_desc": (Warehouse.name, True),
    "code_asc": (Warehouse.code, False),
    "code_desc": (Warehouse.code, True),
    "city_asc": (Warehouse.city, False),
    "city_desc": (Warehouse.city, True),
    "newest": (Warehouse.created_at, True),
    "oldest": (Warehouse.created_at, False),
}
_WAREHOUSE_DEFAULT_SORT = "name_asc"

_INVENTORY_SORT_OPTIONS: dict[str, tuple[Any, bool]] = {
    "quantity_asc": (Inventory.quantity, False),
    "quantity_desc": (Inventory.quantity, True),
    "available_asc": ("available", False),  # handled specially
    "available_desc": ("available", True),
    "newest": (Inventory.created_at, True),
    "oldest": (Inventory.created_at, False),
}
_INVENTORY_DEFAULT_SORT = "quantity_desc"

_TRANSACTION_SORT_OPTIONS: dict[str, tuple[Any, bool]] = {
    "newest": (InventoryTransaction.created_at, True),
    "oldest": (InventoryTransaction.created_at, False),
}
_TRANSACTION_DEFAULT_SORT = "newest"


# =========================================================================
# WarehouseRepository
# =========================================================================


class WarehouseRepository:
    """Data-access layer for Warehouse records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Writes ---------------------------------------------------

    def create(self, warehouse: Warehouse) -> Warehouse:
        """Persists a new Warehouse and returns it with generated
        id/server defaults populated."""
        self.db.add(warehouse)
        self.db.flush()
        self.db.refresh(warehouse)
        return warehouse

    def update(self, warehouse: Warehouse, **fields: Any) -> Warehouse:
        """Applies field updates to an already-loaded Warehouse and
        flushes. Increments version for optimistic concurrency."""
        if "version" in fields:
            fields.pop("version")  # never manually set version
        fields["version"] = warehouse.version + 1

        for field_name, value in fields.items():
            setattr(warehouse, field_name, value)
        self.db.flush()
        self.db.refresh(warehouse)
        return warehouse

    def soft_delete(self, warehouse: Warehouse) -> Warehouse:
        """Soft-deletes a warehouse by setting is_active = False.
        This is the only allowed "delete" operation — physical deletes
        are not permitted."""
        return self.update(warehouse, is_active=False)

    # --- Single-row reads ---------------------------------------------------

    def get_by_id(self, warehouse_id: uuid.UUID) -> Warehouse | None:
        return self.db.get(Warehouse, warehouse_id)

    def get_by_code(self, code: str) -> Warehouse | None:
        stmt = select(Warehouse).where(Warehouse.code == code)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_active_by_id(self, warehouse_id: uuid.UUID) -> Warehouse | None:
        """Returns a warehouse only if it's active. Used by stock
        movement operations that must reject inactive warehouses."""
        stmt = select(Warehouse).where(
            Warehouse.id == warehouse_id,
            Warehouse.is_active.is_(True),
        )
        return self.db.execute(stmt).scalar_one_or_none()

    # --- Uniqueness checks ---------------------------------------------------

    def exists_code(self, code: str, *, exclude_id: uuid.UUID | None = None) -> bool:
        """Returns True if another warehouse already uses this code."""
        stmt = select(Warehouse.id).where(Warehouse.code == code)
        if exclude_id is not None:
            stmt = stmt.where(Warehouse.id != exclude_id)
        return self.db.execute(stmt).first() is not None

    # --- Filtering / pagination ---------------------------------------------------

    def _build_filtered_statement(self, filters: WarehouseFilters) -> Select:
        """Shared WHERE-clause construction for listing/search."""
        stmt = select(Warehouse)

        if filters.is_active is not None:
            stmt = stmt.where(Warehouse.is_active == filters.is_active)
        if filters.city is not None:
            stmt = stmt.where(Warehouse.city == filters.city)
        if filters.country is not None:
            stmt = stmt.where(Warehouse.country == filters.country)

        if filters.query:
            term = f"%{filters.query.lower()}%"
            stmt = stmt.where(
                or_(
                    func.lower(Warehouse.name).like(term),
                    func.lower(Warehouse.code).like(term),
                    func.lower(func.coalesce(Warehouse.city, "")).like(term),
                )
            )

        sort_key = (
            filters.sort
            if filters.sort in _WAREHOUSE_SORT_OPTIONS
            else _WAREHOUSE_DEFAULT_SORT
        )
        column, descending = _WAREHOUSE_SORT_OPTIONS[sort_key]
        stmt = stmt.order_by(column.desc() if descending else column.asc())

        return stmt

    def list_paginated(
        self, *, filters: WarehouseFilters, page: int, page_size: int
    ) -> tuple[list[Warehouse], int]:
        """Returns (items, total_count) for warehouse listing."""
        return self._paginate(filters, page=page, page_size=page_size)

    def _paginate(
        self, filters: WarehouseFilters, *, page: int, page_size: int
    ) -> tuple[list[Warehouse], int]:
        base_stmt = self._build_filtered_statement(filters)

        count_stmt = select(func.count()).select_from(
            base_stmt.order_by(None).subquery()
        )
        total = self.db.execute(count_stmt).scalar_one()

        offset = (page - 1) * page_size
        page_stmt = base_stmt.offset(offset).limit(page_size)
        items = list(self.db.execute(page_stmt).scalars().all())

        return items, total


# =========================================================================
# InventoryRepository
# =========================================================================


class InventoryRepository:
    """Data-access layer for Inventory records — the single source
    of truth for stock."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Writes ---------------------------------------------------

    def create(self, inventory: Inventory) -> Inventory:
        """Creates a new Inventory record."""
        self.db.add(inventory)
        self.db.flush()
        self.db.refresh(inventory)
        return inventory

    def update(self, inventory: Inventory, **fields):
        if "version" in fields:
            fields.pop("version")

        expected_version = inventory.version
        if not self.update_with_version_check(inventory.id, expected_version, **fields):
            raise ConcurrencyConflictError(
                f"Inventory {inventory.id} was modified by another request."
            )
        self.db.refresh(inventory)
        return inventory

    def update_with_version_check(
        self, inventory_id: uuid.UUID, expected_version: int, **fields: Any
    ) -> bool:
        """
        Optimistic concurrency-safe update. Only succeeds if the
        current version matches `expected_version`. Returns True if
        the update was applied, False if the version changed (caller
        should retry).

        This uses a single UPDATE ... WHERE ... version = expected_version
        statement, which is atomic — no race between read and write.
        """
        if "version" in fields:
            fields.pop("version")
        fields["version"] = Inventory.version + 1
        fields["last_stock_update"] = datetime.utcnow()

        stmt = (
            update(Inventory)
            .where(Inventory.id == inventory_id)
            .where(Inventory.version == expected_version)
            .values(**fields)
        )
        result = self.db.execute(stmt)
        self.db.flush()
        return result.rowcount > 0

    def upsert(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID, **fields: Any
    ) -> Inventory:
        """
        Creates or updates an inventory record for the given
        product-warehouse pair. Used by bulk import operations.

        Returns the created or updated Inventory record.
        """
        existing = self.get_by_product_and_warehouse(product_id, warehouse_id)
        if existing is not None:
            return self.update(existing, **fields)
        else:
            inventory = Inventory(
                product_id=product_id,
                warehouse_id=warehouse_id,
                quantity=fields.get("quantity", 0),
                reserved_quantity=fields.get("reserved_quantity", 0),
                reorder_level=fields.get("reorder_level", 0),
                max_stock=fields.get("max_stock", 0),
            )
            return self.create(inventory)

    # --- Single-row reads ---------------------------------------------------

    def get_by_id(self, inventory_id: uuid.UUID) -> Inventory | None:
        return self.db.get(Inventory, inventory_id)

    def get_by_product_and_warehouse(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID
    ) -> Inventory | None:
        """Returns the inventory record for a specific product in a
        specific warehouse, or None."""
        stmt = select(Inventory).where(
            Inventory.product_id == product_id,
            Inventory.warehouse_id == warehouse_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def get_for_update(
        self, product_id: uuid.UUID, warehouse_id: uuid.UUID
    ) -> Inventory | None:
        """
        Returns the inventory record for a specific product-warehouse
        pair, locked FOR UPDATE for concurrency safety.

        This is the ONLY way inventory should be read before a
        modification — it prevents two concurrent requests from
        overselling.
        """
        stmt = (
            select(Inventory)
            .where(
                Inventory.product_id == product_id,
                Inventory.warehouse_id == warehouse_id,
            )
            .with_for_update()
        )
        return self.db.execute(stmt).scalar_one_or_none()

    # --- List / filter ---------------------------------------------------

    def list_by_product(self, product_id: uuid.UUID) -> list[Inventory]:
        """Lists all inventory records for a given product across all
        warehouses."""
        stmt = select(Inventory).where(Inventory.product_id == product_id)
        return list(self.db.execute(stmt).scalars().all())

    def list_by_warehouse(self, warehouse_id: uuid.UUID) -> list[Inventory]:
        """Lists all inventory records in a given warehouse."""
        stmt = select(Inventory).where(Inventory.warehouse_id == warehouse_id)
        return list(self.db.execute(stmt).scalars().all())

    def count_by_warehouse(self, warehouse_id: uuid.UUID) -> int:
        """Returns the number of distinct products stored in a warehouse."""
        stmt = (
            select(func.count())
            .select_from(Inventory)
            .where(Inventory.warehouse_id == warehouse_id)
        )
        return self.db.execute(stmt).scalar_one()

    def _build_filtered_statement(self, filters: InventoryFilters) -> Select:
        """Shared WHERE-clause construction for inventory listing."""
        stmt = (
            select(Inventory)
            .options(joinedload(Inventory.product))
            .options(joinedload(Inventory.warehouse))
        )

        if filters.product_id is not None:
            stmt = stmt.where(Inventory.product_id == filters.product_id)
        if filters.warehouse_id is not None:
            stmt = stmt.where(Inventory.warehouse_id == filters.warehouse_id)
        if filters.warehouse_city is not None:
            stmt = stmt.join(Warehouse).where(Warehouse.city == filters.warehouse_city)

        # Stock status is a computed property, so we filter by the
        # underlying conditions instead.
        if filters.stock_status == StockStatus.OUT_OF_STOCK:
            stmt = stmt.where(
                Inventory.quantity - Inventory.reserved_quantity <= 0
            )
        elif filters.stock_status == StockStatus.LOW_STOCK:
            stmt = stmt.where(
                (Inventory.quantity - Inventory.reserved_quantity > 0)
                & (Inventory.quantity - Inventory.reserved_quantity <= Inventory.reorder_level)
            )
        elif filters.stock_status == StockStatus.IN_STOCK:
            stmt = stmt.where(
                Inventory.quantity - Inventory.reserved_quantity > Inventory.reorder_level
            )

        if filters.reorder_level_min is not None:
            stmt = stmt.where(Inventory.reorder_level >= filters.reorder_level_min)
        if filters.reorder_level_max is not None:
            stmt = stmt.where(Inventory.reorder_level <= filters.reorder_level_max)

        if filters.query:
            term = f"%{filters.query.lower()}%"
            stmt = stmt.join(Product, Inventory.product_id == Product.id).where(
                or_(
                    func.lower(Product.name).like(term),
                    func.lower(Product.sku).like(term),
                )
            )

        sort_key = (
            filters.sort
            if filters.sort in _INVENTORY_SORT_OPTIONS
            else _INVENTORY_DEFAULT_SORT
        )
        column, descending = _INVENTORY_SORT_OPTIONS[sort_key]
        if column == "available":
            # Sort by computed available quantity
            available_expr = Inventory.quantity - Inventory.reserved_quantity
            stmt = stmt.order_by(
                available_expr.desc() if descending else available_expr.asc()
            )
        else:
            stmt = stmt.order_by(column.desc() if descending else column.asc())

        return stmt

    def list_paginated(
        self, *, filters: InventoryFilters, page: int, page_size: int
    ) -> tuple[list[Inventory], int]:
        """Returns (items, total_count) for inventory listing."""
        base_stmt = self._build_filtered_statement(filters)

        count_stmt = select(func.count()).select_from(
            base_stmt.order_by(None).subquery()
        )
        total = self.db.execute(count_stmt).scalar_one()

        offset = (page - 1) * page_size
        page_stmt = base_stmt.offset(offset).limit(page_size)
        items = list(self.db.execute(page_stmt).scalars().all())

        return items, total

    # --- Aggregate queries ---------------------------------------------------

    def get_total_stock_for_product(self, product_id: uuid.UUID) -> dict[str, int]:
        """
        Returns aggregated stock data for a product across all warehouses.

        Returns:
            {
                "total_stock": 100,
                "total_reserved": 20,
                "total_available": 80,
                "warehouse_count": 2
            }
        """
        rows = self.list_by_product(product_id)
        total_stock = sum(item.quantity for item in rows)
        total_reserved = sum(item.reserved_quantity for item in rows)
        return {
            "total_stock": total_stock,
            "total_reserved": total_reserved,
            "total_available": total_stock - total_reserved,
            "warehouse_count": len(rows),
        }

    def get_warehouse_breakdown(self, product_id: uuid.UUID) -> list[dict[str, Any]]:
        """
        Returns per-warehouse breakdown for a product, including
        warehouse name from the joined Warehouse record.
        """
        rows = self.list_by_product(product_id)
        result = []
        for item in rows:
            w = item.warehouse
            result.append(
                {
                    "warehouse_id": str(item.warehouse_id),
                    "warehouse_name": w.name if w else "Unknown",
                    "quantity": item.quantity,
                    "reserved": item.reserved_quantity,
                    "available": item.available_quantity,
                }
            )
        return result

    def get_low_stock_items(self) -> list[Inventory]:
        """
        Returns all inventory records where available quantity is at or
        below the reorder level — the "low stock" report.
        """
        stmt = (
            select(Inventory)
            .options(joinedload(Inventory.product))
            .options(joinedload(Inventory.warehouse))
            .where(
                Inventory.quantity - Inventory.reserved_quantity <= Inventory.reorder_level
            )
            .order_by(Inventory.quantity.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def get_out_of_stock_items(self) -> list[Inventory]:
        """Returns all inventory records with zero available quantity."""
        stmt = (
            select(Inventory)
            .options(joinedload(Inventory.product))
            .options(joinedload(Inventory.warehouse))
            .where(Inventory.quantity - Inventory.reserved_quantity <= 0)
            .order_by(Inventory.quantity.asc())
        )
        return list(self.db.execute(stmt).scalars().all())


# =========================================================================
# TransactionRepository
# =========================================================================


class TransactionRepository:
    """
    Append-only repository for InventoryTransaction records.

    Transactions are immutable once created — no update, no delete.
    This is the audit log for every inventory change.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Write (append only) ---------------------------------------------------

    def create(self, transaction: InventoryTransaction) -> InventoryTransaction:
        """Creates a new transaction record (append-only)."""
        self.db.add(transaction)
        self.db.flush()
        self.db.refresh(transaction)
        return transaction

    # --- Reads ---------------------------------------------------

    def get_by_id(self, transaction_id: uuid.UUID) -> InventoryTransaction | None:
        return self.db.get(InventoryTransaction, transaction_id)

    def get_by_correlation_id(
        self, correlation_id: str
    ) -> list[InventoryTransaction]:
        """Returns all transactions sharing a correlation ID (e.g. both
        sides of a warehouse transfer)."""
        stmt = (
            select(InventoryTransaction)
            .where(InventoryTransaction.correlation_id == correlation_id)
            .order_by(InventoryTransaction.created_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    # --- Filtering / pagination ---------------------------------------------------

    def _build_filtered_statement(self, filters: TransactionFilters) -> Select:
        stmt = select(InventoryTransaction)

        if filters.product_id is not None:
            stmt = stmt.where(
                InventoryTransaction.product_id == filters.product_id
            )
        if filters.warehouse_id is not None:
            stmt = stmt.where(
                InventoryTransaction.warehouse_id == filters.warehouse_id
            )
        if filters.transaction_type is not None:
            stmt = stmt.where(
                InventoryTransaction.transaction_type == filters.transaction_type
            )
        if filters.created_by is not None:
            stmt = stmt.where(
                InventoryTransaction.created_by == filters.created_by
            )
        if filters.reference_number is not None:
            stmt = stmt.where(
                InventoryTransaction.reference_number == filters.reference_number
            )
        if filters.correlation_id is not None:
            stmt = stmt.where(
                InventoryTransaction.correlation_id == filters.correlation_id
            )
        if filters.date_from is not None:
            stmt = stmt.where(
                InventoryTransaction.created_at >= filters.date_from
            )
        if filters.date_to is not None:
            stmt = stmt.where(
                InventoryTransaction.created_at <= filters.date_to
            )

        sort_key = (
            filters.sort
            if filters.sort in _TRANSACTION_SORT_OPTIONS
            else _TRANSACTION_DEFAULT_SORT
        )
        column, descending = _TRANSACTION_SORT_OPTIONS[sort_key]
        stmt = stmt.order_by(column.desc() if descending else column.asc())

        return stmt

    def list_paginated(
        self, *, filters: TransactionFilters, page: int, page_size: int
    ) -> tuple[list[InventoryTransaction], int]:
        """Returns (items, total_count) for transaction history."""
        base_stmt = self._build_filtered_statement(filters)

        count_stmt = select(func.count()).select_from(
            base_stmt.order_by(None).subquery()
        )
        total = self.db.execute(count_stmt).scalar_one()

        offset = (page - 1) * page_size
        page_stmt = base_stmt.offset(offset).limit(page_size)
        items = list(self.db.execute(page_stmt).scalars().all())

        return items, total

    def get_summary_for_product(
        self, product_id: uuid.UUID, limit: int = 50
    ) -> list[InventoryTransaction]:
        """Returns the most recent transactions for a product."""
        stmt = (
            select(InventoryTransaction)
            .where(InventoryTransaction.product_id == product_id)
            .order_by(InventoryTransaction.created_at.desc())
            .limit(limit)
        )
        return list(self.db.execute(stmt).scalars().all())


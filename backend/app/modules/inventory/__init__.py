"""
modules/inventory/ — the inventory management bounded context.

Follows the same internal layout as `modules/auth/` and `modules/products/`:
`router.py` (HTTP layer), `services/` (business logic), `repository.py`
(persistence), `schemas.py` (Pydantic DTOs), `constants.py` (enums),
`exceptions.py` (domain errors), `permissions.py` (RBAC), and
`dependencies.py` (FastAPI DI).

This module implements a production-grade inventory system with:
- Warehouse management (soft-delete, CRUD)
- Stock movement service (all inventory changes go through this)
- Reservation system (reserve, release, confirm)
- Warehouse-to-warehouse transfers (atomic, dual-transaction)
- Low-stock detection and reporting
- Bulk import/update
- Full audit trail via InventoryTransaction records
- Concurrency-safe operations (SELECT ... FOR UPDATE, optimistic locking)

Inventory is the SINGLE source of truth for all stock data. The Product
model no longer stores stock_quantity/reserved_quantity — it derives
total_stock and available_stock from this module.
"""

from app.modules.inventory.constants import InventoryTransactionType, StockStatus

__all__ = [
    "InventoryTransactionType",
    "StockStatus",
]


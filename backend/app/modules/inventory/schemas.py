"""
modules/inventory/schemas.py

Responsibility
--------------
Every request/response shape the inventory module's API exposes.
Follows the same conventions as `schemas/product.py` and
`schemas/auth.py`: Pydantic v2 models with `from_attributes=True`
for ORM-to-schema conversion, explicit field validation, and
comprehensive documentation for auto-generated OpenAPI/Swagger docs.

Inventory is the single source of truth for stock data. These schemas
expose inventory-level information (per warehouse) as well as aggregated
product-level stock views.
"""

import uuid
from datetime import datetime
from math import ceil
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.inventory.constants import (
    InventoryTransactionType,
    StockStatus,
)


# =========================================================================
# Warehouse Schemas
# =========================================================================


class WarehouseCreateRequest(BaseModel):
    """Request body for POST /inventory/warehouses (admin only)."""

    name: str = Field(min_length=1, max_length=255)
    code: str = Field(
        min_length=1,
        max_length=50,
        pattern=r"^[A-Z0-9]+(?:[-_][A-Z0-9]+)*$",
        description="Unique warehouse code (e.g. 'PHX-01', 'LA-DC'). "
        "Uppercase alphanumeric with hyphens/underscores.",
    )
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    contact_number: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)

    @field_validator("code")
    @classmethod
    def _code_must_be_uppercase(cls, value: str) -> str:
        return value.upper()

    @field_validator("email")
    @classmethod
    def _validate_email_format(cls, value: str | None) -> str | None:
        if value is not None and "@" not in value:
            raise ValueError("Invalid email format.")
        return value


class WarehouseUpdateRequest(BaseModel):
    """
    Request body for PUT /inventory/warehouses/{id} (admin only).

    Every field is optional — partial update; only supplied fields
    are changed.
    """

    name: str | None = Field(default=None, min_length=1, max_length=255)
    code: str | None = Field(
        default=None,
        min_length=1,
        max_length=50,
        pattern=r"^[A-Z0-9]+(?:[-_][A-Z0-9]+)*$",
    )
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    postal_code: str | None = Field(default=None, max_length=20)
    contact_number: str | None = Field(default=None, max_length=20)
    email: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None

    @field_validator("code")
    @classmethod
    def _code_must_be_uppercase(cls, value: str | None) -> str | None:
        return value.upper() if value is not None else None

    @field_validator("email")
    @classmethod
    def _validate_email_format(cls, value: str | None) -> str | None:
        if value is not None and "@" not in value:
            raise ValueError("Invalid email format.")
        return value


class WarehouseResponse(BaseModel):
    """Full public representation of a warehouse."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    address: str | None
    city: str | None
    state: str | None
    country: str | None
    postal_code: str | None
    contact_number: str | None
    email: str | None
    is_active: bool
    version: int
    created_at: datetime
    updated_at: datetime


class WarehouseListResponse(BaseModel):
    """Paginated envelope for warehouse listings."""

    items: list[WarehouseResponse]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def build(
        cls, *, items: list[WarehouseResponse], total: int, page: int, page_size: int
    ) -> "WarehouseListResponse":
        pages = ceil(total / page_size) if page_size > 0 else 0
        return cls(items=items, total=total, page=page, page_size=page_size, pages=pages)


# =========================================================================
# Inventory Schemas
# =========================================================================


class InventoryResponse(BaseModel):
    """Per-warehouse inventory record for a single product."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: int
    reserved_quantity: int
    available_quantity: int  # computed: quantity - reserved_quantity
    reorder_level: int
    max_stock: int
    version: int
    stock_status: StockStatus
    last_stock_update: datetime | None
    created_at: datetime
    updated_at: datetime


class InventoryListResponse(BaseModel):
    """Paginated envelope for inventory listings."""

    items: list[InventoryResponse]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def build(
        cls, *, items: list[InventoryResponse], total: int, page: int, page_size: int
    ) -> "InventoryListResponse":
        pages = ceil(total / page_size) if page_size > 0 else 0
        return cls(items=items, total=total, page=page, page_size=page_size, pages=pages)


# =========================================================================
# Stock Movement Request Schemas
# =========================================================================


class AddStockRequest(BaseModel):
    """Request body to add stock to a product in a warehouse."""

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: int = Field(gt=0, description="Number of units to add")
    reference_number: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=500)


class RemoveStockRequest(BaseModel):
    """Request body to remove stock from a product in a warehouse."""

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: int = Field(gt=0, description="Number of units to remove")
    reason: Literal["damage", "expired", "adjustment", "other"] = "adjustment"
    reference_number: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=500)


class AdjustStockRequest(BaseModel):
    """
    Request body to set the exact stock quantity for a product in a
    warehouse. This is a manual override (e.g., after a cycle count).

    The service layer calculates the difference and creates an
    ADJUSTMENT transaction recording the change.
    """

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    new_quantity: int = Field(ge=0, description="Target absolute stock quantity")
    reference_number: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=500)


class ReserveStockRequest(BaseModel):
    """Request body to reserve stock for a pending order."""

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: int = Field(gt=0, description="Number of units to reserve")
    reference_number: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=500)


class ReleaseStockRequest(BaseModel):
    """Request body to release previously reserved stock."""

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: int = Field(gt=0, description="Number of units to release")
    reference_number: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=500)


class ConfirmReservationRequest(BaseModel):
    """
    Request body to confirm a reservation and convert it into an actual
    stock deduction (SALE transaction). This is what happens when a
    pending order is confirmed/fulfilled.
    """

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: int = Field(gt=0, description="Number of reserved units to confirm")
    reference_number: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=500)


class TransferRequest(BaseModel):
    """
    Request body to transfer stock between warehouses.

    Creates two transactions: TRANSFER_OUT from source warehouse and
    TRANSFER_IN to destination warehouse, with the same correlation_id.
    """

    product_id: uuid.UUID
    from_warehouse_id: uuid.UUID
    to_warehouse_id: uuid.UUID
    quantity: int = Field(gt=0, description="Number of units to transfer")
    reference_number: str | None = Field(default=None, max_length=255)
    notes: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validate_different_warehouses(self) -> "TransferRequest":
        if self.from_warehouse_id == self.to_warehouse_id:
            raise ValueError("Source and destination warehouses must be different.")
        return self


# =========================================================================
# Transaction Schemas
# =========================================================================


class InventoryTransactionResponse(BaseModel):
    """An immutable audit record of an inventory change."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    transaction_type: InventoryTransactionType
    quantity: int
    previous_quantity: int
    new_quantity: int
    previous_reserved_quantity: int
    new_reserved_quantity: int
    reference_number: str | None
    correlation_id: str | None
    notes: str | None
    created_by: uuid.UUID
    created_at: datetime


class TransactionListResponse(BaseModel):
    """Paginated envelope for transaction history."""

    items: list[InventoryTransactionResponse]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def build(
        cls,
        *,
        items: list[InventoryTransactionResponse],
        total: int,
        page: int,
        page_size: int,
    ) -> "TransactionListResponse":
        pages = ceil(total / page_size) if page_size > 0 else 0
        return cls(items=items, total=total, page=page, page_size=page_size, pages=pages)


# =========================================================================
# Low Stock Report
# =========================================================================


class LowStockItem(BaseModel):
    """A single item in the low stock report."""

    product_id: uuid.UUID
    product_name: str
    product_sku: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    warehouse_code: str
    quantity: int
    reserved_quantity: int
    available_quantity: int
    reorder_level: int
    stock_status: StockStatus


class LowStockReportResponse(BaseModel):
    """Low stock report across all warehouses."""

    items: list[LowStockItem]
    total: int


# =========================================================================
# Stock Movement Response
# =========================================================================


class StockMovementResponse(BaseModel):
    """
    Response returned by stock mutation endpoints.

    Contains both the updated inventory record and the transaction
    record that was created for audit.
    """

    inventory: InventoryResponse
    transaction: InventoryTransactionResponse


# =========================================================================
# Bulk Import
# =========================================================================


class BulkInventoryItem(BaseModel):
    """A single item in a bulk inventory update request."""

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: int = Field(ge=0)
    reserved_quantity: int = Field(default=0, ge=0)
    reorder_level: int = Field(default=0, ge=0)
    max_stock: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def _validate_reserved_within_quantity(self) -> "BulkInventoryItem":
        if self.reserved_quantity > self.quantity:
            raise ValueError(
                f"Reserved quantity ({self.reserved_quantity}) cannot exceed "
                f"quantity ({self.quantity})."
            )
        return self


class BulkImportRequest(BaseModel):
    """Request body for bulk inventory import/update."""

    items: list[BulkInventoryItem] = Field(
        min_length=1,
        max_length=500,
        description="List of inventory items to create or update. "
        "Max 500 items per batch.",
    )


class BulkImportResponse(BaseModel):
    """Response for a bulk import operation."""

    success: bool
    processed_count: int
    errors: list[dict[str, Any]] = Field(default_factory=list)


# =========================================================================
# Product Stock Summary (aggregated across warehouses)
# =========================================================================


class ProductStockSummary(BaseModel):
    """
    Aggregated stock information for a product across all warehouses.
    Used by the Product module to provide stock visibility without
    coupling Product directly to Inventory.
    """

    product_id: uuid.UUID
    total_stock: int
    total_reserved: int
    total_available: int
    warehouse_count: int
    warehouses: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Per-warehouse breakdown: [{warehouse_id, warehouse_name, quantity, reserved, available}]",
    )


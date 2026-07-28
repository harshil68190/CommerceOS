"""
modules/inventory/models.py

Responsibility
--------------
Defines the three ORM models for the inventory subsystem — Warehouse,
Inventory, and InventoryTransaction — following the same conventions as
`models/user.py` and `models/product.py`.

Key architectural rules enforced here:
1. Inventory is the SINGLE source of truth for stock. The Product model
   does NOT store stock_quantity or reserved_quantity (those columns
   were removed in this module's migration).
2. Inventory quantity is NEVER modified directly. Every change goes
   through an InventoryTransaction (see StockMovementService).
3. `available_quantity` is a computed property (quantity - reserved_quantity)
   — never stored, never drifting out of sync.
4. Optimistic concurrency control via a `version` field on Inventory.
5. Soft-delete for Warehouses via `is_active` — no physical deletes.

Relationship rules:
- Warehouse ↔ Inventory: one-to-many (a warehouse holds many product inventories).
- Product ↔ Inventory: one-to-many (a product can be in many warehouses).
- InventoryTransaction references both Product and Warehouse.
"""

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.modules.inventory.constants import (
    InventoryTransactionType,
    StockStatus,
)
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.product import Product

class Warehouse(Base):
    """
    A physical or virtual location where inventory is stored.

    Soft-delete: never physically deleted. Setting `is_active = False`
    prevents the warehouse from appearing in select lists and blocks
    stock operations against it. Deactivation is blocked if the
    warehouse still has inventory (see WarehouseService).

    The `code` field is a human-readable, unique identifier (e.g.
    "PHX-01", "LA-DC") used in external systems and reporting —
    it is NOT the primary key, but it IS unique and indexed.
    """

    __tablename__ = "warehouses"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    code: Mapped[str] = mapped_column(
        String(50), unique=True, index=True, nullable=False
    )

    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    state: Mapped[str | None] = mapped_column(String(100), nullable=True)
    country: Mapped[str | None] = mapped_column(String(100), nullable=True)
    postal_code: Mapped[str | None] = mapped_column(String(20), nullable=True)

    contact_number: Mapped[str | None] = mapped_column(String(20), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_active: Mapped[bool] = mapped_column(default=True, nullable=False, index=True)

    # Optimistic concurrency for warehouse updates.
    version: Mapped[int] = mapped_column(default=1, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # --- Relationships (used by repositories, not serialized directly) ---
    inventory_items: Mapped[list["Inventory"]] = relationship(
        "Inventory", back_populates="warehouse", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Warehouse id={self.id} code={self.code} active={self.is_active}>"


class Inventory(Base):
    """
    The single source of truth for how much of a product is in a
    particular warehouse.

    This table is the JOIN between Product and Warehouse: one Inventory
    row per product-warehouse pair (enforced by the unique constraint
    on (product_id, warehouse_id)).

    quantity        = physical stock on hand (increased/decreased by
                      transactions). Never reduced by reservations.
    reserved_quantity = stock earmarked for pending orders. Only reduced
                      when a reservation is released or confirmed.
    available_quantity = quantity - reserved_quantity (computed property).
    reorder_level   = when available_quantity drops to or below this
                      value, the item is considered LOW_STOCK.
    max_stock       = maximum desired stock level (for overstock alerts).
    version         = optimistic concurrency lock. Read the current
                      version, apply a change, and only the write that
                      matches the current version succeeds.
    """

    __tablename__ = "inventory"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="quantity_non_negative"),
        CheckConstraint("reserved_quantity >= 0", name="reserved_non_negative"),
        CheckConstraint(
            "reserved_quantity <= quantity",
            name="reserved_within_quantity",
        ),
        CheckConstraint("reorder_level >= 0", name="reorder_level_non_negative"),
        CheckConstraint("max_stock >= 0", name="max_stock_non_negative"),
        UniqueConstraint(
            "product_id", "warehouse_id",
            name="uq_inventory_product_warehouse",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", name="fk_inventory_product_id_products",
                    ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("warehouses.id", name="fk_inventory_warehouse_id_warehouses",
                    ondelete="RESTRICT"),
        index=True,
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(default=0, nullable=False)
    reserved_quantity: Mapped[int] = mapped_column(default=0, nullable=False)
    reorder_level: Mapped[int] = mapped_column(default=0, nullable=False)
    max_stock: Mapped[int] = mapped_column(default=0, nullable=False)

    # Optimistic concurrency version — incremented on every write.
    version: Mapped[int] = mapped_column(default=1, nullable=False)

    last_stock_update: Mapped[datetime | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # --- Relationships ---------------------------------------------------
    product: Mapped["Product"] = relationship("Product")  # noqa: F821
    warehouse: Mapped["Warehouse"] = relationship(
        "Warehouse", back_populates="inventory_items"
    )

    # --- Computed properties ---------------------------------------------------

    @property
    def available_quantity(self) -> int:
        """Stock actually available to sell (physical stock minus
        already-reserved). Computed, never stored."""
        return self.quantity - self.reserved_quantity

    @property
    def stock_status(self) -> StockStatus:
        """
        Current stock health based on available quantity.
        """
        available = self.available_quantity

        if available <= 0:
            return StockStatus.OUT_OF_STOCK

        if available <= self.reorder_level:
            return StockStatus.LOW_STOCK

        return StockStatus.IN_STOCK
    
    def __repr__(self) -> str:
        return (
            f"<Inventory id={self.id} product={self.product_id} "
            f"warehouse={self.warehouse_id} qty={self.quantity} "
            f"reserved={self.reserved_quantity}>"
        )


class InventoryTransaction(Base):
    """
    Immutable audit record for every inventory quantity change.

    Every stock movement (add, remove, reserve, release, transfer,
    adjust) MUST create one of these records. Inventory quantities are
    NEVER modified without a corresponding transaction.

    Fields:
    - transaction_type: see InventoryTransactionType enum.
    - quantity: the signed change amount (positive for inbound,
      negative for outbound in spirit — but stored as an absolute
      value that the transaction_type context disambiguates).
    - previous_quantity: snapshot of the inventory's quantity BEFORE
      the change (for audit).
    - new_quantity: snapshot of the inventory's quantity AFTER the change.
    - previous_reserved_quantity: snapshot of reserved_quantity before.
    - new_reserved_quantity: snapshot of reserved_quantity after.
    - reference_number: external reference (e.g. PO number, order number).
    - correlation_id: groups related transactions (e.g. TRANSFER_OUT +
      TRANSFER_IN for the same warehouse transfer).
    - notes: free-text reason or context.
    - created_by: the user who performed the operation.
    """

    __tablename__ = "inventory_transactions"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="tx_quantity_non_negative"),
        CheckConstraint("previous_quantity >= 0", name="tx_prev_qty_non_negative"),
        CheckConstraint("new_quantity >= 0", name="tx_new_qty_non_negative"),
        CheckConstraint(
            "previous_reserved_quantity >= 0",
            name="tx_prev_reserved_non_negative",
        ),
        CheckConstraint(
            "new_reserved_quantity >= 0",
            name="tx_new_reserved_non_negative",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)

    product_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("products.id", name="fk_tx_product_id_products"),
        index=True,
        nullable=False,
    )
    warehouse_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("warehouses.id", name="fk_tx_warehouse_id_warehouses"),
        index=True,
        nullable=False,
    )

    transaction_type: Mapped[InventoryTransactionType] = mapped_column(
        SAEnum(
            InventoryTransactionType,
            name="inventory_transaction_type",
            native_enum=True,
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        index=True,
        nullable=False,
    )

    quantity: Mapped[int] = mapped_column(nullable=False)
    previous_quantity: Mapped[int] = mapped_column(nullable=False)
    new_quantity: Mapped[int] = mapped_column(nullable=False)
    previous_reserved_quantity: Mapped[int] = mapped_column(nullable=False)
    new_reserved_quantity: Mapped[int] = mapped_column(nullable=False)

    reference_number: Mapped[str | None] = mapped_column(
        String(255), index=True, nullable=True
    )
    correlation_id: Mapped[str | None] = mapped_column(
        String(64), index=True, nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_by: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", name="fk_tx_created_by_users"), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), index=True, nullable=False
    )

    # --- Relationships (informational, not required for writes) ---------
    # These are not eagerly loaded by default — transaction reads are
    # deliberately lightweight; product/warehouse details are joined
    # only when the API needs them (see schemas).
    product: Mapped["Product"] = relationship("Product")  # noqa: F821
    warehouse: Mapped["Warehouse"] = relationship("Warehouse")

    def __repr__(self) -> str:
        return (
            f"<InventoryTransaction id={self.id} type={self.transaction_type} "
            f"qty={self.quantity}>"
        )


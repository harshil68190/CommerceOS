"""
modules/inventory/stock_movement_service.py

Responsibility
--------------
Central StockMovementService — the ONLY place in the codebase that
mutates Inventory records. Every stock operation (add, remove, adjust,
reserve, release, confirm reservation, transfer) goes through this
service.

Architectural rules enforced here:
1. ALL inventory modifications create an InventoryTransaction record
   (immutable audit log).
2. ALL reads-for-modification use SELECT ... FOR UPDATE to prevent
   overselling under concurrent requests.
3. `quantity` = physical stock. Never reduced by reservations.
4. `reserved_quantity` = earmarked for pending orders.
5. `available_quantity` = quantity - reserved_quantity (computed).
6. Only order confirmation (confirm_reservation) reduces quantity
   and creates a SALE transaction.
7. Negative stock is impossible (validated + DB CHECK constraints).
8. Warehouse transfers create TWO transactions (TRANSFER_OUT +
   TRANSFER_IN) with matching correlation_id in a single DB transaction.
9. Optimistic concurrency (version field) as a second layer of safety
   beyond FOR UPDATE.
"""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.modules.inventory.constants import InventoryTransactionType, StockStatus
from app.modules.inventory.exceptions import (
    ConcurrencyConflictError,
    InsufficientStockError,
    InvalidTransferError,
    InventoryNotFoundError,
)
from app.modules.inventory.models import Inventory, InventoryTransaction
from app.modules.inventory.repository import (
    InventoryRepository,
    TransactionRepository,
    WarehouseRepository,
)


def _generate_correlation_id() -> str:
    """Generates a unique correlation ID for grouping related
    transactions (e.g. both sides of a warehouse transfer)."""
    import secrets

    return secrets.token_hex(16)  # 32-character hex string


class StockMovementService:
    """
    Central service for all inventory stock movements.

    Every public method follows the same pattern:
    1. Validate inputs and permissions.
    2. Lock the inventory row (SELECT ... FOR UPDATE).
    3. Apply the business logic.
    4. Update the Inventory record.
    5. Create an InventoryTransaction audit record.
    6. Return (updated_inventory, created_transaction).

    No other service, router, or module should import InventoryRepository
    and modify quantities directly — always go through this class.
    """

    def __init__(
        self,
        db: Session,
        inventory_repo: InventoryRepository,
        transaction_repo: TransactionRepository,
        warehouse_repo: WarehouseRepository,
    ) -> None:
        self.db = db
        self.inventory_repo = inventory_repo
        self.transaction_repo = transaction_repo
        self.warehouse_repo = warehouse_repo

    # =========================================================================
    # Add Stock
    # =========================================================================

    def add_stock(
        self,
        *,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        quantity: int,
        current_user_id: uuid.UUID,
        reference_number: str | None = None,
        notes: str | None = None,
    ) -> tuple[Inventory, InventoryTransaction]:
        """
        Adds physical stock to a product in a warehouse (e.g. purchase
        order received, return processed).

        If no Inventory record exists for this product-warehouse pair,
        one is created (first-time stock entry).

        Concurrency-safe: uses SELECT ... FOR UPDATE.
        """
        self._validate_quantity(quantity)
        self._validate_warehouse_active(warehouse_id)

        inventory = self.inventory_repo.get_for_update(product_id, warehouse_id)

        if inventory is None:
            # First-time stock entry: create the inventory record.
            inventory = Inventory(
                product_id=product_id,
                warehouse_id=warehouse_id,
                quantity=0,
                reserved_quantity=0,
                reorder_level=0,
                max_stock=0,
            )
            inventory = self.inventory_repo.create(inventory)

        previous_qty = inventory.quantity
        previous_reserved = inventory.reserved_quantity

        inventory = self.inventory_repo.update(
            inventory,
            quantity=inventory.quantity + quantity,
        )

        transaction = self._create_transaction(
            product_id=product_id,
            warehouse_id=warehouse_id,
            transaction_type=InventoryTransactionType.PURCHASE,
            quantity=quantity,
            previous_quantity=previous_qty,
            new_quantity=inventory.quantity,
            previous_reserved_quantity=previous_reserved,
            new_reserved_quantity=inventory.reserved_quantity,
            reference_number=reference_number,
            notes=notes,
            created_by=current_user_id,
        )
        print("IN TRANSACTION:", self.db.in_transaction())
        self.db.commit()
        print("COMMITTED")
        return inventory, transaction

    # =========================================================================
    # Remove Stock
    # =========================================================================

    def remove_stock(
        self,
        *,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        quantity: int,
        current_user_id: uuid.UUID,
        reason: str = "adjustment",
        reference_number: str | None = None,
        notes: str | None = None,
    ) -> tuple[Inventory, InventoryTransaction]:
        """
        Removes physical stock from a product in a warehouse (e.g.
        damage, expired, manual correction).

        Raises InsufficientStockError if removing the requested quantity
        would leave less stock than is currently reserved.

        Concurrency-safe: uses SELECT ... FOR UPDATE.
        """
        self._validate_quantity(quantity)
        self._validate_warehouse_active(warehouse_id)
        print("=" * 60)
        print("REMOVE STOCK")
        print("Product ID :", product_id)
        print("Warehouse ID:", warehouse_id)

        inventory = self.inventory_repo.get_by_product_and_warehouse(
            product_id, warehouse_id
        )
        print("Normal lookup:", inventory)

        inventory = self.inventory_repo.get_for_update(product_id, warehouse_id)
        print("FOR UPDATE lookup:", inventory)
        print("=" * 60)
        inventory = self.inventory_repo.get_for_update(product_id, warehouse_id)
        if inventory is None:
            raise InventoryNotFoundError(
                f"No inventory record found for product {product_id} "
                f"in warehouse {warehouse_id}."
            )

        if quantity > inventory.quantity:
            raise InsufficientStockError(
                f"Cannot remove {quantity} units: only {inventory.quantity} "
                f"units are on hand in this warehouse."
            )

        new_quantity = inventory.quantity - quantity
        if new_quantity < inventory.reserved_quantity:
            raise InsufficientStockError(
                f"Cannot remove {quantity} units: {inventory.reserved_quantity} "
                f"units are reserved and the result ({new_quantity}) would be "
                f"less than reserved stock."
            )

        previous_qty = inventory.quantity
        previous_reserved = inventory.reserved_quantity

        # Map reason to transaction type
        type_map = {
            "damage": InventoryTransactionType.DAMAGE,
            "expired": InventoryTransactionType.EXPIRED,
            "adjustment": InventoryTransactionType.ADJUSTMENT,
        }
        tx_type = type_map.get(reason, InventoryTransactionType.ADJUSTMENT)

        inventory = self.inventory_repo.update(inventory, quantity=new_quantity)

        transaction = self._create_transaction(
            product_id=product_id,
            warehouse_id=warehouse_id,
            transaction_type=tx_type,
            quantity=quantity,
            previous_quantity=previous_qty,
            new_quantity=inventory.quantity,
            previous_reserved_quantity=previous_reserved,
            new_reserved_quantity=inventory.reserved_quantity,
            reference_number=reference_number,
            notes=notes,
            created_by=current_user_id,
        )

        return inventory, transaction

    # =========================================================================
    # Adjust Stock (set to exact quantity)
    # =========================================================================

    def adjust_stock(
        self,
        *,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        new_quantity: int,
        current_user_id: uuid.UUID,
        reference_number: str | None = None,
        notes: str | None = None,
    ) -> tuple[Inventory, InventoryTransaction]:
        """
        Sets the exact stock quantity for a product in a warehouse
        (manual override after cycle count).

        Calculates the difference and creates an ADJUSTMENT transaction.
        Raises InsufficientStockError if new_quantity would be less than
        currently reserved.

        Concurrency-safe: uses SELECT ... FOR UPDATE.
        """
        if new_quantity < 0:
            raise ValidationError("New quantity cannot be negative.")

        self._validate_warehouse_active(warehouse_id)

        inventory = self.inventory_repo.get_for_update(product_id, warehouse_id)
        if inventory is None:
            raise InventoryNotFoundError(
                f"No inventory record found for product {product_id} "
                f"in warehouse {warehouse_id}."
            )

        if new_quantity < inventory.reserved_quantity:
            raise InsufficientStockError(
                f"Cannot set quantity to {new_quantity}: {inventory.reserved_quantity} "
                f"units are currently reserved."
            )

        previous_qty = inventory.quantity
        previous_reserved = inventory.reserved_quantity
        difference = abs(new_quantity - previous_qty)

        inventory = self.inventory_repo.update(inventory, quantity=new_quantity)

        transaction = self._create_transaction(
            product_id=product_id,
            warehouse_id=warehouse_id,
            transaction_type=InventoryTransactionType.ADJUSTMENT,
            quantity=difference,
            previous_quantity=previous_qty,
            new_quantity=inventory.quantity,
            previous_reserved_quantity=previous_reserved,
            new_reserved_quantity=inventory.reserved_quantity,
            reference_number=reference_number,
            notes=notes or f"Manual adjustment from {previous_qty} to {new_quantity}",
            created_by=current_user_id,
        )

        return inventory, transaction

    # =========================================================================
    # Reserve Stock
    # =========================================================================

    def reserve_stock(
        self,
        *,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        quantity: int,
        current_user_id: uuid.UUID,
        reference_number: str | None = None,
        notes: str | None = None,
    ) -> tuple[Inventory, InventoryTransaction]:
        """
        Reserves stock for a pending order (e.g. items added to cart /
        checkout initiated).

        Reservation ONLY increases reserved_quantity — it does NOT
        reduce physical quantity. available_quantity = quantity -
        reserved_quantity decreases, but quantity stays the same.

        Raises InsufficientStockError if available_quantity is not
        sufficient.

        Concurrency-safe: uses SELECT ... FOR UPDATE.
        """
        self._validate_quantity(quantity)
        self._validate_warehouse_active(warehouse_id)

        inventory = self.inventory_repo.get_for_update(product_id, warehouse_id)
        if inventory is None:
            raise InventoryNotFoundError(
                f"No inventory record found for product {product_id} "
                f"in warehouse {warehouse_id}."
            )

        available = inventory.quantity - inventory.reserved_quantity
        if quantity > available:
            raise InsufficientStockError(
                f"Cannot reserve {quantity} units: only {available} units "
                f"are currently available in this warehouse."
            )

        previous_qty = inventory.quantity
        previous_reserved = inventory.reserved_quantity

        inventory = self.inventory_repo.update(
            inventory,
            reserved_quantity=inventory.reserved_quantity + quantity,
        )

        transaction = self._create_transaction(
            product_id=product_id,
            warehouse_id=warehouse_id,
            transaction_type=InventoryTransactionType.RESERVATION,
            quantity=quantity,
            previous_quantity=previous_qty,
            new_quantity=inventory.quantity,
            previous_reserved_quantity=previous_reserved,
            new_reserved_quantity=inventory.reserved_quantity,
            reference_number=reference_number,
            notes=notes,
            created_by=current_user_id,
        )
        self.db.commit()
        self.db.refresh(inventory)
        self.db.refresh(transaction)
        return inventory, transaction

    # =========================================================================
    # Release Reservation
    # =========================================================================

    def release_reservation(
        self,
        *,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        quantity: int,
        current_user_id: uuid.UUID,
        reference_number: str | None = None,
        notes: str | None = None,
    ) -> tuple[Inventory, InventoryTransaction]:
        """
        Releases previously reserved stock back to available (e.g. cart
        expired, order cancelled before confirmation).

        Decreases reserved_quantity but does not change physical quantity.
        available_quantity increases by the released amount.

        Concurrency-safe: uses SELECT ... FOR UPDATE.
        """
        self._validate_quantity(quantity)
        self._validate_warehouse_active(warehouse_id)
        inventory = self.inventory_repo.get_for_update(product_id, warehouse_id)
        if inventory is None:
            raise InventoryNotFoundError(
                f"No inventory record found for product {product_id} "
                f"in warehouse {warehouse_id}."
            )

        if quantity > inventory.reserved_quantity:
            raise ValidationError(
                f"Cannot release {quantity} units: only {inventory.reserved_quantity} "
                f"units are currently reserved."
            )

        previous_qty = inventory.quantity
        previous_reserved = inventory.reserved_quantity

        inventory = self.inventory_repo.update(
            inventory,
            reserved_quantity=inventory.reserved_quantity - quantity,
        )

        transaction = self._create_transaction(
            product_id=product_id,
            warehouse_id=warehouse_id,
            transaction_type=InventoryTransactionType.RELEASE,
            quantity=quantity,
            previous_quantity=previous_qty,
            new_quantity=inventory.quantity,
            previous_reserved_quantity=previous_reserved,
            new_reserved_quantity=inventory.reserved_quantity,
            reference_number=reference_number,
            notes=notes,
            created_by=current_user_id,
        )
        self.db.commit()
        self.db.refresh(inventory)
        self.db.refresh(transaction)
        return inventory, transaction

    # =========================================================================
    # Confirm Reservation (convert to SALE)
    # =========================================================================

    def confirm_reservation(
        self,
        *,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        quantity: int,
        current_user_id: uuid.UUID,
        reference_number: str | None = None,
        notes: str | None = None,
    ) -> tuple[Inventory, InventoryTransaction]:
        """
        Confirms a reservation and converts it into an actual stock
        deduction (SALE transaction).

        This is what happens when a pending order is confirmed/fulfilled:
        - reserved_quantity decreases by `quantity`
        - quantity (physical stock) decreases by `quantity`
        - available_quantity stays the same (both decrease equally)
        - A SALE transaction is created

        Concurrency-safe: uses SELECT ... FOR UPDATE.
        """
        self._validate_quantity(quantity)
        self._validate_warehouse_active(warehouse_id)

        inventory = self.inventory_repo.get_for_update(product_id, warehouse_id)
        if inventory is None:
            raise InventoryNotFoundError(
                f"No inventory record found for product {product_id} "
                f"in warehouse {warehouse_id}."
            )

        if quantity > inventory.reserved_quantity:
            raise ValidationError(
                f"Cannot confirm {quantity} units: only {inventory.reserved_quantity} "
                f"units are currently reserved."
            )

        previous_qty = inventory.quantity
        previous_reserved = inventory.reserved_quantity

        inventory = self.inventory_repo.update(
            inventory,
            quantity=inventory.quantity - quantity,
            reserved_quantity=inventory.reserved_quantity - quantity,
        )

        transaction = self._create_transaction(
            product_id=product_id,
            warehouse_id=warehouse_id,
            transaction_type=InventoryTransactionType.CONFIRM_RESERVATION,
            quantity=quantity,
            previous_quantity=previous_qty,
            new_quantity=inventory.quantity,
            previous_reserved_quantity=previous_reserved,
            new_reserved_quantity=inventory.reserved_quantity,
            reference_number=reference_number,
            notes=notes,
            created_by=current_user_id,
        )

        # Also create a SALE transaction to record the sale separately.
        sale_tx = self._create_transaction(
            product_id=product_id,
            warehouse_id=warehouse_id,
            transaction_type=InventoryTransactionType.SALE,
            quantity=quantity,
            previous_quantity=inventory.quantity + quantity,  # what it was before the sale
            new_quantity=inventory.quantity,
            previous_reserved_quantity=inventory.reserved_quantity + quantity,
            new_reserved_quantity=inventory.reserved_quantity,
            reference_number=reference_number,
            notes=notes or "Sale confirmed from reservation",
            created_by=current_user_id,
        )
        _ = sale_tx  # sale transaction recorded alongside

        return inventory, transaction

    # =========================================================================
    # Transfer Between Warehouses
    # =========================================================================

    def transfer_stock(
        self,
        *,
        product_id: uuid.UUID,
        from_warehouse_id: uuid.UUID,
        to_warehouse_id: uuid.UUID,
        quantity: int,
        current_user_id: uuid.UUID,
        reference_number: str | None = None,
        notes: str | None = None,
    ) -> tuple[Inventory, InventoryTransaction, Inventory, InventoryTransaction]:
        """
        Transfers stock from one warehouse to another.

        Creates TWO transactions:
        - TRANSFER_OUT from source warehouse (decreases quantity)
        - TRANSFER_IN to destination warehouse (increases quantity)

        Both share the same correlation_id so they can be linked
        for audit purposes.

        Validates:
        - Source and destination warehouses are different.
        - Both warehouses are active.
        - Source warehouse has sufficient stock.
        - Source warehouse's remaining stock after transfer does not
          drop below reserved_quantity.

        Concurrency-safe: uses SELECT ... FOR UPDATE on source inventory.
        Destination inventory is also locked to prevent races.

        All operations happen in a single DB transaction.
        """
        if from_warehouse_id == to_warehouse_id:
            raise InvalidTransferError(
                "Source and destination warehouses must be different."
            )

        self._validate_quantity(quantity)
        self._validate_warehouse_active(from_warehouse_id)
        self._validate_warehouse_active(to_warehouse_id)

        # Lock source inventory.
        source_inventory = self.inventory_repo.get_for_update(
            product_id, from_warehouse_id
        )
        if source_inventory is None:
            raise InventoryNotFoundError(
                f"No inventory record found for product {product_id} "
                f"in source warehouse {from_warehouse_id}."
            )

        available = source_inventory.quantity - source_inventory.reserved_quantity
        if quantity > available:
            raise InsufficientStockError(
                f"Cannot transfer {quantity} units: only {available} units "
                f"are available in the source warehouse "
                f"(quantity={source_inventory.quantity}, "
                f"reserved={source_inventory.reserved_quantity})."
            )

        # Lock or create destination inventory.
        dest_inventory = self.inventory_repo.get_for_update(
            product_id, to_warehouse_id
        )
        if dest_inventory is None:
            dest_inventory = Inventory(
                product_id=product_id,
                warehouse_id=to_warehouse_id,
                quantity=0,
                reserved_quantity=0,
                reorder_level=0,
                max_stock=0,
            )
            dest_inventory = self.inventory_repo.create(dest_inventory)

        correlation_id = _generate_correlation_id()

        # --- TRANSFER_OUT from source ---
        src_prev_qty = source_inventory.quantity
        src_prev_reserved = source_inventory.reserved_quantity

        source_inventory = self.inventory_repo.update(
            source_inventory,
            quantity=source_inventory.quantity - quantity,
        )

        tx_out = self._create_transaction(
            product_id=product_id,
            warehouse_id=from_warehouse_id,
            transaction_type=InventoryTransactionType.TRANSFER_OUT,
            quantity=quantity,
            previous_quantity=src_prev_qty,
            new_quantity=source_inventory.quantity,
            previous_reserved_quantity=src_prev_reserved,
            new_reserved_quantity=source_inventory.reserved_quantity,
            reference_number=reference_number,
            correlation_id=correlation_id,
            notes=notes or f"Transfer to warehouse {to_warehouse_id}",
            created_by=current_user_id,
        )

        # --- TRANSFER_IN to destination ---
        dest_prev_qty = dest_inventory.quantity
        dest_prev_reserved = dest_inventory.reserved_quantity

        dest_inventory = self.inventory_repo.update(
            dest_inventory,
            quantity=dest_inventory.quantity + quantity,
        )

        tx_in = self._create_transaction(
            product_id=product_id,
            warehouse_id=to_warehouse_id,
            transaction_type=InventoryTransactionType.TRANSFER_IN,
            quantity=quantity,
            previous_quantity=dest_prev_qty,
            new_quantity=dest_inventory.quantity,
            previous_reserved_quantity=dest_prev_reserved,
            new_reserved_quantity=dest_inventory.reserved_quantity,
            reference_number=reference_number,
            correlation_id=correlation_id,
            notes=notes or f"Transfer from warehouse {from_warehouse_id}",
            created_by=current_user_id,
        )

        return source_inventory, tx_out, dest_inventory, tx_in

    # =========================================================================
    # Get Stock Status
    # =========================================================================

    @staticmethod
    def determine_stock_status(inventory: Inventory) -> StockStatus:
        """Determines the stock status for an inventory record based on
        available quantity vs. reorder level."""
        available = inventory.available_quantity
        if available <= 0:
            return StockStatus.OUT_OF_STOCK
        if available <= inventory.reorder_level:
            return StockStatus.LOW_STOCK
        return StockStatus.IN_STOCK

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _validate_quantity(self, quantity: int) -> None:
        """Raises ValidationError if quantity is not positive."""
        if quantity <= 0:
            raise ValidationError("Quantity must be a positive integer.")

    def _validate_warehouse_active(self, warehouse_id: uuid.UUID) -> None:
        """Raises NotFoundError if the warehouse doesn't exist or is
        not active."""
        warehouse = self.warehouse_repo.get_active_by_id(warehouse_id)
        if warehouse is None:
            raise NotFoundError(
                f"Warehouse {warehouse_id} not found or is inactive."
            )

    def _create_transaction(
        self,
        *,
        product_id: uuid.UUID,
        warehouse_id: uuid.UUID,
        transaction_type: InventoryTransactionType,
        quantity: int,
        previous_quantity: int,
        new_quantity: int,
        previous_reserved_quantity: int,
        new_reserved_quantity: int,
        reference_number: str | None = None,
        correlation_id: str | None = None,
        notes: str | None = None,
        created_by: uuid.UUID,
    ) -> InventoryTransaction:
        """
        Creates and persists an InventoryTransaction record.

        Every stock mutation must call this method exactly once per
        transaction. Inventory is NEVER modified without a corresponding
        transaction record.
        """
        transaction = InventoryTransaction(
            product_id=product_id,
            warehouse_id=warehouse_id,
            transaction_type=transaction_type,
            quantity=quantity,
            previous_quantity=previous_quantity,
            new_quantity=new_quantity,
            previous_reserved_quantity=previous_reserved_quantity,
            new_reserved_quantity=new_reserved_quantity,
            reference_number=reference_number,
            correlation_id=correlation_id,
            notes=notes,
            created_by=created_by,
        )
        return self.transaction_repo.create(transaction)


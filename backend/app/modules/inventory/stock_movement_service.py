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

import logging
import uuid
from functools import wraps

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.product import Product
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

logger = logging.getLogger(__name__)


def _generate_correlation_id() -> str:
    """Generates a unique correlation ID for grouping related
    transactions (e.g. both sides of a warehouse transfer)."""
    import secrets
    return secrets.token_hex(16)


def _atomic_movement(method):
    """Run one stock movement inside a savepoint."""
    @wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            with self.db.begin_nested():
                return method(self, *args, **kwargs)
        except ConcurrencyConflictError:
            logger.warning("Inventory concurrency conflict during %s", method.__name__)
            raise
        except Exception:
            logger.exception("Inventory movement failed: operation=%s", method.__name__)
            raise
    return wrapper


class StockMovementService:
    """
    Central service for all inventory stock movements.
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

    @_atomic_movement
    def add_stock(self, *, product_id, warehouse_id, quantity, current_user_id, reference_number=None, notes=None):
        self._validate_quantity(quantity)
        self._validate_warehouse_active(warehouse_id)
        self._validate_product_exists(product_id)
        inventory = self.inventory_repo.get_for_update(product_id, warehouse_id)
        if inventory is None:
            inventory = Inventory(product_id=product_id, warehouse_id=warehouse_id, quantity=0, reserved_quantity=0, reorder_level=0, max_stock=0)
            inventory = self.inventory_repo.create(inventory)
        previous_qty = inventory.quantity
        previous_reserved = inventory.reserved_quantity
        inventory = self.inventory_repo.update(inventory, quantity=inventory.quantity + quantity)
        transaction = self._create_transaction(product_id=product_id, warehouse_id=warehouse_id, transaction_type=InventoryTransactionType.PURCHASE, quantity=quantity, previous_quantity=previous_qty, new_quantity=inventory.quantity, previous_reserved_quantity=previous_reserved, new_reserved_quantity=inventory.reserved_quantity, reference_number=reference_number, notes=notes, created_by=current_user_id)
        logger.info("Stock added: product=%s warehouse=%s quantity=%d", product_id, warehouse_id, quantity)
        return inventory, transaction

    @_atomic_movement
    def remove_stock(self, *, product_id, warehouse_id, quantity, current_user_id, reason="adjustment", reference_number=None, notes=None):
        self._validate_quantity(quantity)
        self._validate_warehouse_active(warehouse_id)
        self._validate_product_exists(product_id)
        inventory = self.inventory_repo.get_for_update(product_id, warehouse_id)
        if inventory is None:
            raise InventoryNotFoundError(f"No inventory record found for product {product_id} in warehouse {warehouse_id}.")
        if quantity > inventory.quantity:
            raise InsufficientStockError(f"Cannot remove {quantity} units: only {inventory.quantity} units on hand.")
        new_qty = inventory.quantity - quantity
        if new_qty < inventory.reserved_quantity:
            raise InsufficientStockError(f"Cannot remove: {inventory.reserved_quantity} units reserved, result {new_qty} would be less.")
        previous_qty = inventory.quantity
        previous_reserved = inventory.reserved_quantity
        type_map = {"damage": InventoryTransactionType.DAMAGE, "expired": InventoryTransactionType.EXPIRED, "adjustment": InventoryTransactionType.ADJUSTMENT}
        tx_type = type_map.get(reason, InventoryTransactionType.ADJUSTMENT)
        inventory = self.inventory_repo.update(inventory, quantity=new_qty)
        transaction = self._create_transaction(product_id=product_id, warehouse_id=warehouse_id, transaction_type=tx_type, quantity=quantity, previous_quantity=previous_qty, new_quantity=inventory.quantity, previous_reserved_quantity=previous_reserved, new_reserved_quantity=inventory.reserved_quantity, reference_number=reference_number, notes=notes, created_by=current_user_id)
        logger.info("Stock removed: product=%s warehouse=%s quantity=%d reason=%s", product_id, warehouse_id, quantity, reason)
        return inventory, transaction

    @_atomic_movement
    def adjust_stock(self, *, product_id, warehouse_id, new_quantity, current_user_id, reference_number=None, notes=None):
        if new_quantity < 0:
            raise ValidationError("New quantity cannot be negative.")
        self._validate_warehouse_active(warehouse_id)
        self._validate_product_exists(product_id)
        inventory = self.inventory_repo.get_for_update(product_id, warehouse_id)
        if inventory is None:
            raise InventoryNotFoundError(f"No inventory record found for product {product_id} in warehouse {warehouse_id}.")
        if new_quantity < inventory.reserved_quantity:
            raise InsufficientStockError(f"Cannot set to {new_quantity}: {inventory.reserved_quantity} units reserved.")
        previous_qty = inventory.quantity
        previous_reserved = inventory.reserved_quantity
        difference = abs(new_quantity - previous_qty)
        inventory = self.inventory_repo.update(inventory, quantity=new_quantity)
        transaction = self._create_transaction(product_id=product_id, warehouse_id=warehouse_id, transaction_type=InventoryTransactionType.ADJUSTMENT, quantity=difference, previous_quantity=previous_qty, new_quantity=inventory.quantity, previous_reserved_quantity=previous_reserved, new_reserved_quantity=inventory.reserved_quantity, reference_number=reference_number, notes=notes or f"Manual adjustment from {previous_qty} to {new_quantity}", created_by=current_user_id)
        logger.info("Stock adjusted: product=%s warehouse=%s prev=%d new=%d", product_id, warehouse_id, previous_qty, new_quantity)
        return inventory, transaction

    @_atomic_movement
    def reserve_stock(self, *, product_id, warehouse_id, quantity, current_user_id, reference_number=None, notes=None):
        self._validate_quantity(quantity)
        self._validate_warehouse_active(warehouse_id)
        self._validate_product_exists(product_id)
        inventory = self.inventory_repo.get_for_update(product_id, warehouse_id)
        if inventory is None:
            raise InventoryNotFoundError(f"No inventory record for product {product_id} in warehouse {warehouse_id}.")
        available = inventory.quantity - inventory.reserved_quantity
        if quantity > available:
            raise InsufficientStockError(f"Cannot reserve {quantity} units: only {available} available.")
        previous_qty = inventory.quantity
        previous_reserved = inventory.reserved_quantity
        inventory = self.inventory_repo.update(inventory, reserved_quantity=inventory.reserved_quantity + quantity)
        transaction = self._create_transaction(product_id=product_id, warehouse_id=warehouse_id, transaction_type=InventoryTransactionType.RESERVATION, quantity=quantity, previous_quantity=previous_qty, new_quantity=inventory.quantity, previous_reserved_quantity=previous_reserved, new_reserved_quantity=inventory.reserved_quantity, reference_number=reference_number, notes=notes, created_by=current_user_id)
        logger.info("Stock reserved: product=%s warehouse=%s quantity=%d", product_id, warehouse_id, quantity)
        return inventory, transaction

    @_atomic_movement
    def release_reservation(self, *, product_id, warehouse_id, quantity, current_user_id, reference_number=None, notes=None):
        self._validate_quantity(quantity)
        self._validate_warehouse_active(warehouse_id)
        self._validate_product_exists(product_id)
        inventory = self.inventory_repo.get_for_update(product_id, warehouse_id)
        if inventory is None:
            raise InventoryNotFoundError(f"No inventory record for product {product_id} in warehouse {warehouse_id}.")
        if quantity > inventory.reserved_quantity:
            raise ValidationError(f"Cannot release {quantity} units: only {inventory.reserved_quantity} reserved.")
        previous_qty = inventory.quantity
        previous_reserved = inventory.reserved_quantity
        inventory = self.inventory_repo.update(inventory, reserved_quantity=inventory.reserved_quantity - quantity)
        transaction = self._create_transaction(product_id=product_id, warehouse_id=warehouse_id, transaction_type=InventoryTransactionType.RELEASE, quantity=quantity, previous_quantity=previous_qty, new_quantity=inventory.quantity, previous_reserved_quantity=previous_reserved, new_reserved_quantity=inventory.reserved_quantity, reference_number=reference_number, notes=notes, created_by=current_user_id)
        logger.info("Reservation released: product=%s warehouse=%s quantity=%d", product_id, warehouse_id, quantity)
        return inventory, transaction

    @_atomic_movement
    def confirm_reservation(self, *, product_id, warehouse_id, quantity, current_user_id, reference_number=None, notes=None):
        self._validate_quantity(quantity)
        self._validate_warehouse_active(warehouse_id)
        self._validate_product_exists(product_id)
        inventory = self.inventory_repo.get_for_update(product_id, warehouse_id)
        if inventory is None:
            raise InventoryNotFoundError(f"No inventory record for product {product_id} in warehouse {warehouse_id}.")
        if quantity > inventory.reserved_quantity:
            raise ValidationError(f"Cannot confirm {quantity} units: only {inventory.reserved_quantity} reserved.")
        previous_qty = inventory.quantity
        previous_reserved = inventory.reserved_quantity
        inventory = self.inventory_repo.update(inventory, quantity=inventory.quantity - quantity, reserved_quantity=inventory.reserved_quantity - quantity)
        transaction = self._create_transaction(product_id=product_id, warehouse_id=warehouse_id, transaction_type=InventoryTransactionType.CONFIRM_RESERVATION, quantity=quantity, previous_quantity=previous_qty, new_quantity=inventory.quantity, previous_reserved_quantity=previous_reserved, new_reserved_quantity=inventory.reserved_quantity, reference_number=reference_number, notes=notes, created_by=current_user_id)
        self._create_transaction(product_id=product_id, warehouse_id=warehouse_id, transaction_type=InventoryTransactionType.SALE, quantity=quantity, previous_quantity=inventory.quantity + quantity, new_quantity=inventory.quantity, previous_reserved_quantity=inventory.reserved_quantity + quantity, new_reserved_quantity=inventory.reserved_quantity, reference_number=reference_number, notes=notes or "Sale confirmed from reservation", created_by=current_user_id)
        logger.info("Reservation confirmed: product=%s warehouse=%s quantity=%d", product_id, warehouse_id, quantity)
        return inventory, transaction

    @_atomic_movement
    def transfer_stock(self, *, product_id, from_warehouse_id, to_warehouse_id, quantity, current_user_id, reference_number=None, notes=None):
        if from_warehouse_id == to_warehouse_id:
            raise InvalidTransferError("Source and destination warehouses must be different.")
        self._validate_quantity(quantity)
        self._validate_warehouse_active(from_warehouse_id)
        self._validate_warehouse_active(to_warehouse_id)
        self._validate_product_exists(product_id)
        source = self.inventory_repo.get_for_update(product_id, from_warehouse_id)
        if source is None:
            raise InventoryNotFoundError(f"No inventory for product {product_id} in source warehouse {from_warehouse_id}.")
        available = source.quantity - source.reserved_quantity
        if quantity > available:
            raise InsufficientStockError(f"Cannot transfer {quantity} units: only {available} available.")
        dest = self.inventory_repo.get_for_update(product_id, to_warehouse_id)
        if dest is None:
            dest = Inventory(product_id=product_id, warehouse_id=to_warehouse_id, quantity=0, reserved_quantity=0, reorder_level=0, max_stock=0)
            dest = self.inventory_repo.create(dest)
        correlation_id = _generate_correlation_id()
        src_prev_qty = source.quantity
        src_prev_reserved = source.reserved_quantity
        source = self.inventory_repo.update(source, quantity=source.quantity - quantity)
        tx_out = self._create_transaction(product_id=product_id, warehouse_id=from_warehouse_id, transaction_type=InventoryTransactionType.TRANSFER_OUT, quantity=quantity, previous_quantity=src_prev_qty, new_quantity=source.quantity, previous_reserved_quantity=src_prev_reserved, new_reserved_quantity=source.reserved_quantity, reference_number=reference_number, correlation_id=correlation_id, notes=notes or f"Transfer to warehouse {to_warehouse_id}", created_by=current_user_id)
        dest_prev_qty = dest.quantity
        dest_prev_reserved = dest.reserved_quantity
        dest = self.inventory_repo.update(dest, quantity=dest.quantity + quantity)
        tx_in = self._create_transaction(product_id=product_id, warehouse_id=to_warehouse_id, transaction_type=InventoryTransactionType.TRANSFER_IN, quantity=quantity, previous_quantity=dest_prev_qty, new_quantity=dest.quantity, previous_reserved_quantity=dest_prev_reserved, new_reserved_quantity=dest.reserved_quantity, reference_number=reference_number, correlation_id=correlation_id, notes=notes or f"Transfer from warehouse {from_warehouse_id}", created_by=current_user_id)
        logger.info("Stock transferred: product=%s from=%s to=%s quantity=%d", product_id, from_warehouse_id, to_warehouse_id, quantity)
        return source, tx_out, dest, tx_in

    @staticmethod
    def determine_stock_status(inventory):
        available = inventory.available_quantity
        if available <= 0:
            return StockStatus.OUT_OF_STOCK
        if available <= inventory.reorder_level:
            return StockStatus.LOW_STOCK
        return StockStatus.IN_STOCK

    def _validate_quantity(self, quantity):
        if quantity <= 0:
            raise ValidationError("Quantity must be a positive integer.")

    def _validate_warehouse_active(self, warehouse_id):
        warehouse = self.warehouse_repo.get_active_by_id(warehouse_id)
        if warehouse is None:
            raise NotFoundError(f"Warehouse {warehouse_id} not found or is inactive.")

    def _validate_product_exists(self, product_id):
        product = self.db.get(Product, product_id)
        if product is None:
            raise NotFoundError(f"Product {product_id} not found.")

    def _create_transaction(self, *, product_id, warehouse_id, transaction_type, quantity, previous_quantity, new_quantity, previous_reserved_quantity, new_reserved_quantity, reference_number=None, correlation_id=None, notes=None, created_by=None):
        transaction = InventoryTransaction(product_id=product_id, warehouse_id=warehouse_id, transaction_type=transaction_type, quantity=quantity, previous_quantity=previous_quantity, new_quantity=new_quantity, previous_reserved_quantity=previous_reserved_quantity, new_reserved_quantity=new_reserved_quantity, reference_number=reference_number, correlation_id=correlation_id, notes=notes, created_by=created_by)
        return self.transaction_repo.create(transaction)

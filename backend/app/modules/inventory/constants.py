"""
modules/inventory/constants.py

Responsibility
--------------
Defines enumerations and threshold constants shared across the inventory
module's models, services, and schemas. Centralizing these here avoids
circular imports between models.py and schemas.py and keeps the policy
values (like what counts as "low stock") easy to find and change in one
place.
"""

import enum


class InventoryTransactionType(str, enum.Enum):
    """
    Every possible reason an inventory quantity can change.

    Each transaction creates an immutable audit record. Inventory
    quantities are NEVER modified directly — only through transactions
    of one of these types.

    - PURCHASE:    stock received from a supplier.
    - SALE:        stock removed for a confirmed customer order.
    - RETURN:      stock returned by a customer (goes back to inventory).
    - ADJUSTMENT:  manual correction (cycle count, reconciliation).
    - TRANSFER_IN: stock received from another warehouse.
    - TRANSFER_OUT: stock sent to another warehouse.
    - DAMAGE:      stock written off due to damage.
    - EXPIRED:     stock written off due to expiry.
    - RESERVATION: stock temporarily earmarked for an in-progress order.
    - RELEASE:     reservation released (cart expired, cancelled).
    """

    PURCHASE = "purchase"
    SALE = "sale"
    RETURN = "return"
    ADJUSTMENT = "adjustment"
    TRANSFER_IN = "transfer_in"
    TRANSFER_OUT = "transfer_out"
    DAMAGE = "damage"
    EXPIRED = "expired"
    RESERVATION = "reservation"
    RELEASE = "release"
    CONFIRM_RESERVATION = "confirm_reservation"


class StockStatus(str, enum.Enum):
    """
    The current stock health for a product-warehouse combination,
    determined by comparing available quantity against the reorder level.

    - IN_STOCK:     available quantity > reorder level.
    - LOW_STOCK:    available quantity > 0 but <= reorder level.
    - OUT_OF_STOCK: available quantity == 0.
    """

    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"


# Default threshold multiplier: when available stock drops below or equal
# to this percentage of max_stock (or an absolute reorder_level), the
# status becomes LOW_STOCK. Used as a fallback when reorder_level is not
# explicitly set on an inventory record.
DEFAULT_LOW_STOCK_THRESHOLD_PERCENT = 20  # percent

# Maximum number of items in a single bulk import batch.
BULK_IMPORT_MAX_BATCH_SIZE = 500

# Length of the auto-generated correlation_id for transfer operations.
CORRELATION_ID_LENGTH = 32


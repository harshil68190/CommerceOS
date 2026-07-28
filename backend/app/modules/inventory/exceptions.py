"""
modules/inventory/exceptions.py

Responsibility
--------------
Domain-specific exceptions for the inventory module.

These extend `core/exceptions.AppException` so the global error handler
in `middleware/error_handler.py` catches them automatically and maps
them to the correct HTTP status code — just like every other module's
exceptions.

No HTTP concepts, FastAPI imports, or status codes live here. The
exception's `status_code` attribute is only read by the error handler,
never by the code that raises it.
"""

from app.core.exceptions import AppException


class InsufficientStockError(AppException):
    """
    Raised when an operation attempts to reserve, remove, or transfer
    more stock than is currently available (accounting for existing
    reservations).

    Maps to HTTP 409 Conflict — the request is well-formed but conflicts
    with the resource's current state (another user may have just
    reserved the last unit).
    """

    status_code = 409
    error_code = "INSUFFICIENT_STOCK"


class InvalidTransferError(AppException):
    """
    Raised when a warehouse-to-warehouse transfer is invalid, e.g.:
    - source and destination warehouse are the same.
    - source warehouse is inactive.
    - source warehouse does not have enough stock.
    - destination warehouse does not exist or is inactive.

    Maps to HTTP 422 Validation Error — the request itself is
    structurally invalid for the business rules.
    """

    status_code = 422
    error_code = "INVALID_TRANSFER"


class DuplicateWarehouseCodeError(AppException):
    """
    Raised when attempting to create or update a warehouse with a
    warehouse code that already exists.

    Maps to HTTP 409 Conflict, mirroring how the products module handles
    duplicate SKUs and slugs.
    """

    status_code = 409
    error_code = "DUPLICATE_WAREHOUSE_CODE"


class WarehouseHasInventoryError(AppException):
    """
    Raised when attempting to deactivate or soft-delete a warehouse
    that still has inventory. Warehouses with stock must be cleared
    (inventory transferred or removed) before they can be deactivated.

    Maps to HTTP 409 Conflict.
    """

    status_code = 409
    error_code = "WAREHOUSE_HAS_INVENTORY"


class InventoryNotFoundError(AppException):
    """
    Raised when attempting to modify inventory for a product-warehouse
    combination that does not exist yet (the caller should use add_stock
    for first-time stock entry).

    Maps to HTTP 404 Not Found.
    """

    status_code = 404
    error_code = "INVENTORY_NOT_FOUND"


class BulkImportPartialFailureError(AppException):
    """
    Raised when a bulk import operation encounters validation errors on
    one or more items. The `details` dict contains per-item error
    information so the caller can identify which records need attention.

    The entire batch is rolled back on any failure (atomicity guarantee).

    Maps to HTTP 422 Validation Error.
    """

    status_code = 422
    error_code = "BULK_IMPORT_FAILED"


class ConcurrencyConflictError(AppException):
    """
    Raised when an optimistic-locking version mismatch is detected:
    another request modified the same inventory record between the time
    this request read it and the time it tried to write.

    The caller should retry the operation (re-read the current state
    and re-apply the change).

    Maps to HTTP 409 Conflict.
    """

    status_code = 409
    error_code = "CONCURRENCY_CONFLICT"


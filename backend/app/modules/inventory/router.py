"""
modules/inventory/router.py

Responsibility
--------------
HTTP layer for the entire inventory management subsystem. Every endpoint
is documented with:
- response models
- request models
- descriptions
- status codes
- authentication/authorization requirements

Route structure:
  /inventory/warehouses          — Warehouse CRUD (admin only)
  /inventory/stock               — Stock mutations (admin/inventory-manager)
  /inventory/reservations        — Reservation management
  /inventory/transfers           — Warehouse-to-warehouse transfers
  /inventory/transactions        — Transaction history (read-only)
  /inventory/reports             — Low stock / out of stock reports
  /inventory/bulk                — Bulk import
  /inventory/products/{id}       — Product-level inventory views

Following the same patterns as router.py in auth and products modules.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.modules.inventory.dependencies import (
    get_inventory_repository,
    get_stock_movement_service,
    get_transaction_repository,
    get_warehouse_service,
    get_warehouse_repository
)
from app.modules.inventory.permissions import (
    require_inventory_manager,
    require_inventory_read,
    require_warehouse_admin,
)
from app.modules.inventory.product_inventory_service import ProductInventoryService
from app.modules.inventory.repository import (
    InventoryFilters,
    TransactionFilters,
    WarehouseFilters,
)
from app.modules.inventory.schemas import (
    AddStockRequest,
    AdjustStockRequest,
    BulkImportRequest,
    BulkImportResponse,
    ConfirmReservationRequest,
    InventoryListResponse,
    InventoryResponse,
    InventoryTransactionResponse,
    LowStockItem,
    LowStockReportResponse,
    ProductStockSummary,
    ReleaseStockRequest,
    RemoveStockRequest,
    ReserveStockRequest,
    StockMovementResponse,
    TransferRequest,
    TransactionListResponse,
    WarehouseCreateRequest,
    WarehouseListResponse,
    WarehouseResponse,
    WarehouseUpdateRequest,
)
from app.modules.inventory.stock_movement_service import StockMovementService
from app.modules.inventory.warehouse_service import WarehouseService

router = APIRouter(prefix="/inventory", tags=["inventory"])

SortOption = Literal[
    "name_asc", "name_desc", "code_asc", "code_desc",
    "city_asc", "city_desc", "newest", "oldest",
    "quantity_asc", "quantity_desc",
    "available_asc", "available_desc",
]

# =========================================================================
# Warehouse endpoints
# =========================================================================


@router.post(
    "/warehouses",
    response_model=WarehouseResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new warehouse",
)
def create_warehouse(
    payload: WarehouseCreateRequest,
    _current_user: User = Depends(require_warehouse_admin),
    warehouse_service: WarehouseService = Depends(get_warehouse_service),
) -> WarehouseResponse:
    """
    Creates a new warehouse.

    Admin only. The warehouse `code` must be unique (case-insensitive)
    and will be uppercased automatically.
    """
    warehouse = warehouse_service.create_warehouse(payload)
    return WarehouseResponse.model_validate(warehouse)


@router.get(
    "/warehouses",
    response_model=WarehouseListResponse,
    status_code=status.HTTP_200_OK,
    summary="List warehouses",
)
def list_warehouses(
    query: str | None = Query(default=None, description="Search by name, code, or city"),
    is_active: bool | None = Query(default=None),
    city: str | None = Query(default=None),
    country: str | None = Query(default=None),
    sort: SortOption | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _current_user: User = Depends(require_inventory_read),
    warehouse_service: WarehouseService = Depends(get_warehouse_service),
) -> WarehouseListResponse:
    """
    Lists warehouses with optional filtering and pagination.

    Accessible to all authenticated users (admin, inventory_manager, customer).
    """
    filters = WarehouseFilters(
        query=query,
        is_active=is_active,
        city=city,
        country=country,
        sort=sort,
    )
    items, total = warehouse_service.list_warehouses(
        filters=filters, page=page, page_size=page_size
    )
    return WarehouseListResponse.build(
        items=[WarehouseResponse.model_validate(w) for w in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/warehouses/{warehouse_id}",
    response_model=WarehouseResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a warehouse by ID",
)
def get_warehouse(
    warehouse_id: uuid.UUID,
    _current_user: User = Depends(require_inventory_read),
    warehouse_service: WarehouseService = Depends(get_warehouse_service),
) -> WarehouseResponse:
    """
    Returns a single warehouse by ID.

    Accessible to all authenticated users.
    """
    warehouse = warehouse_service.get_warehouse_by_id(warehouse_id)
    return WarehouseResponse.model_validate(warehouse)


@router.put(
    "/warehouses/{warehouse_id}",
    response_model=WarehouseResponse,
    status_code=status.HTTP_200_OK,
    summary="Update a warehouse",
)
def update_warehouse(
    warehouse_id: uuid.UUID,
    payload: WarehouseUpdateRequest,
    _current_user: User = Depends(require_warehouse_admin),
    warehouse_service: WarehouseService = Depends(get_warehouse_service),
) -> WarehouseResponse:
    """
    Partially updates a warehouse.

    Admin only. If changing the `code`, the new value must be unique.
    """
    warehouse = warehouse_service.update_warehouse(warehouse_id, payload)
    return WarehouseResponse.model_validate(warehouse)


@router.delete(
    "/warehouses/{warehouse_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Deactivate a warehouse (soft-delete)",
)
def deactivate_warehouse(
    warehouse_id: uuid.UUID,
    _current_user: User = Depends(require_warehouse_admin),
    warehouse_service: WarehouseService = Depends(get_warehouse_service),
) -> None:
    """
    Deactivates a warehouse (soft-delete).

    Admin only. The warehouse must have zero inventory items before it
    can be deactivated — transfer or remove all stock first.

    This is NOT a physical delete: `is_active` is set to `False`,
    making the warehouse unavailable for new stock operations while
    preserving historical transaction records.
    """
    warehouse_service.deactivate_warehouse(warehouse_id)


@router.patch(
    "/warehouses/{warehouse_id}/reactivate",
    response_model=WarehouseResponse,
    status_code=status.HTTP_200_OK,
    summary="Reactivate a deactivated warehouse",
)
def reactivate_warehouse(
    warehouse_id: uuid.UUID,
    _current_user: User = Depends(require_warehouse_admin),
    warehouse_service: WarehouseService = Depends(get_warehouse_service),
) -> WarehouseResponse:
    """
    Reactivates a previously deactivated warehouse.

    Admin only. Sets `is_active` back to `True`.
    """
    warehouse = warehouse_service.reactivate_warehouse(warehouse_id)
    return WarehouseResponse.model_validate(warehouse)


# =========================================================================
# Inventory endpoints
# =========================================================================


@router.get(
    "",
    response_model=InventoryListResponse,
    status_code=status.HTTP_200_OK,
    summary="List inventory records",
)
def list_inventory(
    product_id: uuid.UUID | None = Query(default=None),
    warehouse_id: uuid.UUID | None = Query(default=None),
    warehouse_city: str | None = Query(default=None),
    stock_status: str | None = Query(
        default=None,
        description="Filter by stock status: 'in_stock', 'low_stock', 'out_of_stock'",
    ),
    query: str | None = Query(
        default=None,
        description="Search by product name or SKU",
    ),
    sort: SortOption | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _current_user: User = Depends(require_inventory_read),
    inventory_repo=Depends(get_inventory_repository),
) -> InventoryListResponse:
    """
    Lists inventory records across all warehouses with optional filtering.

    Accessible to all authenticated users.

    Supports filtering by:
    - Product ID, Warehouse ID
    - Stock status (in_stock, low_stock, out_of_stock)
    - Free-text search by product name or SKU
    - Sorting and pagination
    """
    from app.modules.inventory.constants import StockStatus

    status_enum = None
    if stock_status:
        try:
            status_enum = StockStatus(stock_status)
        except ValueError:
            status_enum = None

    filters = InventoryFilters(
        product_id=product_id,
        warehouse_id=warehouse_id,
        warehouse_city=warehouse_city,
        stock_status=status_enum,
        query=query,
        sort=sort,
    )
    items, total = inventory_repo.list_paginated(
        filters=filters, page=page, page_size=page_size
    )
    return InventoryListResponse.build(
        items=[InventoryResponse.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/products/{product_id}",
    response_model=ProductStockSummary,
    status_code=status.HTTP_200_OK,
    summary="Get aggregated stock for a product across all warehouses",
)
def get_product_inventory(
    product_id: uuid.UUID,
    _current_user: User = Depends(require_inventory_read),
    db: Session = Depends(get_db),
) -> ProductStockSummary:
    """
    Returns aggregated stock information for a product across all
    warehouses. Includes total_stock, total_available, warehouse_count,
    and a per-warehouse breakdown.

    Accessible to all authenticated users.
    """
    svc = ProductInventoryService(db)
    return svc.get_product_stock_summary(product_id)


# =========================================================================
# Stock movement endpoints
# =========================================================================


@router.post(
    "/stock/add",
    response_model=StockMovementResponse,
    status_code=status.HTTP_200_OK,
    summary="Add stock (purchase order / return received)",
)
def add_stock(
    payload: AddStockRequest,
    current_user: User = Depends(require_inventory_manager),
    stock_service: StockMovementService = Depends(get_stock_movement_service),
    db: Session = Depends(get_db),
) -> StockMovementResponse:
    """
    Adds physical stock to a product in a warehouse.

    Typically used when a purchase order is received or a return is
    processed. If no inventory record exists for this product-warehouse
    pair, one is created automatically.

    Creates a PURCHASE (or RETURN) transaction for audit.

    Restricted to ADMIN and INVENTORY_MANAGER.
    """
    inventory, transaction = stock_service.add_stock(
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        current_user_id=current_user.id,
        reference_number=payload.reference_number,
        notes=payload.notes,
    )
    db.commit()
    return StockMovementResponse(
        inventory=InventoryResponse.model_validate(inventory),
        transaction=InventoryTransactionResponse.model_validate(transaction),
    )


@router.post(
    "/stock/remove",
    response_model=StockMovementResponse,
    status_code=status.HTTP_200_OK,
    summary="Remove stock (damage, expired, adjustment)",
)
def remove_stock(
    payload: RemoveStockRequest,
    current_user: User = Depends(require_inventory_manager),
    stock_service: StockMovementService = Depends(get_stock_movement_service),
    db: Session = Depends(get_db),
) -> StockMovementResponse:
    """
    Removes physical stock from a product in a warehouse.

    Used for damage write-offs, expired goods, or manual adjustments.
    The `reason` field determines the transaction type (DAMAGE, EXPIRED,
    or ADJUSTMENT).

    Raises 409 if there isn't enough stock, or if removing would leave
    less stock than currently reserved.

    Restricted to ADMIN and INVENTORY_MANAGER.
    """
    inventory, transaction = stock_service.remove_stock(
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        current_user_id=current_user.id,
        reason=payload.reason,
        reference_number=payload.reference_number,
        notes=payload.notes,
    )
    db.commit()
    return StockMovementResponse(
        inventory=InventoryResponse.model_validate(inventory),
        transaction=InventoryTransactionResponse.model_validate(transaction),
    )


@router.post(
    "/stock/adjust",
    response_model=StockMovementResponse,
    status_code=status.HTTP_200_OK,
    summary="Adjust stock to exact quantity (cycle count)",
)
def adjust_stock(
    payload: AdjustStockRequest,
    current_user: User = Depends(require_inventory_manager),
    stock_service: StockMovementService = Depends(get_stock_movement_service),
    db: Session = Depends(get_db),
) -> StockMovementResponse:
    """
    Sets the exact stock quantity for a product in a warehouse.

    Used after cycle counts or reconciliation. Calculates the difference
    from current quantity and creates an ADJUSTMENT transaction.

    Raises 409 if the new quantity would be less than currently reserved.

    Restricted to ADMIN and INVENTORY_MANAGER.
    """
    inventory, transaction = stock_service.adjust_stock(
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        new_quantity=payload.new_quantity,
        current_user_id=current_user.id,
        reference_number=payload.reference_number,
        notes=payload.notes,
    )
    db.commit()
    return StockMovementResponse(
        inventory=InventoryResponse.model_validate(inventory),
        transaction=InventoryTransactionResponse.model_validate(transaction),
    )


# =========================================================================
# Reservation endpoints
# =========================================================================


@router.post(
    "/reserve",
    response_model=StockMovementResponse,
    status_code=status.HTTP_200_OK,
    summary="Reserve stock for a pending order",
)
def reserve_stock(
    payload: ReserveStockRequest,
    current_user: User = Depends(require_inventory_manager),
    stock_service: StockMovementService = Depends(get_stock_movement_service),
    db: Session = Depends(get_db),
) -> StockMovementResponse:
    """
    Reserves stock for a pending order (e.g. items added to cart).

    Reservation increases `reserved_quantity` but does NOT reduce
    physical `quantity`. Only `available_quantity` decreases.

    Raises 409 if there isn't enough available stock.

    Restricted to ADMIN and INVENTORY_MANAGER.
    """
    inventory, transaction = stock_service.reserve_stock(
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        current_user_id=current_user.id,
        reference_number=payload.reference_number,
        notes=payload.notes,
    )
    db.commit()
    return StockMovementResponse(
        inventory=InventoryResponse.model_validate(inventory),
        transaction=InventoryTransactionResponse.model_validate(transaction),
    )


@router.post(
    "/release",
    response_model=StockMovementResponse,
    status_code=status.HTTP_200_OK,
    summary="Release reserved stock (cart expired / order cancelled)",
)
def release_stock(
    payload: ReleaseStockRequest,
    current_user: User = Depends(require_inventory_manager),
    stock_service: StockMovementService = Depends(get_stock_movement_service),
    db: Session = Depends(get_db),
) -> StockMovementResponse:
    """
    Releases previously reserved stock back to available.

    Decreases `reserved_quantity` without changing physical `quantity`.
    `available_quantity` increases by the released amount.

    Raises 422 if releasing more than is currently reserved.

    Restricted to ADMIN and INVENTORY_MANAGER.
    """
    inventory, transaction = stock_service.release_reservation(
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        current_user_id=current_user.id,
        reference_number=payload.reference_number,
        notes=payload.notes,
    )
    db.commit()
    return StockMovementResponse(
        inventory=InventoryResponse.model_validate(inventory),
        transaction=InventoryTransactionResponse.model_validate(transaction),
    )


@router.post(
    "/confirm-reservation",
    response_model=StockMovementResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm a reservation (convert to SALE)",
)
def confirm_reservation(
    payload: ConfirmReservationRequest,
    current_user: User = Depends(require_inventory_manager),
    stock_service: StockMovementService = Depends(get_stock_movement_service),
    db: Session = Depends(get_db),
) -> StockMovementResponse:
    """
    Confirms a reservation and converts it into an actual stock deduction.

    This is the final step in the order lifecycle:
    - `reserved_quantity` decreases by the confirmed amount
    - `quantity` (physical stock) decreases by the confirmed amount
    - `available_quantity` stays the same (both decrease equally)
    - A SALE transaction is created

    Raises 422 if confirming more than is currently reserved.

    Restricted to ADMIN and INVENTORY_MANAGER.
    """
    inventory, transaction = stock_service.confirm_reservation(
        product_id=payload.product_id,
        warehouse_id=payload.warehouse_id,
        quantity=payload.quantity,
        current_user_id=current_user.id,
        reference_number=payload.reference_number,
        notes=payload.notes,
    )
    db.commit()
    return StockMovementResponse(
        inventory=InventoryResponse.model_validate(inventory),
        transaction=InventoryTransactionResponse.model_validate(transaction),
    )


# =========================================================================
# Transfer endpoint
# =========================================================================


@router.post(
    "/transfers",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Transfer stock between warehouses",
)
def transfer_stock(
    payload: TransferRequest,
    current_user: User = Depends(require_inventory_manager),
    stock_service: StockMovementService = Depends(get_stock_movement_service),
    db: Session = Depends(get_db),
) -> dict:
    """
    Transfers stock from one warehouse to another.

    Creates TWO transactions atomically:
    - TRANSFER_OUT from the source warehouse (decreases quantity)
    - TRANSFER_IN to the destination warehouse (increases quantity)

    Both transactions share the same `correlation_id` for audit
    traceability.

    Validates:
    - Source and destination warehouses are different
    - Both warehouses are active
    - Source warehouse has sufficient available stock

    Restricted to ADMIN and INVENTORY_MANAGER.
    """
    source_inv, tx_out, dest_inv, tx_in = stock_service.transfer_stock(
        product_id=payload.product_id,
        from_warehouse_id=payload.from_warehouse_id,
        to_warehouse_id=payload.to_warehouse_id,
        quantity=payload.quantity,
        current_user_id=current_user.id,
        reference_number=payload.reference_number,
        notes=payload.notes,
    )
    db.commit()
    return {
        "success": True,
        "correlation_id": tx_out.correlation_id,
        "source": {
            "inventory": InventoryResponse.model_validate(source_inv).model_dump(),
            "transaction": InventoryTransactionResponse.model_validate(tx_out).model_dump(),
        },
        "destination": {
            "inventory": InventoryResponse.model_validate(dest_inv).model_dump(),
            "transaction": InventoryTransactionResponse.model_validate(tx_in).model_dump(),
        },
    }


# =========================================================================
# Transaction history
# =========================================================================


@router.get(
    "/transactions",
    response_model=TransactionListResponse,
    status_code=status.HTTP_200_OK,
    summary="View transaction history",
)
def list_transactions(
    product_id: uuid.UUID | None = Query(default=None),
    warehouse_id: uuid.UUID | None = Query(default=None),
    transaction_type: str | None = Query(
        default=None,
        description="Filter by transaction type: purchase, sale, return, adjustment, transfer_in, transfer_out, damage, expired, reservation, release, confirm_reservation",
    ),
    reference_number: str | None = Query(default=None),
    correlation_id: str | None = Query(default=None),
    date_from: str | None = Query(default=None, description="ISO datetime filter (start)"),
    date_to: str | None = Query(default=None, description="ISO datetime filter (end)"),
    sort: SortOption | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _current_user: User = Depends(require_inventory_read),
    transaction_repo=Depends(get_transaction_repository),
) -> TransactionListResponse:
    """
    Returns paginated inventory transaction history.

    Every stock movement creates an immutable audit record. This
    endpoint provides full visibility into who changed what, when,
    and why.

    Accessible to all authenticated users.
    """
    from datetime import datetime

    from app.modules.inventory.constants import InventoryTransactionType

    tx_type_enum = None
    if transaction_type:
        try:
            tx_type_enum = InventoryTransactionType(transaction_type)
        except ValueError:
            tx_type_enum = None

    date_from_dt = None
    if date_from:
        try:
            date_from_dt = datetime.fromisoformat(date_from)
        except ValueError:
            pass

    date_to_dt = None
    if date_to:
        try:
            date_to_dt = datetime.fromisoformat(date_to)
        except ValueError:
            pass

    filters = TransactionFilters(
        product_id=product_id,
        warehouse_id=warehouse_id,
        transaction_type=tx_type_enum,
        reference_number=reference_number,
        correlation_id=correlation_id,
        date_from=date_from_dt,
        date_to=date_to_dt,
        sort=sort,
    )
    items, total = transaction_repo.list_paginated(
        filters=filters, page=page, page_size=page_size
    )
    return TransactionListResponse.build(
        items=[InventoryTransactionResponse.model_validate(t) for t in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# =========================================================================
# Reports
# =========================================================================


@router.get(
    "/reports/low-stock",
    response_model=LowStockReportResponse,
    status_code=status.HTTP_200_OK,
    summary="Low stock / out of stock report",
)
def low_stock_report(
    status_filter: str = Query(
        default="low_stock",
        description="'low_stock' (available <= reorder_level) or 'out_of_stock' (available <= 0)",
    ),
    _current_user: User = Depends(require_inventory_read),
    inventory_repo=Depends(get_inventory_repository),
) -> LowStockReportResponse:
    """
    Returns items that are low on stock or out of stock.

    - 'low_stock': available_quantity > 0 but <= reorder_level
    - 'out_of_stock': available_quantity <= 0

    Accessible to all authenticated users.
    """
    if status_filter == "out_of_stock":
        items = inventory_repo.get_out_of_stock_items()
    else:
        items = inventory_repo.get_low_stock_items()

    from app.modules.inventory.stock_movement_service import StockMovementService

    report_items = []
    for inv in items:
        status = StockMovementService.determine_stock_status(inv)
        product = inv.product
        warehouse = inv.warehouse
        report_items.append(
            LowStockItem(
                product_id=inv.product_id,
                product_name=product.name if product else "Unknown",
                product_sku=product.sku if product else "Unknown",
                warehouse_id=inv.warehouse_id,
                warehouse_name=warehouse.name if warehouse else "Unknown",
                warehouse_code=warehouse.code if warehouse else "Unknown",
                quantity=inv.quantity,
                reserved_quantity=inv.reserved_quantity,
                available_quantity=inv.available_quantity,
                reorder_level=inv.reorder_level,
                stock_status=status,
            )
        )

    return LowStockReportResponse(items=report_items, total=len(report_items))


# =========================================================================
# Bulk import
# =========================================================================


@router.post(
    "/bulk",
    response_model=BulkImportResponse,
    status_code=status.HTTP_200_OK,
    summary="Bulk import/update inventory",
)
def bulk_import(
    payload: BulkImportRequest,
    current_user: User = Depends(require_inventory_manager),
    db: Session = Depends(get_db),
    inventory_repo=Depends(get_inventory_repository),
    transaction_repo=Depends(get_transaction_repository),
    warehouse_repo=Depends(get_warehouse_repository),
) -> BulkImportResponse:
    """
    Bulk import or update inventory records.

    All operations are atomic: if any item fails validation, the entire
    batch is rolled back.

    Each item creates or updates an Inventory record and generates an
    ADJUSTMENT transaction for audit.

    Maximum 500 items per batch.

    Restricted to ADMIN and INVENTORY_MANAGER.
    """
    from app.core.exceptions import ValidationError as AppValidationError
    from app.modules.inventory.models import Inventory, InventoryTransaction
    from app.modules.inventory.constants import InventoryTransactionType as TxType

    errors: list[dict] = []
    processed_count = 0

    try:
        for item in payload.items:
            try:
                # Validate product exists
                from app.models.product import Product

                product = db.get(Product, item.product_id)
                if product is None:
                    errors.append(
                        {
                            "product_id": str(item.product_id),
                            "warehouse_id": str(item.warehouse_id),
                            "error": f"Product {item.product_id} not found.",
                        }
                    )
                    continue

                # Validate warehouse exists and is active
                warehouse = warehouse_repo.get_active_by_id(item.warehouse_id)
                if warehouse is None:
                    errors.append(
                        {
                            "product_id": str(item.product_id),
                            "warehouse_id": str(item.warehouse_id),
                            "error": f"Warehouse {item.warehouse_id} not found or inactive.",
                        }
                    )
                    continue

                # Upsert inventory
                existing = inventory_repo.get_for_update(
                    item.product_id, item.warehouse_id
                )
                if existing:
                    prev_qty = existing.quantity
                    prev_reserved = existing.reserved_quantity
                    inventory = inventory_repo.update(
                        existing,
                        quantity=item.quantity,
                        reserved_quantity=item.reserved_quantity,
                        reorder_level=item.reorder_level,
                        max_stock=item.max_stock,
                    )
                else:
                    prev_qty = 0
                    prev_reserved = 0
                    inventory = Inventory(
                        product_id=item.product_id,
                        warehouse_id=item.warehouse_id,
                        quantity=item.quantity,
                        reserved_quantity=item.reserved_quantity,
                        reorder_level=item.reorder_level,
                        max_stock=item.max_stock,
                    )
                    inventory = inventory_repo.create(inventory)

                # Create transaction record
                tx = InventoryTransaction(
                    product_id=item.product_id,
                    warehouse_id=item.warehouse_id,
                    transaction_type=TxType.ADJUSTMENT,
                    quantity=abs(item.quantity - prev_qty),
                    previous_quantity=prev_qty,
                    new_quantity=item.quantity,
                    previous_reserved_quantity=prev_reserved,
                    new_reserved_quantity=item.reserved_quantity,
                    notes="Bulk import",
                    created_by=current_user.id,
                )
                transaction_repo.create(tx)
                processed_count += 1

            except Exception as exc:
                errors.append(
                    {
                        "product_id": str(item.product_id),
                        "warehouse_id": str(item.warehouse_id),
                        "error": str(exc),
                    }
                )

        if errors and processed_count == 0:
            db.rollback()
            return BulkImportResponse(
                success=False, processed_count=0, errors=errors
            )

        db.commit()
        return BulkImportResponse(
            success=len(errors) == 0,
            processed_count=processed_count,
            errors=errors,
        )

    except Exception as exc:
        db.rollback()
        return BulkImportResponse(
            success=False,
            processed_count=0,
            errors=[{"error": str(exc)}],
        )


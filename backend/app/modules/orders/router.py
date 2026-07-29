"""
modules/orders/router.py

Responsibility
--------------
HTTP layer for the entire order management subsystem. Every endpoint
is documented with response/request models, descriptions, status codes,
and authentication/authorization requirements.

Route structure:
  POST   /orders                          -- Create order (customer/admin)
  GET    /orders                          -- List orders (admin/seller)
  GET    /orders/my                       -- List own orders (customer)
  GET    /orders/{id}                     -- Get order by ID
  PATCH  /orders/{id}                     -- Update order (pending only)
  DELETE /orders/{id}                     -- Delete order (pending only, admin)
  PATCH  /orders/{id}/cancel              -- Cancel order
  PATCH  /orders/{id}/confirm-payment     -- Confirm payment
  PATCH  /orders/{id}/process             -- Start processing
  PATCH  /orders/{id}/ship                -- Ship order
  PATCH  /orders/{id}/deliver             -- Deliver order
  PATCH  /orders/{id}/return              -- Return order
  PATCH  /orders/{id}/refund              -- Refund order
  POST   /orders/{id}/items               -- Add item to order
  PATCH  /orders/{id}/items/{item_id}     -- Update item
  DELETE /orders/{id}/items/{item_id}     -- Remove item

Following the same patterns as `modules/inventory/router.py`.
"""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, status

from app.models.user import User
from app.modules.orders.dependencies import (
    get_order_service,
)
from app.modules.orders.permissions import (
    require_order_admin,
    require_order_cancel,
    require_order_creator,
    require_order_read,
    require_order_return,
    require_order_shipping,
)
from app.modules.orders.repository import OrderFilters
from app.modules.orders.schemas import (
    CancelOrderRequest,
    OrderCreateRequest,
    OrderItemCreateRequest,
    OrderItemResponse,
    OrderItemUpdateRequest,
    OrderListResponse,
    OrderResponse,
    OrderStatusTransitionResponse,
    OrderUpdateRequest,
)

router = APIRouter(prefix="/orders", tags=["orders"])

SortOption = Literal[
    "newest", "oldest",
    "total_asc", "total_desc",
    "status_asc", "status_desc",
]


# =========================================================================
# Create Order
# =========================================================================


@router.post(
    "",
    response_model=OrderResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new order",
)
def create_order(
    payload: OrderCreateRequest,
    current_user: User = Depends(require_order_creator),
    service=Depends(get_order_service),
) -> OrderResponse:
    """
    Creates a new order with items and reserves inventory.

    Products are validated for existence and ACTIVE status.
    Prices are looked up from the Product catalog at order time.
    Stock is reserved atomically with order creation.

    Restricted to ADMIN and CUSTOMER.
    """
    order = service.create_order(payload, current_user)
    return OrderResponse.model_validate(order)


# =========================================================================
# List Orders (admin/seller)
# =========================================================================


@router.get(
    "",
    response_model=OrderListResponse,
    status_code=status.HTTP_200_OK,
    summary="List all orders (admin/seller)",
)
def list_orders(
    customer_id: uuid.UUID | None = Query(default=None),
    status_filter: str | None = Query(
        default=None, alias="status",
        description="Filter by order status",
    ),
    payment_status: str | None = Query(default=None),
    sort: SortOption | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_order_read),
    service=Depends(get_order_service),
) -> OrderListResponse:
    """
    Lists all orders with optional filtering and pagination.

    Accessible to ADMIN and SELLER.
    """
    filters = OrderFilters(
        customer_id=customer_id,
        status=status_filter,
        payment_status=payment_status,
        sort=sort,
    )
    items, total = service.list_orders(
        filters=filters, page=page, page_size=page_size
    )
    return OrderListResponse.build(
        items=[OrderResponse.model_validate(o) for o in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# =========================================================================
# List My Orders (customer)
# =========================================================================


@router.get(
    "/my",
    response_model=OrderListResponse,
    status_code=status.HTTP_200_OK,
    summary="List own orders (customer)",
)
def list_my_orders(
    status_filter: str | None = Query(
        default=None, alias="status",
        description="Filter by order status",
    ),
    sort: SortOption | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: User = Depends(require_order_creator),
    service=Depends(get_order_service),
) -> OrderListResponse:
    """
    Lists orders for the currently authenticated customer.

    Accessible to ADMIN and CUSTOMER.
    """
    filters = OrderFilters(
        status=status_filter,
        sort=sort,
    )
    items, total = service.get_orders_for_customer(
        customer_id=current_user.id,
        filters=filters,
        page=page,
        page_size=page_size,
    )
    return OrderListResponse.build(
        items=[OrderResponse.model_validate(o) for o in items],
        total=total,
        page=page,
        page_size=page_size,
    )


# =========================================================================
# Get Order by ID
# =========================================================================


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Get an order by ID",
)
def get_order(
    order_id: uuid.UUID,
    current_user: User = Depends(require_order_read),
    service=Depends(get_order_service),
) -> OrderResponse:
    """
    Returns a single order by ID.

    Accessible to ADMIN and SELLER.
    """
    order = service.get_order_by_id(order_id)
    return OrderResponse.model_validate(order)


# =========================================================================
# Update Order
# =========================================================================


@router.patch(
    "/{order_id}",
    response_model=OrderResponse,
    status_code=status.HTTP_200_OK,
    summary="Update an order (pending only)",
)
def update_order(
    order_id: uuid.UUID,
    payload: OrderUpdateRequest,
    current_user: User = Depends(require_order_creator),
    service=Depends(get_order_service),
) -> OrderResponse:
    """
    Partially updates an order's editable fields (notes, shipping_cost,
    discount). Only allowed while order is PENDING.

    If shipping_cost or discount changes, the total is recalculated.
    """
    order = service.update_order(order_id, payload, current_user)
    return OrderResponse.model_validate(order)


# =========================================================================
# Delete Order (admin only)
# =========================================================================


@router.delete(
    "/{order_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a pending order (admin only)",
)
def delete_order(
    order_id: uuid.UUID,
    current_user: User = Depends(require_order_admin),
    service=Depends(get_order_service),
) -> None:
    """
    Permanently removes a PENDING order.

    Releases reserved inventory before deletion.
    Admin only.
    """
    service.delete_order(order_id, current_user)


# =========================================================================
# Cancel Order
# =========================================================================


@router.patch(
    "/{order_id}/cancel",
    response_model=OrderStatusTransitionResponse,
    status_code=status.HTTP_200_OK,
    summary="Cancel an order",
)
def cancel_order(
    order_id: uuid.UUID,
    payload: CancelOrderRequest = Depends(),
    current_user: User = Depends(require_order_cancel),
    service=Depends(get_order_service),
) -> OrderStatusTransitionResponse:
    """
    Cancels an order. Releases reserved inventory.

    Only allowed before shipping (PENDING, CONFIRMED, PROCESSING).

    Accessible to ADMIN and CUSTOMER (own orders).
    """
    order = service.cancel_order(order_id, payload, current_user)
    return OrderStatusTransitionResponse(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        payment_status=order.payment_status,
        version=order.version,
        updated_at=order.updated_at,
        message="Order cancelled successfully.",
    )


# =========================================================================
# Confirm Payment
# =========================================================================


@router.patch(
    "/{order_id}/confirm-payment",
    response_model=OrderStatusTransitionResponse,
    status_code=status.HTTP_200_OK,
    summary="Confirm payment for an order",
)
def confirm_payment(
    order_id: uuid.UUID,
    current_user: User = Depends(require_order_admin),
    service=Depends(get_order_service),
) -> OrderStatusTransitionResponse:
    """
    Confirms payment for an order.

    PENDING -> CONFIRMED. Payment status changes to PAID.
    Converts reservation to confirmed sale (deducts stock).

    Admin only.
    """
    order = service.confirm_order(order_id, current_user)
    return OrderStatusTransitionResponse(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        payment_status=order.payment_status,
        version=order.version,
        updated_at=order.updated_at,
        message="Payment confirmed. Stock deducted.",
    )


# =========================================================================
# Start Processing
# =========================================================================


@router.patch(
    "/{order_id}/process",
    response_model=OrderStatusTransitionResponse,
    status_code=status.HTTP_200_OK,
    summary="Start processing an order",
)
def process_order(
    order_id: uuid.UUID,
    current_user: User = Depends(require_order_shipping),
    service=Depends(get_order_service),
) -> OrderStatusTransitionResponse:
    """
    Starts warehouse processing.

    CONFIRMED -> PROCESSING.

    Accessible to ADMIN and SELLER.
    """
    order = service.process_order(order_id, current_user)
    return OrderStatusTransitionResponse(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        payment_status=order.payment_status,
        version=order.version,
        updated_at=order.updated_at,
        message="Order is now being processed.",
    )


# =========================================================================
# Ship Order
# =========================================================================


@router.patch(
    "/{order_id}/ship",
    response_model=OrderStatusTransitionResponse,
    status_code=status.HTTP_200_OK,
    summary="Ship an order",
)
def ship_order(
    order_id: uuid.UUID,
    current_user: User = Depends(require_order_shipping),
    service=Depends(get_order_service),
) -> OrderStatusTransitionResponse:
    """
    Marks order as shipped (carrier picked up).

    PROCESSING -> SHIPPED.

    Accessible to ADMIN and SELLER.
    """
    order = service.ship_order(order_id, current_user)
    return OrderStatusTransitionResponse(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        payment_status=order.payment_status,
        version=order.version,
        updated_at=order.updated_at,
        message="Order shipped.",
    )


# =========================================================================
# Deliver Order
# =========================================================================


@router.patch(
    "/{order_id}/deliver",
    response_model=OrderStatusTransitionResponse,
    status_code=status.HTTP_200_OK,
    summary="Deliver an order",
)
def deliver_order(
    order_id: uuid.UUID,
    current_user: User = Depends(require_order_shipping),
    service=Depends(get_order_service),
) -> OrderStatusTransitionResponse:
    """
    Marks order as delivered to customer.

    SHIPPED -> DELIVERED.

    Accessible to ADMIN and SELLER.
    """
    order = service.deliver_order(order_id, current_user)
    return OrderStatusTransitionResponse(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        payment_status=order.payment_status,
        version=order.version,
        updated_at=order.updated_at,
        message="Order delivered.",
    )


# =========================================================================
# Return Order
# =========================================================================


@router.patch(
    "/{order_id}/return",
    response_model=OrderStatusTransitionResponse,
    status_code=status.HTTP_200_OK,
    summary="Process a return",
)
def return_order(
    order_id: uuid.UUID,
    current_user: User = Depends(require_order_return),
    service=Depends(get_order_service),
) -> OrderStatusTransitionResponse:
    """
    Processes a return after delivery.

    DELIVERED -> RETURNED.

    Accessible to ADMIN and SELLER.
    """
    order = service.return_order(order_id, current_user)
    return OrderStatusTransitionResponse(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        payment_status=order.payment_status,
        version=order.version,
        updated_at=order.updated_at,
        message="Return processed.",
    )


# =========================================================================
# Refund Order
# =========================================================================


@router.patch(
    "/{order_id}/refund",
    response_model=OrderStatusTransitionResponse,
    status_code=status.HTTP_200_OK,
    summary="Process a refund",
)
def refund_order(
    order_id: uuid.UUID,
    current_user: User = Depends(require_order_admin),
    service=Depends(get_order_service),
) -> OrderStatusTransitionResponse:
    """
    Processes a refund after return.

    RETURNED -> REFUNDED. Payment status changes to REFUNDED.

    Admin only.
    """
    order = service.refund_order(order_id, current_user)
    return OrderStatusTransitionResponse(
        id=order.id,
        order_number=order.order_number,
        status=order.status,
        payment_status=order.payment_status,
        version=order.version,
        updated_at=order.updated_at,
        message="Refund completed.",
    )


# =========================================================================
# Order Item Management
# =========================================================================


@router.post(
    "/{order_id}/items",
    response_model=OrderItemResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add item to order",
)
def add_order_item(
    order_id: uuid.UUID,
    payload: OrderItemCreateRequest,
    current_user: User = Depends(require_order_creator),
    service=Depends(get_order_service),
) -> OrderItemResponse:
    """
    Adds a new item to a PENDING order.

    Validates product existence and ACTIVE status.
    Reserves additional inventory.

    Accessible to ADMIN and CUSTOMER (own orders).
    """
    item = service.add_item_to_order(order_id, payload, current_user)
    return OrderItemResponse.model_validate(item)


@router.patch(
    "/{order_id}/items/{item_id}",
    response_model=OrderItemResponse,
    status_code=status.HTTP_200_OK,
    summary="Update order item quantity",
)
def update_order_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: OrderItemUpdateRequest,
    current_user: User = Depends(require_order_creator),
    service=Depends(get_order_service),
) -> OrderItemResponse:
    """
    Updates the quantity of an item on a PENDING order.

    Adjusts inventory reservation:
    - If quantity increases, more stock is reserved.
    - If quantity decreases, excess reservation is released.

    Accessible to ADMIN and CUSTOMER (own orders).
    """
    item = service.update_order_item(order_id, item_id, payload, current_user)
    return OrderItemResponse.model_validate(item)


@router.delete(
    "/{order_id}/items/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove item from order",
)
def remove_order_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    current_user: User = Depends(require_order_creator),
    service=Depends(get_order_service),
) -> None:
    """
    Removes an item from a PENDING order.

    Releases the reserved inventory for this item.
    Recalculates order totals.

    Accessible to ADMIN and CUSTOMER (own orders).
    """
    service.remove_item_from_order(order_id, item_id, current_user)

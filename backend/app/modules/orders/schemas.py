"""
modules/orders/schemas.py

Responsibility
--------------
Every request/response shape the orders module's API exposes.
Follows the same conventions as `schemas/inventory.py`:
Pydantic v2 models with `from_attributes=True` for ORM-to-schema
conversion, explicit field validation, and comprehensive documentation
for auto-generated OpenAPI/Swagger docs.

Architectural rules:
- Order creation requests contain a list of items (product_id, warehouse_id, quantity).
- Prices are NOT accepted in the request — they are looked up from the Product catalog.
- All monetary fields use Decimal for precision.
- Response schemas include computed fields (subtotal, total, line_total).
"""

import uuid
from datetime import datetime
from decimal import Decimal
from math import ceil
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.modules.orders.constants import OrderStatus, PaymentStatus


# =========================================================================
# Order Item Schemas
# =========================================================================


class OrderItemCreateRequest(BaseModel):
    """
    A single item in an order creation request.

    The client specifies which product, which warehouse, and how many.
    The unit_price is looked up from the Product catalog at order time
    — the client does NOT supply prices.
    """

    product_id: uuid.UUID
    warehouse_id: uuid.UUID
    quantity: int = Field(gt=0, description="Number of units to order")


class OrderItemResponse(BaseModel):
    """A single line item on an order, as returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    product_id: uuid.UUID
    product_name: str
    product_sku: str
    warehouse_id: uuid.UUID
    quantity: int
    unit_price: Decimal
    line_total: Decimal
    created_at: datetime


# =========================================================================
# Order Schemas
# =========================================================================


class OrderCreateRequest(BaseModel):
    """
    Request body for POST /orders.

    Contains the list of items being ordered. Prices are determined
    server-side from the Product catalog — the client never supplies
    prices directly.

    Optional fields:
    - notes: free-text notes for the order.
    - shipping_cost: if applicable (default 0).
    - discount: if applicable (default 0).
    """

    items: list[OrderItemCreateRequest] = Field(
        min_length=1,
        description="Items to order (at least one required).",
    )
    notes: str | None = Field(default=None, max_length=2000)
    shipping_cost: Decimal = Field(default=Decimal("0.00"), ge=0)
    discount: Decimal = Field(default=Decimal("0.00"), ge=0)

    @model_validator(mode="after")
    def _validate_items_unique(self) -> "OrderCreateRequest":
        """Ensure no duplicate product-warehouse combinations in the
        request."""
        seen = set()
        for item in self.items:
            key = (item.product_id, item.warehouse_id)
            if key in seen:
                raise ValueError(
                    f"Duplicate item: product {item.product_id} in "
                    f"warehouse {item.warehouse_id} appears more than once."
                )
            seen.add(key)
        return self


class OrderUpdateRequest(BaseModel):
    """Request body for PATCH /orders/{id} — partial update of
    editable order fields."""

    notes: str | None = Field(default=None, max_length=2000)
    shipping_cost: Decimal | None = Field(default=None, ge=0)
    discount: Decimal | None = Field(default=None, ge=0)


class OrderItemUpdateRequest(BaseModel):
    """Request body for PATCH /orders/{id}/items/{item_id}.

    Only quantity can be updated on an existing item. If quantity
    changes, the inventory reservation is adjusted automatically
    (more reserved or partially released)."""

    quantity: int = Field(gt=0, description="New quantity for this item")


class OrderStatusUpdateResponse(BaseModel):
    """Response returned by order status transition endpoints."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_number: str
    status: OrderStatus
    payment_status: PaymentStatus
    version: int
    updated_at: datetime


class CancelOrderRequest(BaseModel):
    """Request body for cancelling an order."""

    reason: str | None = Field(default=None, max_length=1000)


class OrderResponse(BaseModel):
    """Full public representation of an order."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_number: str
    customer_id: uuid.UUID
    status: OrderStatus
    subtotal: Decimal
    tax: Decimal
    shipping_cost: Decimal
    discount: Decimal
    total: Decimal
    payment_status: PaymentStatus
    notes: str | None
    reserved_until: datetime | None
    cancel_reason: str | None
    version: int
    created_by: uuid.UUID
    updated_by: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemResponse]


class OrderListResponse(BaseModel):
    """Paginated envelope for order listings."""

    items: list[OrderResponse]
    total: int
    page: int
    page_size: int
    pages: int

    @classmethod
    def build(
        cls, *, items: list[OrderResponse], total: int, page: int, page_size: int
    ) -> "OrderListResponse":
        pages = ceil(total / page_size) if page_size > 0 else 0
        return cls(items=items, total=total, page=page, page_size=page_size, pages=pages)


# =========================================================================
# Order Status Transition Response
# =========================================================================


class OrderStatusTransitionResponse(BaseModel):
    """Response returned by status transition endpoints (cancel, confirm,
    ship, deliver, return, refund)."""

    id: uuid.UUID
    order_number: str
    status: OrderStatus
    payment_status: PaymentStatus
    version: int
    updated_at: datetime
    message: str | None = None

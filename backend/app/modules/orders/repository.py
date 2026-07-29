"""
modules/orders/repository.py

Responsibility
--------------
Two repository classes — OrderRepository and OrderItemRepository — following
the exact same patterns as ProductRepository (products module) and
UserRepository (auth module).

Key architectural guarantees:
- Orders are immutable business records: no soft-delete, no physical
  delete for orders that have been confirmed/processed/shipped.
- Order items are cascade-deleted with their parent order.
- Repositories are pure data-access: no business rules, no HTTP concepts.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.modules.orders.constants import OrderStatus, PaymentStatus
from app.modules.orders.models import Order, OrderItem


# =========================================================================
# Filter Dataclasses
# =========================================================================


@dataclass
class OrderFilters:
    """Structured filter parameters for order listing/search."""

    customer_id: uuid.UUID | None = None
    status: OrderStatus | None = None
    payment_status: PaymentStatus | None = None
    order_number: str | None = None
    date_from: datetime | None = None
    date_to: datetime | None = None
    sort: str | None = None


@dataclass
class OrderItemFilters:
    """Structured filter parameters for order item listing."""

    product_id: uuid.UUID | None = None
    warehouse_id: uuid.UUID | None = None
    sort: str | None = None


# Sort option maps
_ORDER_SORT_OPTIONS: dict[str, tuple[Any, bool]] = {
    "newest": (Order.created_at, True),
    "oldest": (Order.created_at, False),
    "order_number_asc": (Order.order_number, False),
    "order_number_desc": (Order.order_number, True),
    "total_asc": (Order.total, False),
    "total_desc": (Order.total, True),
}
_ORDER_DEFAULT_SORT = "newest"

_ORDER_ITEM_SORT_OPTIONS: dict[str, tuple[Any, bool]] = {
    "newest": (OrderItem.created_at, True),
    "oldest": (OrderItem.created_at, False),
}
_ORDER_ITEM_DEFAULT_SORT = "newest"


# =========================================================================
# OrderRepository
# =========================================================================


class OrderRepository:
    """Data-access layer for Order records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Writes ---------------------------------------------------

    def create(self, order: Order) -> Order:
        """Persists a new Order and returns it with generated
        id/server defaults populated."""
        self.db.add(order)
        self.db.flush()
        self.db.refresh(order)
        return order

    def update(self, order: Order, **fields: Any) -> Order:
        """Applies field updates to an already-loaded Order and
        flushes. Increments version for optimistic concurrency."""
        if "version" in fields:
            fields.pop("version")  # never manually set version
        fields["version"] = order.version + 1

        for field_name, value in fields.items():
            setattr(order, field_name, value)
        self.db.flush()
        self.db.refresh(order)
        return order

    def delete(self, order: Order) -> None:
        """Permanently removes an order row. Only allowed for
        PENDING orders that haven't been confirmed yet."""
        self.db.delete(order)
        self.db.flush()

    # --- Single-row reads ---------------------------------------------------

    def get_by_id(self, order_id: uuid.UUID) -> Order | None:
        """Returns an order by id, with items eagerly loaded."""
        stmt = (
            select(Order)
            .options(joinedload(Order.items))
            .where(Order.id == order_id)
        )
        return self.db.execute(stmt).unique().scalar_one_or_none()

    def get_by_order_number(self, order_number: str) -> Order | None:
        """Returns an order by its human-readable order number."""
        stmt = select(Order).where(Order.order_number == order_number)
        return self.db.execute(stmt).scalar_one_or_none()

    def get_by_id_for_update(self, order_id: uuid.UUID) -> Order | None:
        """Returns an order locked FOR UPDATE, with items eagerly loaded.
        Used by status transitions that modify the order."""
        stmt = (
            select(Order)
            .options(joinedload(Order.items))
            .where(Order.id == order_id)
            .with_for_update()
        )
        return self.db.execute(stmt).unique().scalar_one_or_none()

    # --- Uniqueness checks ---------------------------------------------------

    def exists_order_number(
        self, order_number: str, *, exclude_id: uuid.UUID | None = None
    ) -> bool:
        """Returns True if another order already uses this order number."""
        stmt = select(Order.id).where(Order.order_number == order_number)
        if exclude_id is not None:
            stmt = stmt.where(Order.id != exclude_id)
        return self.db.execute(stmt).first() is not None

    # --- Filtering / pagination ---------------------------------------------------

    def _build_filtered_statement(self, filters: OrderFilters) -> Select:
        """Shared WHERE-clause construction for listing/search."""
        stmt = select(Order).options(joinedload(Order.items))

        if filters.customer_id is not None:
            stmt = stmt.where(Order.customer_id == filters.customer_id)
        if filters.status is not None:
            stmt = stmt.where(Order.status == filters.status)
        if filters.payment_status is not None:
            stmt = stmt.where(Order.payment_status == filters.payment_status)
        if filters.order_number is not None:
            stmt = stmt.where(Order.order_number == filters.order_number)
        if filters.date_from is not None:
            stmt = stmt.where(Order.created_at >= filters.date_from)
        if filters.date_to is not None:
            stmt = stmt.where(Order.created_at <= filters.date_to)

        sort_key = (
            filters.sort
            if filters.sort in _ORDER_SORT_OPTIONS
            else _ORDER_DEFAULT_SORT
        )
        column, descending = _ORDER_SORT_OPTIONS[sort_key]
        stmt = stmt.order_by(column.desc() if descending else column.asc())

        return stmt

    def list_paginated(
        self, *, filters: OrderFilters, page: int, page_size: int
    ) -> tuple[list[Order], int]:
        """Returns (items, total_count) for order listing."""
        return self._paginate(filters, page=page, page_size=page_size)

    def _paginate(
        self, filters: OrderFilters, *, page: int, page_size: int
    ) -> tuple[list[Order], int]:
        base_stmt = self._build_filtered_statement(filters)

        count_stmt = select(func.count()).select_from(
            base_stmt.order_by(None).subquery()
        )
        total = self.db.execute(count_stmt).scalar_one()

        offset = (page - 1) * page_size
        page_stmt = base_stmt.offset(offset).limit(page_size)
        items = list(self.db.execute(page_stmt).unique().scalars().all())

        return items, total

    # --- Aggregates ---------------------------------------------------

    def count_by_customer(self, customer_id: uuid.UUID) -> int:
        """Returns the number of orders placed by a customer."""
        stmt = (
            select(func.count())
            .select_from(Order)
            .where(Order.customer_id == customer_id)
        )
        return self.db.execute(stmt).scalar_one()

    def get_customer_order_total(self, customer_id: uuid.UUID) -> Decimal:
        """Returns the total amount spent by a customer."""
        stmt = (
            select(func.coalesce(func.sum(Order.total), 0))
            .select_from(Order)
            .where(Order.customer_id == customer_id)
        )
        return self.db.execute(stmt).scalar_one()


# =========================================================================
# OrderItemRepository
# =========================================================================


class OrderItemRepository:
    """Data-access layer for OrderItem records."""

    def __init__(self, db: Session) -> None:
        self.db = db

    # --- Writes ---------------------------------------------------

    def create(self, item: OrderItem) -> OrderItem:
        """Creates a new OrderItem and flushes."""
        self.db.add(item)
        self.db.flush()
        self.db.refresh(item)
        return item

    def update(self, item: OrderItem, **fields: Any) -> OrderItem:
        """Applies field updates to an already-loaded OrderItem."""
        for field_name, value in fields.items():
            setattr(item, field_name, value)
        self.db.flush()
        self.db.refresh(item)
        return item

    def delete(self, item: OrderItem) -> None:
        """Removes an OrderItem."""
        self.db.delete(item)
        self.db.flush()

    # --- Reads ---------------------------------------------------

    def get_by_id(self, item_id: uuid.UUID) -> OrderItem | None:
        """Returns an OrderItem by id."""
        return self.db.get(OrderItem, item_id)

    def get_by_order_and_id(
        self, order_id: uuid.UUID, item_id: uuid.UUID
    ) -> OrderItem | None:
        """Returns an OrderItem by order id and item id."""
        stmt = select(OrderItem).where(
            OrderItem.id == item_id,
            OrderItem.order_id == order_id,
        )
        return self.db.execute(stmt).scalar_one_or_none()

    def list_by_order(self, order_id: uuid.UUID) -> list[OrderItem]:
        """Lists all items for a given order."""
        stmt = (
            select(OrderItem)
            .where(OrderItem.order_id == order_id)
            .order_by(OrderItem.created_at.asc())
        )
        return list(self.db.execute(stmt).scalars().all())

    def delete_by_order(self, order_id: uuid.UUID) -> None:
        """Deletes all items for a given order."""
        stmt = select(OrderItem).where(OrderItem.order_id == order_id)
        items = list(self.db.execute(stmt).scalars().all())
        for item in items:
            self.db.delete(item)
        self.db.flush()

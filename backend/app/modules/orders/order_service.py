"""
modules/orders/order_service.py

Responsibility
--------------
Every business rule for order management: creation, status transitions,
inventory integration (reservation/release), and validation.
`router.py` calls exactly one method per endpoint and does nothing else.

No SQL lives here — every persistence operation goes through
`OrderRepository` and `OrderItemRepository`. Every raised error is a
domain exception from `exceptions.py` or `core/exceptions.py`.

Inventory integration:
- CREATE order: reserves stock via StockMovementService.reserve_stock()
- CONFIRM order: converts reservation via confirm_reservation()
- CANCEL order: releases reservation via StockMovementService.release_reservation()
- All inventory operations happen in the same DB transaction as the order update.
"""

import logging
import secrets
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError, ValidationError
from app.models.product import Product, ProductStatus
from app.models.user import User
from app.modules.inventory.stock_movement_service import StockMovementService
from app.modules.orders.constants import (
    CANCELLABLE_STATUSES,
    ORDER_STATUS_TRANSITIONS,
    OrderStatus,
    PaymentStatus,
    STATUSES_WITH_RESERVATION,
)
from app.modules.orders.exceptions import (
    InvalidOrderStatusTransitionError,
    OrderCannotBeModifiedError,
    OrderItemValidationError,
    OrderNotFoundError,
)
from app.modules.orders.models import Order, OrderItem
from app.modules.orders.repository import OrderItemRepository, OrderRepository
from app.modules.orders.schemas import (
    CancelOrderRequest,
    OrderCreateRequest,
    OrderUpdateRequest,
    OrderItemCreateRequest,
    OrderItemUpdateRequest,
)
from app.modules.products.repository import ProductRepository

logger = logging.getLogger(__name__)

# Tax rate applied to subtotal (configurable, currently 10%).
_TAX_RATE = Decimal("0.10")


def _generate_order_number() -> str:
    """Generates a human-readable order number.

    Format: ORD-{YYYYMMDD}-{8 random hex chars}
    Example: ORD-20260801-A1B2C3D4
    """
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    random_part = secrets.token_hex(4).upper()
    return f"ORD-{date_part}-{random_part}"


class OrderService:
    """Business logic for creating, updating, and managing orders
    through their entire lifecycle."""

    def __init__(
        self,
        db: Session,
        order_repo: OrderRepository,
        item_repo: OrderItemRepository,
        product_repo: ProductRepository,
        stock_service: StockMovementService,
    ) -> None:
        self.db = db
        self.order_repo = order_repo
        self.item_repo = item_repo
        self.product_repo = product_repo
        self.stock_service = stock_service

    # =========================================================================
    # Create Order
    # =========================================================================

    def create_order(
        self, payload: OrderCreateRequest, current_user: User
    ) -> Order:
        """
        Creates a new order with items, reserves inventory, and
        persists everything atomically.

        Business rules:
        1. Validate all products exist and are active.
        2. Validate inventory availability (reserve stock).
        3. Snapshot product names, SKUs, and prices.
        4. Calculate subtotal and total.
        5. Create the order and items in a single transaction.
        6. If any step fails, everything is rolled back.
        """
        # Validate items and build lookup data
        items_data = self._validate_and_prepare_items(payload.items, current_user)

        # Calculate monetary fields
        subtotal = sum(item_data["line_total"] for item_data in items_data)
        if payload.discount > subtotal:
            logger.warning("Order creation rejected: discount exceeds subtotal for customer=%s", current_user.id)
            raise ValidationError("Discount cannot exceed the order subtotal.")
        tax = (subtotal * _TAX_RATE).quantize(Decimal("0.01"))
        total = subtotal + tax + payload.shipping_cost - payload.discount
        total = max(total, Decimal("0.00"))

        # Generate unique order number
        order_number = _generate_order_number()
        while self.order_repo.exists_order_number(order_number):
            order_number = _generate_order_number()

        # Create order
        order = Order(
            order_number=order_number,
            customer_id=current_user.id,
            status=OrderStatus.PENDING,
            subtotal=subtotal,
            tax=tax,
            shipping_cost=payload.shipping_cost,
            discount=payload.discount,
            total=total,
            payment_status=PaymentStatus.UNPAID,
            notes=payload.notes,
            created_by=current_user.id,
            updated_by=current_user.id,
        )
        order = self.order_repo.create(order)

        # Create order items and reserve inventory
        try:
            for item_data in items_data:
                item = OrderItem(
                    order_id=order.id,
                    product_id=item_data["product_id"],
                    product_name=item_data["product_name"],
                    product_sku=item_data["product_sku"],
                    warehouse_id=item_data["warehouse_id"],
                    quantity=item_data["quantity"],
                    unit_price=item_data["unit_price"],
                    line_total=item_data["line_total"],
                )
                self.item_repo.create(item)

                # Reserve stock for this item
                self.stock_service.reserve_stock(
                    product_id=item_data["product_id"],
                    warehouse_id=item_data["warehouse_id"],
                    quantity=item_data["quantity"],
                    current_user_id=current_user.id,
                    reference_number=order_number,
                    notes=f"Order {order_number} item reservation",
                )
        except Exception:
            self.db.rollback()
            raise

        self.db.commit()
        self.db.refresh(order)
        return order

    # =========================================================================
    # Update Order
    # =========================================================================

    def update_order(
        self, order_id: uuid.UUID, payload: OrderUpdateRequest, current_user: User
    ) -> Order:
        """
        Updates an order's editable fields (notes, shipping_cost, discount).

        Only allowed while order is PENDING.
        If shipping_cost or discount changes, the total is recalculated.
        """
        order = self._get_order_or_404(order_id)

        if order.status != OrderStatus.PENDING:
            raise OrderCannotBeModifiedError(
                "Only pending orders can be modified."
            )

        updates = payload.model_dump(exclude_unset=True)

        recalc_total = False
        if "shipping_cost" in updates:
            recalc_total = True
        if "discount" in updates:
            recalc_total = True

        if recalc_total:
            shipping_cost = updates.get("shipping_cost", order.shipping_cost)
            discount = updates.get("discount", order.discount)
            if discount > order.subtotal:
                logger.warning("Order update rejected: discount exceeds subtotal for order=%s", order.order_number)
                raise ValidationError("Discount cannot exceed the order subtotal.")
            total = order.subtotal + order.tax + shipping_cost - discount
            updates["total"] = max(total, Decimal("0.00"))

        updates["updated_by"] = current_user.id
        updated = self.order_repo.update(order, **updates)
        self.db.commit()
        return updated

    # =========================================================================
    # Delete Order
    # =========================================================================

    def delete_order(self, order_id: uuid.UUID, current_user: User) -> None:
        """
        Permanently removes a PENDING order.

        Must release reserved inventory before deletion.
        """
        order = self._get_order_or_404(order_id)

        if order.status != OrderStatus.PENDING:
            raise OrderCannotBeModifiedError(
                "Only pending orders can be deleted."
            )

        self._release_order_inventory(order, current_user)
        self.order_repo.delete(order)
        self.db.commit()

    # =========================================================================
    # Confirm Payment
    # =========================================================================

    def confirm_order(self, order_id: uuid.UUID, current_user: User) -> Order:
        """PENDING -> CONFIRMED. Payment successful."""
        order = self._get_order_or_404(order_id)
        self._validate_transition(order, OrderStatus.CONFIRMED)

        order = self.order_repo.update(
            order,
            status=OrderStatus.CONFIRMED,
            payment_status=PaymentStatus.PAID,
            updated_by=current_user.id,
        )

        for item in order.items:
            self.stock_service.confirm_reservation(
                product_id=item.product_id,
                warehouse_id=item.warehouse_id,
                quantity=item.quantity,
                current_user_id=current_user.id,
                reference_number=order.order_number,
                notes=f"Order {order.order_number} confirmed",
            )

        self.db.commit()
        return order

    # =========================================================================
    # Ship
    # =========================================================================

    def ship_order(self, order_id: uuid.UUID, current_user: User) -> Order:
        """CONFIRMED -> SHIPPED. Carrier picked up."""
        order = self._get_order_or_404(order_id)
        self._validate_transition(order, OrderStatus.SHIPPED)

        order = self.order_repo.update(
            order,
            status=OrderStatus.SHIPPED,
            updated_by=current_user.id,
        )
        self.db.commit()
        return order

    # =========================================================================
    # Deliver
    # =========================================================================

    def deliver_order(self, order_id: uuid.UUID, current_user: User) -> Order:
        """SHIPPED -> DELIVERED. Delivered to customer."""
        order = self._get_order_or_404(order_id)
        self._validate_transition(order, OrderStatus.DELIVERED)

        order = self.order_repo.update(
            order,
            status=OrderStatus.DELIVERED,
            updated_by=current_user.id,
        )
        self.db.commit()
        return order

    # =========================================================================
    # Cancel
    # =========================================================================

    def cancel_order(
        self, order_id: uuid.UUID, payload: CancelOrderRequest, current_user: User
    ) -> Order:
        """Any cancellable status -> CANCELLED.

        Must release reserved inventory.
        Only allowed before SHIPPED.
        """
        order = self._get_order_or_404(order_id)

        if order.status not in CANCELLABLE_STATUSES:
            raise InvalidOrderStatusTransitionError(
                f"Order {order.order_number} is {order.status.value} and "
                f"cannot be cancelled. Only orders in "
                f"{', '.join(s.value for s in CANCELLABLE_STATUSES)} can be cancelled."
            )

        self._release_order_inventory(order, current_user)

        order = self.order_repo.update(
            order,
            status=OrderStatus.CANCELLED,
            cancel_reason=payload.reason if payload else None,
            updated_by=current_user.id,
        )
        self.db.commit()
        return order

    # =========================================================================
    # Return
    # =========================================================================

    def return_order(self, order_id: uuid.UUID, current_user: User) -> Order:
        """DELIVERED -> RETURNED. Customer returned items."""
        order = self._get_order_or_404(order_id)
        self._validate_transition(order, OrderStatus.RETURNED)

        order = self.order_repo.update(
            order,
            status=OrderStatus.RETURNED,
            updated_by=current_user.id,
        )
        self.db.commit()
        return order

    # =========================================================================
    # Refund
    # =========================================================================

    def refund_order(self, order_id: uuid.UUID, current_user: User) -> Order:
        """RETURNED -> REFUNDED. Refund completed."""
        order = self._get_order_or_404(order_id)
        self._validate_transition(order, OrderStatus.REFUNDED)

        order = self.order_repo.update(
            order,
            status=OrderStatus.REFUNDED,
            payment_status=PaymentStatus.REFUNDED,
            updated_by=current_user.id,
        )
        self.db.commit()
        return order

    # =========================================================================
    # Read methods
    # =========================================================================

    def get_order_by_id(self, order_id: uuid.UUID) -> Order:
        """Returns an order by id, or raises NotFoundError."""
        return self._get_order_or_404(order_id)

    def list_orders(
        self,
        *,
        filters,
        page: int,
        page_size: int,
    ) -> tuple[list[Order], int]:
        """Returns paginated, filtered order list."""
        return self.order_repo.list_paginated(
            filters=filters, page=page, page_size=page_size
        )

    def get_orders_for_customer(
        self,
        customer_id: uuid.UUID,
        *,
        filters,
        page: int,
        page_size: int,
    ) -> tuple[list[Order], int]:
        """Returns paginated orders for a specific customer."""
        filters.customer_id = customer_id
        return self.order_repo.list_paginated(
            filters=filters, page=page, page_size=page_size
        )

    # =========================================================================
    # Order Item Management
    # =========================================================================

    def add_item_to_order(
        self, order_id: uuid.UUID, payload: OrderItemCreateRequest, current_user: User
    ) -> OrderItem:
        """Adds a new item to a PENDING order and reserves inventory."""
        order = self._get_order_or_404(order_id)

        if order.status != OrderStatus.PENDING:
            raise OrderCannotBeModifiedError(
                "Items can only be added to pending orders."
            )

        product = self.product_repo.get_by_id(payload.product_id)
        if product is None:
            raise OrderItemValidationError(
                f"Product {payload.product_id} not found."
            )
        if product.status != ProductStatus.ACTIVE:
            raise OrderItemValidationError(
                f"Product '{product.name}' is not active."
            )

        unit_price = product.price
        line_total = unit_price * Decimal(payload.quantity)

        self.stock_service.reserve_stock(
            product_id=payload.product_id,
            warehouse_id=payload.warehouse_id,
            quantity=payload.quantity,
            current_user_id=current_user.id,
            reference_number=order.order_number,
            notes=f"Order {order.order_number} additional item",
        )

        item = OrderItem(
            order_id=order.id,
            product_id=payload.product_id,
            product_name=product.name,
            product_sku=product.sku,
            warehouse_id=payload.warehouse_id,
            quantity=payload.quantity,
            unit_price=unit_price,
            line_total=line_total,
        )
        item = self.item_repo.create(item)

        self._recalculate_order_totals(order)
        self.order_repo.update(order, updated_by=current_user.id)
        self.db.commit()
        return item

    def update_order_item(
        self,
        order_id: uuid.UUID,
        item_id: uuid.UUID,
        payload: OrderItemUpdateRequest,
        current_user: User,
    ) -> OrderItem:
        """Updates an item on a PENDING order (quantity only)."""
        order = self._get_order_or_404(order_id)

        if order.status != OrderStatus.PENDING:
            raise OrderCannotBeModifiedError(
                "Items can only be modified on pending orders."
            )

        item = self.item_repo.get_by_order_and_id(order_id, item_id)
        if item is None:
            raise NotFoundError(
                f"Item {item_id} not found on order {order_id}."
            )

        updates = payload.model_dump(exclude_unset=True)

        if "quantity" in updates:
            old_quantity = item.quantity
            new_quantity = updates["quantity"]

            if new_quantity > old_quantity:
                diff = new_quantity - old_quantity
                self.stock_service.reserve_stock(
                    product_id=item.product_id,
                    warehouse_id=item.warehouse_id,
                    quantity=diff,
                    current_user_id=current_user.id,
                    reference_number=order.order_number,
                    notes=f"Order {order.order_number} item quantity increase",
                )
            elif new_quantity < old_quantity:
                diff = old_quantity - new_quantity
                self.stock_service.release_reservation(
                    product_id=item.product_id,
                    warehouse_id=item.warehouse_id,
                    quantity=diff,
                    current_user_id=current_user.id,
                    reference_number=order.order_number,
                    notes=f"Order {order.order_number} item quantity decrease",
                )

            updates["line_total"] = item.unit_price * Decimal(new_quantity)

        updated_item = self.item_repo.update(item, **updates)
        self._recalculate_order_totals(order)
        self.order_repo.update(order, updated_by=current_user.id)
        self.db.commit()
        return updated_item

    def remove_item_from_order(
        self,
        order_id: uuid.UUID,
        item_id: uuid.UUID,
        current_user: User,
    ) -> None:
        """Removes an item from a PENDING order and releases its inventory."""
        order = self._get_order_or_404(order_id)

        if order.status != OrderStatus.PENDING:
            raise OrderCannotBeModifiedError(
                "Items can only be removed from pending orders."
            )

        item = self.item_repo.get_by_order_and_id(order_id, item_id)
        if item is None:
            raise NotFoundError(
                f"Item {item_id} not found on order {order_id}."
            )

        self.stock_service.release_reservation(
            product_id=item.product_id,
            warehouse_id=item.warehouse_id,
            quantity=item.quantity,
            current_user_id=current_user.id,
            reference_number=order.order_number,
            notes=f"Order {order.order_number} item removed",
        )

        self.item_repo.delete(item)
        self._recalculate_order_totals(order)
        self.order_repo.update(order, updated_by=current_user.id)
        self.db.commit()

    # =========================================================================
    # Internal helpers
    # =========================================================================

    def _get_order_or_404(self, order_id: uuid.UUID) -> Order:
        """Returns an order or raises OrderNotFoundError."""
        order = self.order_repo.get_by_id(order_id)
        if order is None:
            raise OrderNotFoundError(f"No order found with id '{order_id}'.")
        return order

    def _validate_transition(
        self, order: Order, target_status: OrderStatus
    ) -> None:
        """
        Validates that the transition from the order's current status
        to the target status is allowed.

        Uses ORDER_STATUS_TRANSITIONS from constants.py.
        """
        allowed = ORDER_STATUS_TRANSITIONS.get(order.status, set())
        if target_status not in allowed:
            raise InvalidOrderStatusTransitionError(
                f"Cannot transition order {order.order_number} from "
                f"'{order.status.value}' to '{target_status.value}'. "
                f"Allowed transitions from '{order.status.value}': "
                f"{', '.join(s.value for s in allowed) if allowed else 'none (terminal state)'}."
            )

    def _validate_and_prepare_items(
        self, items, current_user: User
    ) -> list[dict]:
        """
        Validates order items and prepares item data dicts.

        Checks:
        - Each product exists.
        - Each product is ACTIVE.
        - Loads product_name, product_sku, unit_price for snapshotting.
        - Calculates line_total for each item.
        """
        items_data = []
        for item in items:
            product = self.product_repo.get_by_id(item.product_id)
            if product is None:
                raise OrderItemValidationError(
                    f"Product {item.product_id} not found."
                )
            if product.status != ProductStatus.ACTIVE:
                raise OrderItemValidationError(
                    f"Product '{product.name}' is not active."
                )

            unit_price = product.price
            line_total = unit_price * Decimal(item.quantity)

            items_data.append(
                {
                    "product_id": item.product_id,
                    "product_name": product.name,
                    "product_sku": product.sku,
                    "warehouse_id": item.warehouse_id,
                    "quantity": item.quantity,
                    "unit_price": unit_price,
                    "line_total": line_total,
                }
            )
        return items_data

    def _release_order_inventory(
        self, order: Order, current_user: User
    ) -> None:
        """
        Releases reserved inventory for all items in an order.

        Called during cancellation or deletion of a pending order.
        Only releases if the order currently has reserved stock
        (PENDING status).
        """
        if order.status not in STATUSES_WITH_RESERVATION:
            return

        for item in order.items:
            try:
                self.stock_service.release_reservation(
                    product_id=item.product_id,
                    warehouse_id=item.warehouse_id,
                    quantity=item.quantity,
                    current_user_id=current_user.id,
                    reference_number=order.order_number,
                    notes=f"Order {order.order_number} cancelled/deleted",
                )
            except Exception:
                logger.exception(
                    "Failed to release inventory for order "
                    "%s, item %s", order.order_number, item.id
                )

    def _recalculate_order_totals(self, order: Order) -> None:
        """
        Recalculates subtotal, tax, and total for an order based on
        its current items.

        Called after items are added, removed, or modified.
        Uses the same _TAX_RATE as create_order for consistency.
        """
        items = self.item_repo.list_by_order(order.id)
        subtotal = sum(item.line_total for item in items)
        tax = (subtotal * _TAX_RATE).quantize(Decimal("0.01"))
        total = subtotal + tax + order.shipping_cost - order.discount
        total = max(total, Decimal("0.00"))

        self.order_repo.update(
            order,
            subtotal=subtotal,
            tax=tax,
            total=total,
        )

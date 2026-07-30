"""
modules/orders/constants.py

Responsibility
--------------
Defines enumerations shared across the orders module's models, services,
and schemas. Centralizing these here avoids circular imports between
models.py and schemas.py.
"""

import enum


class OrderStatus(str, enum.Enum):
    """
    Full lifecycle states for an order.

    The status transition map (enforced in OrderService) is:
        PENDING    → CONFIRMED, CANCELLED
        CONFIRMED  → SHIPPED
        SHIPPED    → DELIVERED
        DELIVERED  → RETURNED
        RETURNED   → REFUNDED
        CANCELLED  → (terminal)
        REFUNDED   → (terminal)

    PENDING:    Stock reserved. Awaiting payment.
    CONFIRMED:  Payment successful.
    SHIPPED:    Carrier picked up.
    DELIVERED:  Delivered to customer.
    CANCELLED:  Cancelled before shipping (inventory released).
    RETURNED:   Returned after delivery.
    REFUNDED:   Refund completed.
    """

    PENDING = "pending"
    CONFIRMED = "confirmed"
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    RETURNED = "returned"
    REFUNDED = "refunded"


class PaymentStatus(str, enum.Enum):
    """
    Payment lifecycle states for an order.

    UNPAID:     No payment received or pending.
    AUTHORIZED: Payment authorized but not yet captured.
    PAID:       Payment captured successfully.
    FAILED:     Payment attempt failed.
    REFUNDED:   Payment refunded after return.
    """

    UNPAID = "unpaid"
    AUTHORIZED = "authorized"
    PAID = "paid"
    FAILED = "failed"
    REFUNDED = "refunded"


# Map of valid transitions: current_status -> set of allowed next statuses.
ORDER_STATUS_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
    OrderStatus.PENDING: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.SHIPPED},
    OrderStatus.SHIPPED: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: {OrderStatus.RETURNED},
    OrderStatus.RETURNED: {OrderStatus.REFUNDED},
    OrderStatus.CANCELLED: set(),   # terminal
    OrderStatus.REFUNDED: set(),    # terminal
}

# Statuses where inventory IS reserved (cancellation must release stock).
STATUSES_WITH_RESERVATION: set[OrderStatus] = {
    OrderStatus.PENDING,
}

# Statuses that allow cancellation.
CANCELLABLE_STATUSES: set[OrderStatus] = {
    OrderStatus.PENDING,
}


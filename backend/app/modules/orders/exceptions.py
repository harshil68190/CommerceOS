"""
modules/orders/exceptions.py

Responsibility
--------------
Domain-specific exceptions for the orders module.

These extend `core/exceptions.AppException` so the global error handler
in `middleware/error_handler.py` catches them automatically and maps
them to the correct HTTP status code.
"""

from app.core.exceptions import AppException


class OrderNotFoundError(AppException):
    """Raised when an order does not exist."""

    status_code = 404
    error_code = "ORDER_NOT_FOUND"


class InvalidOrderStatusTransitionError(AppException):
    """
    Raised when an attempt is made to transition an order to a status
    that is not allowed from its current status.

    For example, trying to ship an order that is still PENDING.
    Maps to HTTP 409 Conflict.
    """

    status_code = 409
    error_code = "INVALID_STATUS_TRANSITION"


class OrderCannotBeModifiedError(AppException):
    """
    Raised when attempting to modify an order that is in a terminal
    or locked state (e.g., CANCELLED, REFUNDED, or already SHIPPED
    when trying to cancel).
    """

    status_code = 409
    error_code = "ORDER_CANNOT_BE_MODIFIED"


class OrderItemValidationError(AppException):
    """
    Raised when one or more order items fail validation:
    - Product not found or inactive
    - Insufficient inventory
    - Invalid warehouse
    """

    status_code = 422
    error_code = "ORDER_ITEM_VALIDATION_ERROR"


class OrderPaymentError(AppException):
    """Raised when a payment operation fails."""

    status_code = 422
    error_code = "ORDER_PAYMENT_ERROR"


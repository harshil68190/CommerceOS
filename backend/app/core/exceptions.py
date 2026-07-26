"""
core/exceptions.py

Responsibility
--------------
Defines the application's own exception hierarchy, completely independent
of FastAPI's `HTTPException`. This matters architecturally: services and
repositories (business/data layers) must never import or raise
`fastapi.HTTPException`, because that would leak an HTTP-layer concept into
layers that have no business knowing about HTTP at all.

Instead, business/data code raises one of the domain exceptions defined
here (e.g. `NotFoundError`, `ConflictError`). The middleware in
`app/middleware/error_handler.py` is the ONLY place that translates these
into HTTP responses. This keeps the dependency direction correct:

    router -> service -> repository
    (HTTP-aware)  (HTTP-agnostic)  (HTTP-agnostic)

Every future module (auth, catalog, orders, ...) should raise subclasses
of `AppException` rather than inventing its own ad-hoc error handling.
"""

from typing import Any, Optional


class AppException(Exception):
    """
    Base class for all application-raised (expected/handled) errors.

    Attributes
    ----------
    message: Human-readable error description, safe to show to a client.
    status_code: The HTTP status code this error should map to.
    error_code: A short, stable machine-readable code (e.g. "NOT_FOUND"),
        useful for frontend clients to branch on without parsing message
        strings.
    details: Optional extra structured context (e.g. which field failed
        validation).
    """

    status_code: int = 500
    error_code: str = "INTERNAL_ERROR"

    def __init__(self, message: str, details: Optional[dict[str, Any]] = None) -> None:
        self.message = message
        self.details = details or {}
        super().__init__(message)


class NotFoundError(AppException):
    """Raised when a requested resource does not exist."""

    status_code = 404
    error_code = "NOT_FOUND"


class ValidationError(AppException):
    """Raised when input fails a business validation rule (not a schema-level error)."""

    status_code = 422
    error_code = "VALIDATION_ERROR"


class ConflictError(AppException):
    """Raised when an operation conflicts with the current state (e.g. duplicate email)."""

    status_code = 409
    error_code = "CONFLICT"


class UnauthorizedError(AppException):
    """Raised when authentication is missing or invalid."""

    status_code = 401
    error_code = "UNAUTHORIZED"


class ForbiddenError(AppException):
    """Raised when an authenticated user lacks permission for the action."""

    status_code = 403
    error_code = "FORBIDDEN"


class ServiceUnavailableError(AppException):
    """Raised when a required downstream dependency (DB, Redis, external API) is unreachable."""

    status_code = 503
    error_code = "SERVICE_UNAVAILABLE"

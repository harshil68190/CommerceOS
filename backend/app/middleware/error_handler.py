"""
middleware/error_handler.py

Responsibility
--------------
The ONLY place in the application that translates exceptions into HTTP
responses. This is the counterpart to `core/exceptions.py`: business and
data-access code raises plain Python exceptions (`AppException`
subclasses) with no knowledge of HTTP; these handlers are what turn that
into a proper status code and JSON body.

Three handlers are registered against the FastAPI app:
  1. `AppException` (and subclasses) -> our own structured error format,
     using each exception's own `status_code`/`error_code`.
  2. `RequestValidationError` -> FastAPI/Pydantic request validation
     failures, reformatted into the same structured shape so API
     consumers only ever deal with one error format.
  3. `Exception` (catch-all) -> anything unexpected. Logged with full
     traceback server-side, but returns a generic 500 to the client —
     never leak internal exception details/stack traces to a caller.

Every response follows the same envelope:
    {
      "error_code": "NOT_FOUND",
      "message": "...",
      "details": {...},
      "request_id": "..."
    }
so frontend/API clients can handle errors uniformly regardless of which
module raised them.
"""

import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import AppException

logger = logging.getLogger(__name__)


def _error_envelope(
    *, error_code: str, message: str, details: dict, request: Request
) -> dict:
    """Builds the consistent error response body shared by all handlers."""
    return {
        "error_code": error_code,
        "message": message,
        "details": details,
        "request_id": getattr(request.state, "request_id", "-"),
    }


def _error_code_from_http_status(status_code: int) -> str:
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return "UNAUTHORIZED"
    if status_code == status.HTTP_403_FORBIDDEN:
        return "FORBIDDEN"
    if status_code == status.HTTP_404_NOT_FOUND:
        return "NOT_FOUND"
    if status_code == status.HTTP_409_CONFLICT:
        return "CONFLICT"
    if status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
        return "REQUEST_VALIDATION_ERROR"
    return "HTTP_ERROR"


def register_exception_handlers(app: FastAPI) -> None:
    """Registers all global exception handlers on the given FastAPI app.
    Called once from the app factory in `app/main.py`."""

    @app.exception_handler(AppException)
    async def handle_app_exception(request: Request, exc: AppException) -> JSONResponse:
        logger.warning(
            "Handled application exception: %s", exc.message,
            extra={"error_code": exc.error_code},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(
                error_code=exc.error_code,
                message=exc.message,
                details=exc.details,
                request=request,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        logger.info("Request validation failed: %s", exc.errors())

        errors = []

        for err in exc.errors():
            err = dict(err)

            if isinstance(err.get("input"), bytes):
                err["input"] = err["input"].decode("utf-8", errors="replace")

            # Pydantic includes the original ValueError in ``ctx`` for
            # validator failures. JSONResponse cannot serialize exception
            # objects, so normalize the complete error payload first.
            errors.append(jsonable_encoder(err, custom_encoder={Exception: str}))

        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=_error_envelope(
                error_code="REQUEST_VALIDATION_ERROR",
                message="The request contained invalid data.",
                details={"errors": errors},
                request=request,
            ),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> JSONResponse:
        detail = exc.detail if isinstance(exc.detail, str) else "Request failed."
        details = (
            {"detail": exc.detail}
            if exc.detail is not None and not isinstance(exc.detail, str)
            else {}
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_envelope(
                error_code=_error_code_from_http_status(exc.status_code),
                message=detail,
                details=details,
                request=request,
            ),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        # Full traceback goes to logs for debugging; the client only ever
        # sees a generic message. Leaking internal exception text (SQL
        # errors, file paths, stack traces) to API clients is a real
        # security/information-disclosure risk.
        logger.exception("Unhandled exception while processing request")
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=_error_envelope(
                error_code="INTERNAL_ERROR",
                message="An unexpected error occurred. Please try again.",
                details={},
                request=request,
            ),
        )

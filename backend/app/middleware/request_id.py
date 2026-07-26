"""
middleware/request_id.py

Responsibility
--------------
Assigns a unique ID to every incoming request (or reuses one supplied by
an upstream caller/load balancer via the `X-Request-ID` header), makes it
available throughout the request via `request.state.request_id` and the
logging ContextVar, and echoes it back on the response.

Why this exists: in production, a single user-facing error usually spans
multiple log lines across multiple layers (router, service, repository).
Without a shared request ID, correlating those lines during an incident
means guessing by timestamp. With it, `grep request_id=<id>` reconstructs
the exact sequence of events for one request.
"""

import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.constants import REQUEST_ID_HEADER
from app.core.logging import request_id_ctx_var


class RequestIDMiddleware(BaseHTTPMiddleware):
    """Ensures every request has a request ID, in state, in logs, and in
    the response headers."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        incoming_id = request.headers.get(REQUEST_ID_HEADER)
        request_id = incoming_id if incoming_id else str(uuid.uuid4())

        # Make the ID available to anything reading `request.state`
        # (e.g. exception handlers) ...
        request.state.request_id = request_id

        # ... and to anything logging via the stdlib `logging` module,
        # anywhere in the call stack, without needing the `request`
        # object passed down through service/repository layers.
        token = request_id_ctx_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            # Always reset the ContextVar, even on exception, so request
            # IDs never leak across requests sharing the same async task
            # in edge cases.
            request_id_ctx_var.reset(token)

        response.headers[REQUEST_ID_HEADER] = request_id
        return response

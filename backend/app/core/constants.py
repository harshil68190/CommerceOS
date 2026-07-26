"""
core/constants.py

Responsibility
--------------
Holds literal values that are shared across multiple modules and are not
environment-specific (those belong in config.py instead). Centralizing
these avoids magic strings scattered across routers/services/middleware.

Kept intentionally small in this milestone — grows as feature modules
(auth, orders, coupons, ...) are implemented and need shared enums or
header names.
"""

# HTTP header used to propagate/assign a unique ID per request, read by
# the request-ID middleware and echoed back in responses/logs for tracing.
REQUEST_ID_HEADER = "X-Request-ID"

# Key used to store the current request ID in the request's `state` and
# in the logging context, so any code within a request can access it.
REQUEST_ID_CTX_KEY = "request_id"

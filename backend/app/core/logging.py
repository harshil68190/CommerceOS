"""
core/logging.py

Responsibility
--------------
Configures application-wide structured (JSON) logging, and exposes a
`request_id` ContextVar that the request-ID middleware populates per
request. Every log line emitted during a request automatically carries
that request's ID, which is essential for tracing a single request's
behavior across routers/services/repositories in production logs.

Design notes
------------
- We use the stdlib `logging` module rather than pulling in a third-party
  logging framework — no need for extra dependency weight at this stage,
  and stdlib logging integrates cleanly with Uvicorn/Gunicorn's own logs.
- JSON output is used so logs are directly ingestible by any log
  aggregator (CloudWatch, ELK, Datadog, etc.) without a separate parser.
- `setup_logging()` is called exactly once, from the FastAPI lifespan
  startup hook in `app/main.py`.
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

# Holds the current request's ID for the lifetime of that request.
# Set by RequestIDMiddleware; read here by the logging filter below.
# Defaults to "-" outside of any request (e.g. during startup).
request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Convenience accessor used anywhere (services, repositories) that
    wants to log with the current request's ID without importing the
    middleware module directly."""
    return request_id_ctx_var.get()


class RequestIdLogFilter(logging.Filter):
    """Injects the current request ID into every LogRecord as `request_id`,
    so it's available to the formatter below regardless of which logger
    emitted the record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()  # type: ignore[attr-defined]
        return True


class JsonFormatter(logging.Formatter):
    """Renders each log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", "-"),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def setup_logging(*, debug: bool = False) -> None:
    """
    Configures the root logger once at application startup.

    In debug mode we keep JSON output (consistency matters more than
    pretty-printing) but set the level to DEBUG for verbose local
    development; production runs at INFO.
    """
    from app.core.config import get_settings

    settings = get_settings()
    root_logger = logging.getLogger()
    root_logger.setLevel(settings.effective_log_level)

    # Remove any handlers configured by default (e.g. by Uvicorn) so we
    # don't get duplicate log lines with two different formats.
    root_logger.handlers.clear()

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdLogFilter())
    root_logger.addHandler(handler)

    is_debug = settings.effective_log_level == "DEBUG"
    # Quiet down noisy third-party loggers unless we're debugging.
    logging.getLogger("uvicorn.access").setLevel(
        logging.WARNING if not is_debug else logging.INFO
    )

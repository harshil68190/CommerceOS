"""
main.py

Responsibility
--------------
The application's composition root. This is the ONLY file that wires
together configuration, logging, middleware, exception handlers, and
routers into a runnable FastAPI app. It contains no business logic and
no routes of its own (the health endpoint lives in `api_router.py`).

We use the "app factory" pattern (`create_app()` returning a configured
`FastAPI` instance) rather than a bare module-level `app = FastAPI()`.
This is deliberate: tests can call `create_app()` with different settings
overrides, and it keeps app construction side-effect-explicit rather than
happening implicitly at import time.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api_router import api_router
from app.core.config import get_settings
from app.core.logging import setup_logging
from app.workers.redis_client import redis_pool
from app.db.session import engine
from app.middleware.error_handler import register_exception_handlers
from app.middleware.request_id import RequestIDMiddleware

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Startup/shutdown hooks, using FastAPI's recommended lifespan context
    manager (replaces the deprecated `@app.on_event` decorators).

    Startup: configure logging before anything else runs, so even the
    earliest log lines are structured correctly.

    Shutdown: dispose of the DB engine's connection pool and close the
    Redis pool cleanly, so the process doesn't leave dangling connections
    behind when the container stops (important for graceful rolling
    deploys).
    """
    settings = get_settings()
    setup_logging(debug=settings.DEBUG)
    logger.info(
        "Starting %s in %s mode", settings.APP_NAME, settings.ENVIRONMENT
    )

    yield

    logger.info("Shutting down %s", settings.APP_NAME)
    engine.dispose()
    redis_pool.disconnect()


def create_app() -> FastAPI:
    """Builds and returns a fully configured FastAPI application instance."""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        debug=settings.DEBUG,
        lifespan=lifespan,
        # Disable interactive API docs (Swagger/ReDoc) in production.
        # The OpenAPI schema endpoints are still reachable if needed, but
        # the interactive UI is a common attack surface / info leak and is
        # not needed in a live environment.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
    )

    # --- Middleware ---------------------------------------------------
    # Order matters: middleware added last runs first (outermost) on the
    # way in. We want the request ID assigned before anything else logs
    # or handles the request, so it's added last here.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(RequestIDMiddleware)

    # --- Exception handling ---------------------------------------------
    register_exception_handlers(app)

    # --- Routers ---------------------------------------------------
    app.include_router(api_router)

    return app


app = create_app()

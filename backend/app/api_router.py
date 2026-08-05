"""
api_router.py

Responsibility
--------------
Single aggregation point for every versioned API router in the
application. `app/main.py` includes only this one router; it never
includes individual module routers directly. This means adding a new
feature module in a future milestone (auth, catalog, orders, ...) is a
one-line change here, and `main.py` never needs to grow.

The health check endpoints required for operations live directly here:

    GET /api/v1/health        -> {"status": "healthy"}   (liveness)
    GET /api/v1/health/ready  -> {"status": "ready"}      (readiness)

Health checks are deliberately NOT placed inside `app/modules/` — they
are infrastructure/ops concerns (used by Docker healthchecks, load
balancers, and orchestrators), not a commerce business module, so they
live directly alongside the router aggregator instead.

Milestone 3 added the first real feature module router: `auth`.
Milestone 4 adds the second: `products`.
"""

from fastapi import APIRouter, HTTPException
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine
from app.workers.redis_client import redis_pool
from app.modules.auth.router import router as auth_router
from app.modules.products.router import router as products_router
from app.modules.inventory.router import router as inventory_router
from app.modules.orders.router import router as orders_router

settings = get_settings()

api_router = APIRouter(prefix=settings.API_V1_PREFIX)

api_router.include_router(auth_router)
api_router.include_router(products_router)
api_router.include_router(inventory_router)
api_router.include_router(orders_router)


@api_router.get("/health", tags=["health"], summary="Liveness check")
def health_check() -> dict[str, str]:
    """
    Basic liveness probe.

    Intentionally lightweight: it confirms the FastAPI process is up and
    able to handle a request, nothing more. It does NOT check DB/Redis
    connectivity — that's the job of the readiness probe
    (`/health/ready`), which orchestrators use to decide whether to
    route traffic to this instance.
    """
    return {"status": "healthy"}


@api_router.get(
    "/health/ready", tags=["health"], summary="Readiness check"
)
def readiness_check() -> dict[str, str]:
    """
    Readiness probe used by orchestrators (e.g. Render's health check) /
    load balancers to decide whether this instance can serve traffic.

    Unlike the liveness probe, this verifies that the two runtime
    dependencies the app cannot function without — PostgreSQL and Redis —
    are actually reachable before the instance is marked ready. An
    instance that cannot reach its dependencies is taken out of rotation
    rather than serving 500s to real users.

    It returns HTTP 200 with a status body when both are healthy, or
    HTTP 503 with details about which dependency failed.
    """
    failures: list[str] = []

    # --- PostgreSQL ------------------------------------------------------
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        failures.append("postgres")

    # --- Redis -----------------------------------------------------------
    try:
        connection = redis_pool.get_connection(command_name="ping")
        try:
            connection.ping()
        finally:
            redis_pool.release(connection)
    except Exception:
        failures.append("redis")

    if failures:
        raise HTTPException(
            status_code=503,
            detail={
                "status": "unhealthy",
                "dependencies": failures,
            },
        )

    return {"status": "ready"}

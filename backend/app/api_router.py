"""
api_router.py

Responsibility
--------------
Single aggregation point for every versioned API router in the
application. `app/main.py` includes only this one router; it never
includes individual module routers directly. This means adding a new
feature module in a future milestone (auth, catalog, orders, ...) is a
one-line change here, and `main.py` never needs to grow.

This milestone defines only the health check endpoint required by the
foundation spec:

    GET /api/v1/health -> {"status": "healthy"}

Health checks are deliberately NOT placed inside `app/modules/` — they
are infrastructure/ops concerns (used by Docker healthchecks, load
balancers, and orchestrators), not a commerce business module, so they
live directly alongside the router aggregator instead.
"""

from fastapi import APIRouter

from app.core.config import get_settings
from app.modules.auth.router import router as auth_router
settings = get_settings()

api_router = APIRouter(prefix=settings.API_V1_PREFIX)
api_router.include_router(auth_router)

@api_router.get("/health", tags=["health"], summary="Liveness check")
def health_check() -> dict[str, str]:
    """
    Basic liveness probe.

    Intentionally lightweight: it confirms the FastAPI process is up and
    able to handle a request, nothing more. It does NOT check DB/Redis
    connectivity — that's a deliberate scope decision for this milestone
    (a "readiness" probe that verifies downstream dependencies is a
    natural, separate addition once those dependencies are actually used
    by real endpoints).
    """
    return {"status": "healthy"}

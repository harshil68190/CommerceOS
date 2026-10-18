"""
modules/intelligence/router.py

Responsibility
--------------
HTTP layer for CommerceOS Intelligence. All endpoints are ADMIN only and
read-only (POST /simulate computes a scenario; it persists nothing).

    GET  /intelligence/dashboard
    GET  /intelligence/products/{product_id}
    POST /intelligence/simulate
"""

import uuid

from fastapi import APIRouter, Depends, Query, status

from app.models.user import User
from app.modules.intelligence.constants import (
    DEFAULT_HORIZON_DAYS,
    DEFAULT_LEAD_TIME_DAYS,
    DEFAULT_LIST_LIMIT,
    MAX_LEAD_TIME_DAYS,
    MAX_LIST_LIMIT,
    MIN_LEAD_TIME_DAYS,
)
from app.modules.intelligence.dependencies import get_intelligence_service
from app.modules.intelligence.permissions import require_intelligence_admin
from app.modules.intelligence.schemas import (
    DashboardResponse,
    HorizonDays,
    ProductIntelligenceResponse,
    SimulationRequest,
    SimulationResponse,
)
from app.modules.intelligence.service import IntelligenceService

router = APIRouter(prefix="/intelligence", tags=["intelligence"])


@router.get(
    "/dashboard",
    response_model=DashboardResponse,
    status_code=status.HTTP_200_OK,
    summary="Inventory intelligence dashboard (admin only)",
)
def get_dashboard(
    horizon_days: HorizonDays = Query(default=DEFAULT_HORIZON_DAYS),
    lead_time_days: int = Query(
        default=DEFAULT_LEAD_TIME_DAYS, ge=MIN_LEAD_TIME_DAYS, le=MAX_LEAD_TIME_DAYS
    ),
    limit: int = Query(default=DEFAULT_LIST_LIMIT, ge=1, le=MAX_LIST_LIMIT),
    _current_user: User = Depends(require_intelligence_admin),
    service: IntelligenceService = Depends(get_intelligence_service),
) -> DashboardResponse:
    """Risk KPIs, highest-risk stock positions, reorder recommendations and
    forecast-vs-actual demand, all derived from live orders and inventory."""
    return service.get_dashboard(
        horizon_days=horizon_days, lead_time_days=lead_time_days, limit=limit
    )


@router.get(
    "/products/{product_id}",
    response_model=ProductIntelligenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Per-product intelligence with reasoning (admin only)",
)
def get_product_intelligence(
    product_id: uuid.UUID,
    horizon_days: HorizonDays = Query(default=DEFAULT_HORIZON_DAYS),
    lead_time_days: int = Query(
        default=DEFAULT_LEAD_TIME_DAYS, ge=MIN_LEAD_TIME_DAYS, le=MAX_LEAD_TIME_DAYS
    ),
    _current_user: User = Depends(require_intelligence_admin),
    service: IntelligenceService = Depends(get_intelligence_service),
) -> ProductIntelligenceResponse:
    """Forecast, projected inventory, stockout date, risk reasoning and the
    itemised reorder calculation for every warehouse holding the product."""
    return service.get_product(
        product_id, horizon_days=horizon_days, lead_time_days=lead_time_days
    )


@router.post(
    "/simulate",
    response_model=SimulationResponse,
    status_code=status.HTTP_200_OK,
    summary="What-if demand simulation (admin only, read-only)",
)
def simulate(
    payload: SimulationRequest,
    _current_user: User = Depends(require_intelligence_admin),
    service: IntelligenceService = Depends(get_intelligence_service),
) -> SimulationResponse:
    """Applies a percentage change to baseline demand and reports the
    changed risk, projected stockouts and additional reorder units."""
    return service.simulate(payload)

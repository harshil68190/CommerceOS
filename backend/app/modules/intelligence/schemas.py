"""
modules/intelligence/schemas.py

Responsibility
--------------
Request/response shapes for the intelligence API (Pydantic v2). Numbers
are rounded for display here; calculations upstream use full precision.
"""

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field

from app.modules.intelligence.constants import (
    DEFAULT_HORIZON_DAYS,
    Horizon,
    MAX_DEMAND_CHANGE_PERCENT,
    MAX_LEAD_TIME_DAYS,
    MIN_DEMAND_CHANGE_PERCENT,
    MIN_LEAD_TIME_DAYS,
    ForecastConfidence,
    RiskLevel,
)

HorizonDays = Horizon


# --- Shared building blocks ------------------------------------------------


class Assumptions(BaseModel):
    """The policy numbers behind every result, echoed for transparency."""

    horizon_days: int
    lead_time_days: int
    service_level_z: float
    forecast_weights: dict[str, float]
    risk_thresholds_days: dict[str, float]
    demand_statuses: list[str]
    history_window_days: int
    notes: list[str]


class ForecastOut(BaseModel):
    daily_rate: float
    ma_7: float
    ma_14: float
    ma_30: float
    sigma_daily: float
    history_days: int
    total_units_in_history: int
    confidence: ForecastConfidence
    forecast_demand_horizon: float


class RiskOut(BaseModel):
    level: RiskLevel
    days_of_cover: float | None
    reasons: list[str]


class ReorderOut(BaseModel):
    available: int
    lead_time_demand: float
    safety_stock: float
    computed_reorder_point: float
    configured_reorder_level: int
    effective_reorder_point: int
    target_stock: int
    max_stock: int
    capped_by_max_stock: bool
    reorder_needed: bool
    recommended_quantity: int
    reasons: list[str]


class ProjectionPointOut(BaseModel):
    day: date
    projected_stock: float
    cumulative_demand: float


class DemandPointOut(BaseModel):
    """One day of demand: actual (history) and/or forecast."""

    day: date
    actual: float | None = None
    forecast: float | None = None


class PositionOut(BaseModel):
    """Full analysis of one product x warehouse stock position."""

    product_id: uuid.UUID
    product_name: str
    product_sku: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    warehouse_code: str
    quantity: int
    reserved_quantity: int
    available: int
    reorder_level: int
    max_stock: int
    forecast: ForecastOut
    risk: RiskOut
    stockout_date: date | None
    stocks_out_in_horizon: bool
    unserved_demand: float
    reorder: ReorderOut
    reasoning: list[str]
    wape: float | None = None
    projection: list[ProjectionPointOut] = Field(default_factory=list)
    demand_history: list[DemandPointOut] = Field(default_factory=list)


class PositionSummary(BaseModel):
    """Compact row for dashboard tables."""

    product_id: uuid.UUID
    product_name: str
    product_sku: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    warehouse_code: str
    available: int
    daily_rate: float
    days_of_cover: float | None
    risk_level: RiskLevel
    stockout_date: date | None
    stocks_out_in_horizon: bool
    confidence: ForecastConfidence
    recommended_quantity: int
    reorder_needed: bool


class RiskCounts(BaseModel):
    healthy: int = 0
    low: int = 0
    medium: int = 0
    high: int = 0


class Kpis(BaseModel):
    total_positions: int
    positions_with_demand: int
    risk_counts: RiskCounts
    projected_stockouts: int
    positions_needing_reorder: int
    total_recommended_units: int
    total_unserved_demand: float


# --- Dashboard -------------------------------------------------------------


class DashboardResponse(BaseModel):
    generated_at: datetime
    as_of_date: date
    assumptions: Assumptions
    kpis: Kpis
    high_risk: list[PositionSummary]
    reorder_recommendations: list[PositionSummary]
    demand_trend: list[DemandPointOut]
    network_wape: float | None
    has_demand_history: bool


# --- Product detail --------------------------------------------------------


class ProductAggregate(BaseModel):
    total_available: int
    total_daily_rate: float
    total_recommended_quantity: int
    worst_risk: RiskLevel
    earliest_stockout_date: date | None
    projected_stockouts: int


class ProductIntelligenceResponse(BaseModel):
    generated_at: datetime
    as_of_date: date
    product_id: uuid.UUID
    product_name: str
    product_sku: str
    assumptions: Assumptions
    aggregate: ProductAggregate
    positions: list[PositionOut]
    demand_trend: list[DemandPointOut]


# --- Simulation ------------------------------------------------------------


class SimulationRequest(BaseModel):
    demand_change_percent: float = Field(
        ge=MIN_DEMAND_CHANGE_PERCENT,
        le=MAX_DEMAND_CHANGE_PERCENT,
        description="Percent change applied to baseline demand, e.g. 20 = +20%.",
    )
    horizon_days: HorizonDays = DEFAULT_HORIZON_DAYS
    lead_time_days: int | None = Field(
        default=None, ge=MIN_LEAD_TIME_DAYS, le=MAX_LEAD_TIME_DAYS
    )
    product_id: uuid.UUID | None = Field(
        default=None, description="Limit the scenario to one product."
    )
    warehouse_id: uuid.UUID | None = Field(
        default=None, description="Limit the scenario to one warehouse."
    )


class SimulationDelta(BaseModel):
    """Baseline vs scenario for one position whose outcome changed."""

    product_id: uuid.UUID
    product_name: str
    product_sku: str
    warehouse_id: uuid.UUID
    warehouse_name: str
    warehouse_code: str
    available: int
    baseline_daily_rate: float
    scenario_daily_rate: float
    baseline_risk: RiskLevel
    scenario_risk: RiskLevel
    risk_changed: bool
    baseline_stockout_date: date | None
    scenario_stockout_date: date | None
    baseline_stocks_out_in_horizon: bool
    scenario_stocks_out_in_horizon: bool
    newly_stocking_out: bool
    baseline_recommended_quantity: int
    scenario_recommended_quantity: int
    additional_reorder_quantity: int


class ScenarioSummary(BaseModel):
    risk_counts: RiskCounts
    projected_stockouts: int
    positions_needing_reorder: int
    total_recommended_units: int
    total_unserved_demand: float


class SimulationResponse(BaseModel):
    generated_at: datetime
    as_of_date: date
    demand_change_percent: float
    assumptions: Assumptions
    positions_analyzed: int
    changed_positions_count: int
    baseline: ScenarioSummary
    scenario: ScenarioSummary
    additional_projected_stockouts: int
    additional_reorder_units: int
    positions_with_risk_change: int
    positions_with_stockout_date_change: int
    newly_projected_stockouts: int
    changed_positions: list[SimulationDelta]
